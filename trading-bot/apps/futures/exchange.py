"""Read-only access to Binance USD-M futures. This module has no code path that sends an order.

Key: FUTURES_API_KEY / FUTURES_API_SECRET (or EXCHANGE_API_KEY / EXCHANGE_API_SECRET) from .env.
Create it with ONLY "Enable Reading" ticked. On start the key's permissions are checked; a key that can
withdraw is refused outright, a key that can trade is refused unless explicitly allowed.
"""
from __future__ import annotations

import os
import time

from apps.futures.models import FPosition, StopOrder, position_from_ccxt, stop_from_raw


class KeyTooPowerful(RuntimeError):
    pass


class BinanceFuturesReader:
    def __init__(self, allow_trading_key: bool = False, ex=None):
        if ex is None:
            import ccxt
            key = os.getenv("FUTURES_API_KEY") or os.getenv("EXCHANGE_API_KEY", "")
            secret = os.getenv("FUTURES_API_SECRET") or os.getenv("EXCHANGE_API_SECRET", "")
            if not (key and secret):
                raise SystemExit("Lipsește FUTURES_API_KEY / FUTURES_API_SECRET în .env (cheie doar cu citire).")
            ex = ccxt.binanceusdm({"apiKey": key, "secret": secret, "enableRateLimit": True})
        self.ex = ex
        self.allow_trading_key = allow_trading_key

    def check_key(self) -> dict:
        """GET /sapi/v1/account/apiRestrictions. Raises if the key can withdraw (always) or trade (by default)."""
        try:
            import ccxt
            r = ccxt.binance({"apiKey": self.ex.apiKey, "secret": self.ex.secret}).sapiGetAccountApiRestrictions()
        except Exception as exc:  # noqa: BLE001 - reported, never printed with the key
            return {"checked": False, "error": type(exc).__name__}
        if str(r.get("enableWithdrawals")).lower() == "true":
            raise KeyTooPowerful("Cheia poate RETRAGE bani. Șterge-o din Binance și fă una doar cu citire.")
        can_trade = any(str(r.get(k)).lower() == "true" for k in ("enableFutures", "enableSpotAndMarginTrading", "enableMargin"))
        if can_trade and not self.allow_trading_key:
            raise KeyTooPowerful("Cheia poate TRANZACȚIONA. Gardianul are nevoie doar de citire: fă o cheie separată.")
        return {"checked": True, "can_trade": can_trade}

    def positions(self) -> list[FPosition]:
        return [p for p in (position_from_ccxt(x) for x in self.ex.fetch_positions()) if p]

    def stops(self) -> list[StopOrder]:
        raw: list[dict] = []
        try:
            raw += self.ex.fapiPrivateGetOpenAlgoOrders()           # conditional orders since 2025-12-09
        except Exception:  # noqa: BLE001 - older accounts / ccxt versions: fall back to legacy only
            pass
        try:
            raw += self.ex.fapiPrivateGetOpenOrders()
        except Exception:  # noqa: BLE001
            pass
        return [s for s in (stop_from_raw(o) for o in raw) if s]

    def equity(self) -> float:
        acct = self.ex.fapiPrivateV2GetAccount() if hasattr(self.ex, "fapiPrivateV2GetAccount") else self.ex.fapiPrivateGetAccount()
        return float(acct["totalMarginBalance"])

    def income(self, since_ms: int, until_ms: int | None = None) -> list[dict]:
        """/fapi/v1/income in 7-day windows, 1000 per page. Types: REALIZED_PNL, COMMISSION, FUNDING_FEE, TRANSFER..."""
        until_ms = until_ms or int(time.time() * 1000)
        out, start = [], since_ms
        week = 7 * 86_400_000
        while start < until_ms:
            end = min(start + week, until_ms)
            cursor = start
            while True:
                batch = self.ex.fapiPrivateGetIncome({"startTime": cursor, "endTime": end, "limit": 1000})
                out += batch
                if len(batch) < 1000:
                    break
                cursor = int(batch[-1]["time"]) + 1
            start = end + 1
        seen, uniq = set(), []
        for r in out:
            k = (r.get("tranId"), r.get("incomeType"))
            if k not in seen:
                seen.add(k)
                uniq.append(r)
        return sorted(uniq, key=lambda r: int(r["time"]))
