import json

import pandas as pd
import pytest

from apps.backtest.run import recorded_jev
from apps.jev.client import FakeBackend, JevClient, parse_answers
from apps.strategy.trend_pullback import StrategyParams, indicators
from apps.trader.notify import Notifier
from apps.trader.runner import BAR, Runner
from apps.trader.sources import ReplaySource
from tests.helpers import synthetic_15m
from tests.test_jev_policy import GOOD

SYM = "BTC/USDT"


@pytest.fixture(scope="module")
def market():
    """Trending synthetic data plus the close times of bars where the strategy fires."""
    df = synthetic_15m(n=1600, drift=0.0004, vol=0.004, seed=3)
    sig = indicators(df, StrategyParams())["signal"].astype(bool)
    closes = [t + BAR for t in df.index[400:][sig.iloc[400:].to_numpy()]]
    assert closes, "fixture needs at least one signal"
    return df, [t.to_pydatetime() for t in closes]


def make(tmp_path, df, now, jev=None):
    tg = Notifier(token="", chat_id="", echo=False)
    jev = jev or JevClient(enabled=False, log_path=None)
    return Runner(ReplaySource({SYM: df}), [SYM], jev=jev, notifier=tg, base=tmp_path, now=now), tg


def decisions(tmp_path):
    p = tmp_path / "logs" / "decisions.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


def test_signal_opens_paper_position_with_fallback(tmp_path, market):
    df, sig_times = market
    bot, tg = make(tmp_path, df, sig_times[0])
    bot.step(sig_times[0])
    assert SYM in bot.positions
    pos = bot.positions[SYM]
    assert pos.entry > float(df.loc[pd.Timestamp(sig_times[0]), "open"])     # paid ask + slippage over next open
    assert pos.stake_usd <= 0.20 * 500 + 1e-9
    assert bot.cash == pytest.approx(500 - pos.stake_usd * 1.001)
    assert any(m.startswith("🟦 INTRARE") for m in tg.sent)
    rec = decisions(tmp_path)[-1]
    assert rec["action"] == "enter" and rec["policy_fallback"] == "jev_disabled" and rec["jev_answers"] is None


def test_state_survives_restart(tmp_path, market):
    df, sig_times = market
    bot, _ = make(tmp_path, df, sig_times[0])
    bot.step(sig_times[0])
    again, tg = make(tmp_path, df, sig_times[0])
    assert again.cash == pytest.approx(bot.cash)
    assert again.positions == bot.positions
    assert not tg.sent                              # no second "bot pornit" on restart
    again.step(sig_times[0] + BAR)                  # and it keeps running from the restored state


def test_kill_from_control_file_blocks_entries(tmp_path, market):
    df, sig_times = market
    bot, tg = make(tmp_path, df, sig_times[0])
    (tmp_path / "data" / "control.json").write_text(json.dumps({"kill": True}))
    bot.step(sig_times[0])
    assert not bot.positions and bot.acct.killed
    assert any("KILL" in m for m in tg.sent)


def test_pause_blocks_entries(tmp_path, market):
    df, sig_times = market
    bot, _ = make(tmp_path, df, sig_times[0])
    (tmp_path / "data" / "control.json").write_text(json.dumps({"paused": True}))
    bot.step(sig_times[0])
    assert not bot.positions


def test_risk_override_is_clamped(tmp_path, market):
    df, sig_times = market
    bot, _ = make(tmp_path, df, sig_times[0])
    (tmp_path / "data" / "control.json").write_text(json.dumps({"risk_per_trade_pct": 0.5}))   # 50%: absurd
    bot.step(sig_times[0])
    pos = bot.positions[SYM]
    risk_usd = pos.stake_usd * (pos.entry - pos.stop) / pos.entry
    assert risk_usd <= 0.015 * 500 + 0.01          # max 1.5% of equity whatever the file says


def test_late_jev_holds(tmp_path, market):
    df, sig_times = market
    jev = JevClient(api_key="t", backend=FakeBackend(GOOD, delay_s=0.05), timeout_ms=10, log_path=None)
    bot, tg = make(tmp_path, df, sig_times[0], jev=jev)
    bot.step(sig_times[0])
    assert not bot.positions
    assert any("prea târziu" in m for m in tg.sent)
    assert decisions(tmp_path)[-1]["policy_fallback"] == "jev_late_hold"


def test_jev_answers_logged_in_replayable_form(tmp_path, market, monkeypatch):
    df, sig_times = market
    jev = JevClient(api_key="t", backend=FakeBackend(GOOD), log_path=None)
    bot, _ = make(tmp_path, df, sig_times[0], jev=jev)
    bot.step(sig_times[0])
    rec = decisions(tmp_path)[-1]
    parsed = parse_answers(rec["jev_answers"])
    assert parsed["setup_quality"].score == 2.4 and parsed["regime"].choice == "trending_up"
    monkeypatch.setattr("apps.backtest.run.ROOT", tmp_path)
    assert rec["snapshot_ts"] in recorded_jev(SYM)


def test_outcome_logged_one_bar_later(tmp_path, market):
    df, sig_times = market
    bot, _ = make(tmp_path, df, sig_times[0])
    bot.step(sig_times[0])
    bot.step(sig_times[0] + BAR)
    outs = [r for r in decisions(tmp_path) if r["type"] == "outcome"]
    assert outs and isinstance(outs[0]["ret_15m"], float)


def test_position_eventually_closes_and_ledger_written(tmp_path, market):
    df, sig_times = market
    t0 = sig_times[0]
    bot, tg = make(tmp_path, df, t0)
    t = t0
    for _ in range(200):                            # 48h time stop guarantees an exit within 192 bars
        bot.step(t)
        if bot.trades:
            break
        t += BAR
    assert bot.trades == 1
    ledger = (tmp_path / "context" / "Trade_Ledger.md").read_text()
    assert "| 1 | BTC/USDT |" in ledger
    assert any("IEȘIRE" in m for m in tg.sent)
    assert bot.acct.equity == pytest.approx(bot.cash + bot.acct.inventory_usd)


def test_replay_only_sees_closed_candles(market):
    df, sig_times = market
    src = ReplaySource({SYM: df})
    seen = src.candles(SYM, sig_times[0])
    assert seen.index[-1] + BAR == pd.Timestamp(sig_times[0])
