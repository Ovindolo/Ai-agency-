import time
from datetime import datetime, timezone

from apps.backtest.engine import bar_exit, run_backtest
from apps.risk.engine import Position, RiskLimits
from tests.helpers import synthetic_15m

L = RiskLimits()
NOW = datetime(2026, 1, 5, tzinfo=timezone.utc)


def uptrend():
    return synthetic_15m(n=6000, drift=0.0004, seed=11)


def test_runs_fast_and_reports_honestly():
    df = uptrend()
    t0 = time.perf_counter()
    r = run_backtest(df, "BTC/USDT", label="synthetic")
    assert time.perf_counter() - t0 < 30
    assert r.n > 0, "regression: every signal was vetoed by risk"
    md = r.markdown()
    assert "Buy-and-hold" in md and "Profit factor" in md
    for t in r.trades:
        assert t.fees > 0 and t.exit_time > t.entry_time


def test_entries_fill_next_bar_open_with_slippage():
    df = uptrend()
    r = run_backtest(df, "BTC/USDT", label="x")
    assert r.trades
    for t in r.trades:
        assert abs(t.entry - df.loc[t.entry_time, "open"] * (1 + L.slippage_pct)) < 1e-9


def pos():
    return Position("BTC/USDT", 100.0, 98.0, 104.0, 100.0, NOW)


def test_stop_wins_when_both_hit_in_one_bar():
    px, why = bar_exit(pos(), o=100, h=105, l=97, c=101, t=NOW, limits=L)
    assert why == "stop" and px == 98.0 * (1 - L.slippage_pct)


def test_gap_through_stop_fills_at_open_not_stop():
    px, why = bar_exit(pos(), o=96, h=97, l=95, c=96.5, t=NOW, limits=L)
    assert why == "stop" and px == 96 * (1 - L.slippage_pct)


def test_target_and_hold():
    assert bar_exit(pos(), 100, 104.5, 99.5, 104, NOW, L)[1] == "target"
    assert bar_exit(pos(), 100, 101, 99.5, 100.5, NOW, L) == (None, "")


def test_jev_replay_without_records_equals_rules_only():
    df = uptrend()
    a = run_backtest(df, "BTC/USDT", label="A")
    b = run_backtest(df, "BTC/USDT", label="B", use_jev=True, jev_records={})
    assert [t.pnl for t in a.trades] == [t.pnl for t in b.trades]
    assert b.jev_coverage == 0.0


def test_recorded_veto_removes_every_trade():
    df = uptrend()
    a = run_backtest(df, "BTC/USDT", label="A")
    veto = {"regime": {"type": "choice", "choice": "chop", "confidence": 0.9, "probabilities": {}},
            "setup_quality": {"type": "score", "score": 0.5, "confidence": 0.9},
            "aligned_with_signal": {"type": "noul", "noul": 0.1},
            "toxic_or_unstable": {"type": "noul", "noul": 0.9}}
    b = run_backtest(df, "BTC/USDT", label="B", use_jev=True, jev_records={ts.isoformat(): {"answers": veto} for ts in df.index})
    assert a.n > 0 and b.n == 0 and b.jev_coverage == 1.0
