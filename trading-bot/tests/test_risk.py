from datetime import datetime, timedelta, timezone

import pytest

from apps.risk.engine import (
    AccountState, Action, Candidate, Position, RiskLimits,
    circuit_breakers, evaluate_entry, locked_reserve, manage_position,
    manual_kill, position_size, tighten_only,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
L = RiskLimits()


def acct(**kw) -> AccountState:
    base = dict(starting_equity=500, equity=500, peak_equity=500, day_start_equity=500, week_start_equity=500)
    base.update(kw)
    return AccountState(**base)


def cand(**kw) -> Candidate:
    # entry 100, 2% stop, 4% target -> RR 2.0
    base = dict(symbol="BTC/USDT", entry=100.0, stop=98.0, take=104.0, spread_bps=2.0, data_age_sec=5)
    base.update(kw)
    return Candidate(**base)


# ------------------------------------------------ config file matches code defaults
def test_yaml_matches_defaults():
    assert RiskLimits.load() == RiskLimits()


# ------------------------------------------------ sizing
def test_size_is_one_percent_risk_capped_by_position():
    # 1% of 500 = $5 risk; 2% stop -> $250 by risk, but max position 20% = $100
    stake, notes = position_size(acct(), L, stop_pct=0.02)
    assert stake == 100.0
    assert "capped by max_position_pct" in notes

def test_size_uses_risk_when_below_cap():
    # 0.5x -> $2.50 risk / 2.5% stop = $100 -> equals cap; use 0.25x -> $50
    stake, _ = position_size(acct(), L, stop_pct=0.025, risk_mult=0.25)
    assert stake == 50.0

def test_risk_mult_cannot_increase_size():
    a, _ = position_size(acct(equity=5000, peak_equity=5000), L, 0.02, risk_mult=1.0)
    b, notes = position_size(acct(equity=5000, peak_equity=5000), L, 0.02, risk_mult=3.0)
    assert a == b
    assert any("clamped" in n for n in notes)

def test_cash_reserve_and_inventory_limit_stake():
    # deployable = 500*0.7 - 330 inventory = $20
    stake, notes = position_size(acct(inventory_usd=330), L, 0.02)
    assert stake == 20.0
    assert any("reserve" in n for n in notes)

def test_runtime_risk_override_is_clamped():
    s = acct(equity=10_000, peak_equity=10_000, risk_per_trade_pct=0.50)   # absurd /set value
    stake, _ = position_size(s, L, 0.02)
    # clamped to 1.5% -> $150 risk / 2% = $7500, capped at 20% = $2000
    assert stake == 2000.0
    assert L.clamp_risk_pct(0.001) == 0.005


# ------------------------------------------------ circuit breakers
def test_daily_loss_pauses_24h():
    s = acct(equity=484)        # -3.2% today
    v = circuit_breakers(s, L, NOW)
    assert v.action is Action.PAUSE
    assert s.paused_until == NOW + timedelta(hours=24)
    # still paused an hour later even if equity recovers
    s.equity = 500
    assert circuit_breakers(s, L, NOW + timedelta(hours=1)).action is Action.PAUSE
    assert circuit_breakers(s, L, NOW + timedelta(hours=25)) is None

def test_weekly_loss_kills():
    s = acct(equity=455, day_start_equity=455)   # -9% week, flat today
    assert circuit_breakers(s, L, NOW).action is Action.KILL
    assert s.killed

def test_drawdown_from_peak_kills():
    s = acct(equity=520, peak_equity=600, day_start_equity=520, week_start_equity=520)  # -13.3% from peak
    v = circuit_breakers(s, L, NOW)
    assert v.action is Action.KILL and "drawdown" in v.reasons[0]

def test_kill_is_sticky():
    s = acct()
    manual_kill(s)
    s.equity = 10_000
    assert evaluate_entry(s, L, cand(), NOW).action is Action.KILL


# ------------------------------------------------ entry gate
def test_happy_path_allows():
    v = evaluate_entry(acct(), L, cand(), NOW)
    assert v.allowed and v.stake_usd == 100.0 and v.reward_risk == 2.0

@pytest.mark.parametrize("override,fragment", [
    (dict(data_age_sec=600), "stale"),
    (dict(spread_bps=25), "spread"),
    (dict(stop=101.0), "spot long only"),
    (dict(stop=97.0), "too volatile"),            # 3% stop > 2.5%
    (dict(take=102.0), "reward/risk"),            # RR 1.0
])
def test_entry_skips(override, fragment):
    v = evaluate_entry(acct(), L, cand(**override), NOW)
    assert v.action is Action.SKIP
    assert any(fragment in r for r in v.reasons), v.reasons

def test_max_open_positions_and_one_per_symbol():
    assert evaluate_entry(acct(open_positions=2), L, cand(), NOW).action is Action.SKIP
    v = evaluate_entry(acct(open_positions=1, open_symbols=frozenset({"BTC/USDT"})), L, cand(), NOW)
    assert any("already in" in r for r in v.reasons)

def test_tight_stop_is_widened_not_trusted():
    # 0.5% stop -> widened to 1.5%; target 4% -> RR 2.67
    v = evaluate_entry(acct(), L, cand(stop=99.5), NOW)
    assert v.allowed and v.stop_pct == pytest.approx(0.015)
    assert v.stop == pytest.approx(98.5)

def test_target_must_beat_fees():
    tiny = RiskLimits(stop_min_pct=0.001, min_reward_risk=1.0)
    # 0.5% target vs 2.5 x 0.36% = 0.9% required
    v = evaluate_entry(acct(), tiny, cand(stop=99.7, take=100.5), NOW)
    assert v.action is Action.SKIP and any("edge after fees" in r for r in v.reasons)

def test_below_min_stake_skips():
    v = evaluate_entry(acct(inventory_usd=345), L, cand(), NOW)   # $5 deployable
    assert v.action is Action.SKIP and any("min" in r for r in v.reasons)


# ------------------------------------------------ profit lock
def test_profit_lock():
    assert locked_reserve(acct(realized_pnl_total=40), L) == 0.0     # +8%: below trigger
    assert locked_reserve(acct(realized_pnl_total=60), L) == 30.0    # +12%: lock half


# ------------------------------------------------ position management
def pos(**kw) -> Position:
    base = dict(symbol="BTC/USDT", entry=100, stop=98, take=104, stake_usd=100, opened_at=NOW)
    base.update(kw)
    return Position(**base)

def test_stop_and_target_and_time_stop():
    assert manage_position(pos(), 97.9, NOW, L).action == "exit"
    assert manage_position(pos(), 104.1, NOW, L).action == "exit"
    assert manage_position(pos(), 100.5, NOW + timedelta(hours=49), L).action == "exit"
    assert manage_position(pos(), 100.5, NOW, L).action == "hold"

def test_trailing_after_1_2R():
    # R = 2. At +1.2R (102.4) trail to price - R = 100.4
    d = manage_position(pos(), 102.5, NOW, L)
    assert d.action == "tighten" and d.new_stop == pytest.approx(100.5)

def test_stops_only_move_up():
    p = pos(stop=100.5)
    assert tighten_only(p, 99.0).stop == 100.5
    assert tighten_only(p, 101.0).stop == 101.0
