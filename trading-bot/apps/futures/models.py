"""Normalized futures state. Everything the guard and journal need, independent of ccxt's dict shapes."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FPosition:
    symbol: str                 # exchange id, e.g. BTCUSDT
    side: str                   # long | short
    qty: float                  # base units, positive
    entry: float
    mark: float
    leverage: float | None
    liq: float | None
    unrealized: float
    position_side: str = "BOTH"  # BOTH (one-way) | LONG | SHORT (hedge mode)

    @property
    def notional(self) -> float:
        return self.qty * self.mark


@dataclass(frozen=True)
class StopOrder:
    symbol: str
    side: str                   # BUY | SELL (the closing side)
    trigger: float
    qty: float | None           # None = closes the whole position
    position_side: str = "BOTH"


def _f(x) -> float | None:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def position_from_ccxt(p: dict) -> FPosition | None:
    info = p.get("info") or {}
    qty = abs(_f(p.get("contracts")) or _f(info.get("positionAmt")) or 0.0) * (_f(p.get("contractSize")) or 1.0)
    if qty == 0:
        return None
    amt = _f(info.get("positionAmt"))
    side = p.get("side") or ("long" if (amt or 0) > 0 else "short")
    return FPosition(symbol=info.get("symbol") or p["symbol"].split(":")[0].replace("/", ""), side=side, qty=qty,
                     entry=_f(p.get("entryPrice")) or _f(info.get("entryPrice")) or 0.0,
                     mark=_f(p.get("markPrice")) or _f(info.get("markPrice")) or 0.0,
                     leverage=_f(p.get("leverage")) or _f(info.get("leverage")),
                     liq=_f(p.get("liquidationPrice")) or _f(info.get("liquidationPrice")) or None,
                     unrealized=_f(p.get("unrealizedPnl")) or _f(info.get("unRealizedProfit")) or 0.0,
                     position_side=(info.get("positionSide") or "BOTH").upper())


def stop_from_raw(o: dict) -> StopOrder | None:
    """Binance raw order dict: legacy /fapi/v1/openOrders (stopPrice) or, since 2025-12-09, the Algo
    service /fapi/v1/openAlgoOrders (triggerPrice). Only closing orders that trigger count."""
    trigger = _f(o.get("triggerPrice")) or _f(o.get("stopPrice"))
    if not trigger:
        return None
    reduce = str(o.get("reduceOnly")).lower() == "true" or str(o.get("closePosition")).lower() == "true" \
        or (o.get("positionSide") or "BOTH").upper() in ("LONG", "SHORT")
    if not reduce:
        return None
    close_all = str(o.get("closePosition")).lower() == "true"
    qty = None if close_all else (_f(o.get("quantity")) or _f(o.get("origQty")))
    return StopOrder(o["symbol"], str(o.get("side", "")).upper(), trigger, qty, (o.get("positionSide") or "BOTH").upper())


def protective_stops(pos: FPosition, orders: list[StopOrder]) -> list[StopOrder]:
    """Orders that close this position at a worse price than now: a stop, not a take-profit."""
    closing = "SELL" if pos.side == "long" else "BUY"
    out = []
    for o in orders:
        if o.symbol != pos.symbol or o.side != closing or o.position_side not in ("BOTH", pos.position_side):
            continue
        if (pos.side == "long" and o.trigger < pos.mark) or (pos.side == "short" and o.trigger > pos.mark):
            out.append(o)
    return out
