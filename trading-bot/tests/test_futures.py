import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apps.futures.exchange import BinanceFuturesReader
from apps.futures.guard import Dedup, GuardConfig, check, resolved_text, tick
from apps.futures.journal import build_journal, markdown, verdict
from apps.futures.models import FPosition, StopOrder, position_from_ccxt, protective_stops, stop_from_raw

CFG = GuardConfig()
NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)


def pos(**kw):
    base = dict(symbol="BTCUSDT", side="long", qty=0.01, entry=60000.0, mark=61000.0, leverage=3.0, liq=41000.0,
                unrealized=10.0)
    base.update(kw)
    return FPosition(**base)


def keys(alerts):
    return {a.key.split(":")[0] for a in alerts}


def test_no_code_path_places_or_cancels_orders():
    src = "".join(p.read_text() for p in Path("apps/futures").glob("*.py"))
    assert not re.search(r"create_order|cancel_order|edit_order|Post[A-Z]|Delete[A-Z]|Put[A-Z]", src)


def test_config_file_matches_defaults():
    assert GuardConfig.load() == GuardConfig()


def test_algo_orders_are_read_as_stops():
    # since 2025-12-09 Binance returns conditional orders from /fapi/v1/openAlgoOrders with triggerPrice
    algo = {"algoId": 1, "symbol": "BTCUSDT", "side": "SELL", "positionSide": "BOTH", "triggerPrice": "59000",
            "quantity": "0.01", "reduceOnly": True, "algoType": "CONDITIONAL", "orderType": "STOP_MARKET"}
    legacy = {"symbol": "BTCUSDT", "side": "SELL", "stopPrice": "58000", "closePosition": "true", "type": "STOP_MARKET"}
    opening = {"symbol": "BTCUSDT", "side": "BUY", "stopPrice": "62000", "reduceOnly": False, "positionSide": "BOTH"}
    assert stop_from_raw(algo) == StopOrder("BTCUSDT", "SELL", 59000.0, 0.01)
    assert stop_from_raw(legacy).qty is None
    assert stop_from_raw(opening) is None


def test_take_profit_is_not_a_stop():
    tp = StopOrder("BTCUSDT", "SELL", 65000.0, 0.01)
    sl = StopOrder("BTCUSDT", "SELL", 59000.0, 0.01)
    assert protective_stops(pos(), [tp, sl]) == [sl]
    short = pos(side="short", entry=60000, mark=59000, liq=80000)
    assert protective_stops(short, [StopOrder("BTCUSDT", "BUY", 61000.0, None)])


def test_position_without_stop_is_danger():
    a = check([pos()], [], equity=1000, day_pnl=0, cfg=CFG)
    assert "no_stop" in keys(a) and a[0].severity == "danger" and "lichidare" in a[0].text


def test_clean_position_raises_nothing():
    assert check([pos()], [StopOrder("BTCUSDT", "SELL", 59500.0, 0.01)], equity=1000, day_pnl=0, cfg=CFG) == []


def test_risk_leverage_liq_exposure_partial():
    p = pos(qty=0.1, leverage=20, liq=58000, mark=61000)                      # 6.1k notional on 1k equity
    a = check([p], [StopOrder("BTCUSDT", "SELL", 57000.0, 0.05)], equity=1000, day_pnl=0, cfg=CFG)
    assert {"risk", "leverage", "liq", "exposure", "partial_stop"} <= keys(a)


def test_daily_loss_says_take_a_break():
    a = check([], [], equity=960, day_pnl=-40, cfg=CFG)                        # -4% of 1000
    assert "daily_loss" in keys(a) and "pauză" in a[0].text


def test_dedup_repeats_and_resolves(tmp_path):
    d = Dedup(tmp_path / "g.json", repeat_minutes=60)
    a = check([pos()], [], 1000, 0, CFG)
    assert len(d.filter(a, NOW)[0]) == 1
    assert d.filter(a, NOW + timedelta(minutes=10))[0] == []                   # no spam
    assert len(d.filter(a, NOW + timedelta(minutes=61))[0]) == 1               # still unresolved: repeat
    due, resolved = Dedup(tmp_path / "g.json", 60).filter([], NOW + timedelta(minutes=70))   # survives restart
    assert resolved == ["no_stop:BTCUSDT:long"]
    assert resolved_text(resolved[0]) == "✅ BTCUSDT LONG: are stop acum."


class FakeEx:
    apiKey = secret = "x"

    def __init__(self, positions, algo, income):
        self._p, self._a, self._i = positions, algo, income

    def fetch_positions(self):
        return self._p

    def fapiPrivateGetOpenAlgoOrders(self):
        return self._a

    def fapiPrivateGetOpenOrders(self):
        return []

    def fapiPrivateV2GetAccount(self):
        return {"totalMarginBalance": "1000"}

    def fapiPrivateGetIncome(self, params):
        return [r for r in self._i if params["startTime"] <= r["time"] <= params["endTime"]]


class Tg:
    def __init__(self):
        self.sent = []

    def send(self, t):
        self.sent.append(t)


CCXT_POS = {"symbol": "BTC/USDT:USDT", "contracts": 0.01, "contractSize": 1, "side": "long", "entryPrice": 60000,
            "markPrice": 61000, "leverage": 3, "liquidationPrice": 41000, "unrealizedPnl": 10,
            "info": {"symbol": "BTCUSDT", "positionAmt": "0.01", "positionSide": "BOTH"}}


def test_ccxt_position_parsing():
    p = position_from_ccxt(CCXT_POS)
    assert p.symbol == "BTCUSDT" and p.side == "long" and p.qty == 0.01 and p.notional == 610
    assert position_from_ccxt({**CCXT_POS, "contracts": 0, "info": {"positionAmt": "0"}}) is None


def test_tick_end_to_end(tmp_path):
    reader = BinanceFuturesReader(ex=FakeEx([CCXT_POS], [], []))
    tg = Tg()
    tick(reader, tg, CFG, Dedup(tmp_path / "g.json", 60), NOW)
    assert any("FĂRĂ STOP" in m for m in tg.sent)


def inc(t_min, typ, amt, sym="BTCUSDT", tran=None):
    t = int((NOW + timedelta(minutes=t_min)).timestamp() * 1000)
    return {"time": t, "symbol": sym, "incomeType": typ, "income": str(amt), "tranId": tran or f"{typ}{t_min}{sym}"}


def test_journal_splits_deposits_from_trading():
    income = [inc(0, "TRANSFER", 1000, ""), inc(10, "REALIZED_PNL", 30), inc(10.5, "REALIZED_PNL", 20),
              inc(10, "COMMISSION", -2), inc(60, "REALIZED_PNL", -25, "ETHUSDT"), inc(60, "COMMISSION", -1, "ETHUSDT"),
              inc(120, "FUNDING_FEE", -0.5)]
    j = build_journal(income)
    assert len(j.exits) == 2                                                   # two fills 30s apart = one exit
    assert j.exits.loc[j.exits.symbol == "BTCUSDT", "pnl"].iloc[0] == 50
    assert j.net_trading == pytest.approx(50 - 2 - 25 - 1 - 0.5)
    assert j.net_transfers == 1000
    md = markdown(j, 90, balance=1021.5)
    assert "Transferuri nete" in md and "ETHUSDT" in md and "prea puține" in md


def test_verdict_uses_t_stat():
    assert "noroc" in verdict({"exits": 40, "t_stat": 1.0})
    assert "greu de explicat" in verdict({"exits": 40, "t_stat": 2.5})


def test_reader_income_pages_by_week():
    rows = [inc(m * 60 * 24, "COMMISSION", -1) for m in range(20)]              # one per day for 20 days
    r = BinanceFuturesReader(ex=FakeEx([], [], rows))
    got = r.income(rows[0]["time"], rows[-1]["time"])
    assert len(got) == 20
