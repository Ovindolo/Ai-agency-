"""Paper trading entry point.

  python -m apps.trader.paper                     # live market data (ccxt public), virtual money, loops every 15m
  python -m apps.trader.paper --once              # one tick and exit (cron-friendly)
  python -m apps.trader.paper --replay data/BTC_USDT_15m.csv --days 30    # replay history bar by bar
  python -m apps.trader.paper --replay simulated --days 30                # replay a SIMULATED market (demo)

Replays write to runs/replay-*/ and never touch the real paper state in data/.
No live order path exists here. Jev is used only if TYPESAFE_API_KEY is set; otherwise deterministic fallback.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from apps.backtest.data import load
from apps.jev.client import JevClient
from apps.trader.notify import Notifier
from apps.trader.runner import ROOT, Runner
from apps.trader.sources import BARS, CcxtSource, ReplaySource

WARMUP = 400      # bars of history before the first replayed decision (indicators need ~55h of 1h bars)


def simulated_market(days: int, seed: int, start: float = 60_000.0) -> pd.DataFrame:
    """SIMULATED 15m candles with regime switches (trend up / chop / trend down). Not market data."""
    rng = np.random.default_rng(seed)
    n = WARMUP + days * 96
    drift = np.empty(n)
    i = 0
    while i < n:                                   # regimes of 1-4 days
        length = int(rng.integers(96, 384))
        drift[i:i + length] = rng.choice([0.0001, 0.0, 0.0, -0.0001])   # ~±1%/day in trend regimes
        i += length
    vol = 0.0025 * np.exp(0.3 * rng.standard_normal(n)).clip(0.5, 2.0)
    close = start * np.exp(np.cumsum(drift + vol * rng.standard_normal(n)))
    open_ = np.concatenate([[start], close[:-1]])
    wick = np.abs(vol * rng.standard_normal(n)) * close
    volume = 1000 * np.exp(0.4 * rng.standard_normal(n))
    idx = pd.date_range(pd.Timestamp.now(tz="UTC").floor("D") - pd.Timedelta(minutes=15 * n), periods=n, freq="15min")
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + wick / 2,
                         "low": np.minimum(open_, close) - wick / 2, "close": close, "volume": volume,
                         "taker_buy_volume": volume * 0.5}, index=idx)


def replay(args) -> Path:
    symbols = args.symbols.split(",")
    if args.replay == "simulated":
        frames = {s: simulated_market(args.days, args.seed + k, start=[60_000.0, 3_000.0, 150.0][k % 3])
                  for k, s in enumerate(symbols)}
    else:
        df = load(symbols[0]) if args.replay == "data" else pd.read_csv(args.replay, index_col=0, parse_dates=True)
        frames = {symbols[0]: df.iloc[-(WARMUP + args.days * 96):]}
        symbols = symbols[:1]
    base = ROOT / "runs" / f"replay-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{args.replay if args.replay == 'simulated' else 'csv'}{args.seed}"
    src = ReplaySource(frames)
    times = src.times(symbols[0], WARMUP)
    jev = JevClient(log_path=base / "logs" / "jev.jsonl")
    tg = Notifier(token="", chat_id="", echo=not args.quiet)          # replays never message Telegram
    label = "SIMULAT" if args.replay == "simulated" else "ISTORIC"
    print(f"== replay {label}: {', '.join(symbols)} · {len(times)} lumânări 15m · Jev {'ON' if jev.enabled else 'OFF (fallback determinist)'}")
    bot = Runner(src, symbols, jev=jev, notifier=tg, base=base, starting_equity=args.equity, now=times[0])
    for now in times:
        bot.step(now)
    summarize(bot, base)
    return base


def summarize(bot: Runner, base: Path) -> None:
    decisions = [json.loads(line) for line in (base / "logs" / "decisions.jsonl").read_text().splitlines()] \
        if (base / "logs" / "decisions.jsonl").exists() else []
    exits = [d for d in decisions if d["type"] == "exit"]
    signals = [d for d in decisions if d["type"] == "decision"]
    wins = [e for e in exits if e["pnl"] > 0]
    gross_w, gross_l = sum(e["pnl"] for e in wins), -sum(e["pnl"] for e in exits if e["pnl"] <= 0)
    a = bot.acct
    print("\n== rezumat")
    print(f"semnale strategie: {len(signals)} · intrări: {sum(d.get('action') == 'enter' for d in signals)}"
          f" · respinse de policy: {sum(d['policy'] != 'enter' for d in signals)}"
          f" · respinse de risk: {sum(d.get('risk') not in (None, 'allow') for d in signals)}")
    print(f"tranzacții închise: {len(exits)} · câștigătoare: {len(wins)}"
          f" · profit factor: {gross_w / gross_l if gross_l else float('inf'):.2f}")
    print(f"capital: {a.starting_equity:.2f} → {a.equity:.2f} USDT ({a.equity / a.starting_equity - 1:+.2%})"
          f" · max drawdown vs vârf: {a.drawdown_pct:.2%} · poziții deschise: {len(bot.positions)}"
          f" · kill: {a.kill_reason or 'nu'}")
    print(f"fișiere: {base.relative_to(ROOT)}/  (data/state.json, logs/decisions.jsonl, context/Trade_Ledger.md)")


def next_close(now: datetime) -> datetime:
    """10 seconds after the next 15m candle closes."""
    q = now.replace(second=0, microsecond=0, minute=now.minute - now.minute % 15) + timedelta(minutes=15)
    return q + timedelta(seconds=10)


def live(args) -> None:
    symbols = args.symbols.split(",")
    src = CcxtSource(args.exchange)
    bot = Runner(src, symbols, jev=JevClient(), notifier=Notifier(), starting_equity=args.equity)
    while True:
        now = datetime.now(timezone.utc)
        try:
            bot.step(now)
        except Exception as exc:              # a data hiccup must not kill the loop; the tick is skipped, not guessed
            print(f"[paper] tick skipped at {now:%H:%M:%S}: {type(exc).__name__}: {exc}")
        if args.once:
            return
        time.sleep(max(1.0, (next_close(datetime.now(timezone.utc)) - datetime.now(timezone.utc)).total_seconds()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTC/USDT,ETH/USDT")
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--equity", type=float, default=500.0)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--replay", help="'simulated', 'data' (downloaded CSV of the first symbol) or a CSV path")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    assert BARS >= WARMUP
    replay(a) if a.replay else live(a)


if __name__ == "__main__":
    main()
