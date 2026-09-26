from datetime import datetime, timezone

import pandas as pd
import pytest

from apps.audit.signals import Costs, Signal, audit, evaluate, parse, report

T0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
NOFEE = Costs(fee_pct=0.0, slippage_pct=0.0, funding_pct_8h=0.0)


def bars(rows):
    """rows of (open, high, low, close), 15m apart from T0."""
    idx = pd.date_range(T0, periods=len(rows), freq="15min")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def sig(**kw):
    base = dict(group="G", time=T0, symbol="BTC/USDT", side="long", entry=100.0, stop=98.0, targets=(102.0, 104.0),
                leverage=1.0)
    base.update(kw)
    return Signal(**base)


def test_limit_entry_never_reached_is_unfilled():
    o = evaluate(sig(entry=95.0, stop=94.0), bars([(100, 101, 99, 100)] * 8), NOFEE)
    assert o.status == "unfilled" and not o.filled


def test_both_targets_hit():
    o = evaluate(sig(), bars([(100.5, 100.6, 99.9, 100.2), (100.2, 102.5, 100.1, 102.2), (102.2, 104.5, 102, 104)]), NOFEE)
    assert [e[0] for e in o.exits] == ["TP1", "TP2"]
    assert o.move_pct == pytest.approx(0.5 * 0.02 + 0.5 * 0.04)
    assert o.r == pytest.approx(0.03 / 0.02)


def test_stop_and_target_in_same_bar_counts_as_stop():
    o = evaluate(sig(), bars([(100.5, 100.6, 99.9, 100.2), (100.2, 103, 97.5, 100)]), NOFEE)
    assert o.exits[0][0] == "stop" and o.r == pytest.approx(-1.0)


def test_breakeven_after_tp1():
    o = evaluate(sig(), bars([(100.5, 100.6, 99.9, 100.2), (100.2, 102.5, 100.1, 102), (102, 102.1, 99.5, 99.8)]), NOFEE)
    assert [e[0] for e in o.exits] == ["TP1", "stop"]
    assert o.move_pct == pytest.approx(0.5 * 0.02)          # second half out at entry


def test_leverage_liquidates_before_a_wide_stop():
    # 20x: margin gone at about -4.5%; the stop at -8% is never reached
    o = evaluate(sig(stop=92.0, leverage=20), bars([(100.5, 100.6, 99.9, 100.2), (100.2, 100.3, 95.0, 95.5)]), NOFEE)
    assert o.status == "liquidated" and o.margin_pct == -1.0


def test_costs_and_funding_reduce_the_result():
    b = bars([(100.5, 100.6, 99.9, 100.2), (100.2, 104.5, 100.1, 104)])
    free = evaluate(sig(leverage=10), b, NOFEE)
    paid = evaluate(sig(leverage=10), b, Costs(fee_pct=0.0005, slippage_pct=0.0, funding_pct_8h=0.0001))
    assert paid.margin_pct < free.margin_pct
    assert free.margin_pct == pytest.approx(10 * free.move_pct)


def test_short_side():
    o = evaluate(sig(side="short", entry=100.0, stop=102.0, targets=(98.0,)),
                 bars([(99.5, 100.2, 99.4, 99.8), (99.8, 99.9, 97.5, 97.8)]), NOFEE)
    assert o.exits[0][0] == "TP1" and o.move_pct == pytest.approx(0.02)


def test_invalid_signal():
    assert evaluate(sig(stop=101.0), bars([(100, 101, 99, 100)]), NOFEE).status == "invalid"


def test_parse_and_report(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("group,time,symbol,side,entry,stop,targets,leverage\n"
                 "VIP,2026-09-01 12:00,btc/usdt,long,100,98,102|104,10\n"
                 "VIP,2026-09-01 12:00,BTC/USDT,long,market,98,102,5\n"
                 "Other,2026-09-01 12:00,ETH/USDT,long,100,98,102,1\n")
    sigs = parse(p)
    assert sigs[0].symbol == "BTC/USDT" and sigs[1].entry is None and sigs[0].targets == (102.0, 104.0)
    groups = audit(sigs, {"BTC/USDT": bars([(100.5, 100.6, 99.9, 100.2), (100.2, 104.5, 100.1, 104)])}, NOFEE,
                   monthly_fee=30)
    md = report(groups)
    assert "VIP" in md and "Other" in md
    other = next(g for g in groups if g.group == "Other")
    assert other.outcomes[0].status == "no_data"
    assert next(g for g in groups if g.group == "VIP").row()["subscription"] == pytest.approx(30)
