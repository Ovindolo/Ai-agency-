"""Turn the bot's own log into training rows for a Jev-like model (vinnylarouge/jevlike JSONL format:
{"context", "options", "label"}), so a local model can one day be fitted on OUR market states.

Two label sets, both from things that actually happened after the decision:
  trades   the entry won or lost (few rows: one per closed trade)
  moves    price was higher 15 minutes later (one row per logged decision; noisier, far more rows)

A few hundred trades is thin data for training; this exists so nothing logged today is wasted.

  python -m apps.review.export_training [--base runs/replay-...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRADE_OPTIONS = ["the long entry lost money", "the long entry made money"]
MOVE_OPTIONS = ["price was lower 15 minutes later", "price was higher 15 minutes later"]


def rows(base: Path) -> tuple[list[dict], list[dict]]:
    path = base / "logs" / "decisions.jsonl"
    recs = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    words = {r["id"]: r["words"] for r in recs if r["type"] == "decision" and r.get("words")}
    trades = [{"context": words[x["decision_id"]], "options": TRADE_OPTIONS, "label": int(x["pnl"] > 0)}
              for x in recs if x["type"] == "exit" and x.get("decision_id") in words]
    moves = [{"context": words[o["decision_id"]], "options": MOVE_OPTIONS, "label": int(o["ret_15m"] > 0)}
             for o in recs if o["type"] == "outcome" and o["decision_id"] in words and o["ret_15m"] != 0]
    return trades, moves


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(ROOT))
    a = ap.parse_args()
    base = Path(a.base)
    trades, moves = rows(base)
    out = base / "data"
    out.mkdir(exist_ok=True)
    for name, data in (("train_trades.jsonl", trades), ("train_moves.jsonl", moves)):
        (out / name).write_text("".join(json.dumps(r) + "\n" for r in data))
        print(f"{name}: {len(data)} rânduri")


if __name__ == "__main__":
    main()
