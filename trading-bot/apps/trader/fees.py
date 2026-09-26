"""make fees -> data/fees.json: the account's REAL maker/taker fees per symbol (promotions included).

Needs a read-only API key in the environment (EXCHANGE_API_KEY / EXCHANGE_API_SECRET). Nothing secret is
printed or written; only the fee numbers. The runner applies them on start; without the file, config/risk.yaml.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from apps.risk.engine import RiskLimits

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "data" / "fees.json"


def discover(exchange: str, symbols: list[str]) -> dict[str, dict[str, float]]:
    import ccxt
    key, secret = os.getenv("EXCHANGE_API_KEY", ""), os.getenv("EXCHANGE_API_SECRET", "")
    if not (key and secret):
        raise SystemExit("EXCHANGE_API_KEY / EXCHANGE_API_SECRET lipsesc din .env (cheie read-only ajunge).")
    ex = getattr(ccxt, exchange)({"apiKey": key, "secret": secret, "enableRateLimit": True})
    fees = ex.fetch_trading_fees()
    return {s: {"maker": float(fees[s]["maker"]), "taker": float(fees[s]["taker"])} for s in symbols if s in fees}


def apply(limits: RiskLimits, symbols: list[str], path: Path = PATH) -> tuple[RiskLimits, str]:
    """Use the WORST fee across the traded symbols (one limits object serves all of them)."""
    try:
        fees = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return limits, "taxe din config/risk.yaml"
    got = [fees[s] for s in symbols if s in fees]
    if not got:
        return limits, "taxe din config/risk.yaml"
    new = replace(limits, maker_fee_pct=max(f["maker"] for f in got), taker_fee_pct=max(f["taker"] for f in got))
    return new, f"taxe reale din cont: maker {new.maker_fee_pct:.3%} · taker {new.taker_fee_pct:.3%}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--symbols", default="BTC/USDT,ETH/USDT,BTC/FDUSD,ETH/FDUSD,BTC/USDC,ETH/USDC")
    a = ap.parse_args()
    fees = discover(a.exchange, a.symbols.split(","))
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(fees, indent=1))
    for s, f in fees.items():
        print(f"{s:12s} maker {f['maker']:.4%}  taker {f['taker']:.4%}")
    print("\nPerechile cu maker 0% taie cel mai mare cost al botului. Atenție: un stablecoin (FDUSD, USDC) "
          "poate pierde paritatea; ține în el doar cât tranzacționezi.")


if __name__ == "__main__":
    main()
