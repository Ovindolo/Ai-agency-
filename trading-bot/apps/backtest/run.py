"""make backtest -> reports/A_rules_only.md and reports/B_rules_plus_jev.md"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from apps.backtest.data import download, load
from apps.backtest.engine import run_backtest

ROOT = Path(__file__).resolve().parents[2]


def recorded_jev(symbol: str) -> dict[str, dict]:
    """Recorded paper/live Jev answers keyed by snapshot ts. Written by the paper runner."""
    path = ROOT / "logs" / "decisions.jsonl"
    out: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            r = json.loads(line)
            if r.get("symbol") == symbol and r.get("jev_status") == "ok" and r.get("jev_answers"):
                out[r["snapshot_ts"]] = {"model": r.get("jev_model"), "answers": r["jev_answers"]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTC/USDT,ETH/USDT")
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--equity", type=float, default=500.0)
    a = ap.parse_args()
    (ROOT / "reports").mkdir(exist_ok=True)
    for sym in a.symbols.split(","):
        if a.download:
            print("downloading", sym, "->", download(sym, a.exchange))
        df = load(sym)
        A = run_backtest(df, sym, label=f"{sym} · A · rules only", start_equity=a.equity)
        rec = recorded_jev(sym)
        B = run_backtest(df, sym, label=f"{sym} · B · rules + recorded Jev", start_equity=a.equity,
                         use_jev=True, jev_records=rec)
        tag = sym.replace("/", "")
        (ROOT / "reports" / f"{tag}_A_rules_only.md").write_text(A.markdown())
        note = "" if rec else ("\n> **No recorded Jev answers yet.** B equals A until the paper runner has logged "
                               "real answers. That is by design: Jev is never simulated in a backtest.\n")
        (ROOT / "reports" / f"{tag}_B_rules_plus_jev.md").write_text(B.markdown() + note)
        print(f"{sym}: A {'PASS' if A.passed else 'FAIL'} ({A.n} trades, PF {A.profit_factor:.2f}, DD {A.max_dd:.1%}, "
              f"net {A.net:+.2f}, hold {A.hold_return:+.1%}) | B coverage {B.jev_coverage or 0:.0%}")


if __name__ == "__main__":
    main()
