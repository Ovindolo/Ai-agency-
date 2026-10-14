"""Paired replay: ask another decision model the exact states the bot logged, before paying for it.

DXRG (arXiv 2609.05663) replayed 416 saved production scenarios on three frontier models: decision quality
was statistically the same, but how often a model changed its answer on IDENTICAL input differed sharply.
This does the same on our own log:

  agreement   would model B have taken the same entry decision (enter / skip / hold) as the recorded one?
  calibration Brier skill of P(aligned_with_signal) against what happened (trade won / price up 15m later)
  stability   the same state asked `repeats` times: how often the decision flips
  cost        input tokens and latency per decision

  python -m apps.review.replay_models --base-url http://127.0.0.1:8009 --model kev-4b
  python -m apps.review.replay_models --model jev-latest                  # the paid API (TYPESAFE_API_KEY)

Only states already logged are sent (the ~14 words the bot showed the model); nothing is traded.
"""
from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from apps.backtest.engine import _jev_from_record
from apps.common.config import PolicyThresholds
from apps.jev.client import JevClient
from apps.policy.engine import compose_entry
from apps.review.learn import brier

ROOT = Path(__file__).resolve().parents[2]
LONG = SimpleNamespace(strategy_side="long")       # every logged decision had a long signal


@dataclass
class Case:
    id: str
    words: str
    recorded: dict | None        # {"model", "answers"} or None if Jev was off
    won: int | None              # trade result, if the decision became a trade
    up_15m: int | None           # price higher 15 minutes later


@dataclass
class ModelScore:
    model: str
    asked: int = 0
    ok: int = 0
    agree: int = 0
    comparable: int = 0
    tokens: int = 0
    latency: list[float] = field(default_factory=list)
    vs_trade: list[tuple[float, int]] = field(default_factory=list)
    vs_move: list[tuple[float, int]] = field(default_factory=list)
    flips: int = 0
    repeated: int = 0


def load_cases(base: Path) -> list[Case]:
    path = base / "logs" / "decisions.jsonl"
    recs = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    won = {r["decision_id"]: int(r["pnl"] > 0) for r in recs if r["type"] == "exit" and r.get("decision_id")}
    up = {r["decision_id"]: int(r["ret_15m"] > 0) for r in recs if r["type"] == "outcome" and r.get("ret_15m")}
    out = []
    for r in recs:
        if r["type"] == "decision" and r.get("words"):
            rec = {"model": r.get("jev_model"), "answers": r["jev_answers"]} if r.get("jev_answers") else None
            out.append(Case(r["id"], r["words"], rec, won.get(r["id"]), up.get(r["id"])))
    return out


def decision(jev, t: PolicyThresholds) -> str:
    return compose_entry(LONG, jev, t).action


def replay(cases: list[Case], client: JevClient, repeats: int = 3, stability_sample: int = 50,
           t: PolicyThresholds | None = None) -> ModelScore:
    t = t or PolicyThresholds()
    sc = ModelScore(client.model)
    for i, c in enumerate(cases):
        res = client.ask(c.words, candidate_signal=True, in_position=False)
        sc.asked += 1
        if not res.ok:
            continue
        sc.ok += 1
        sc.tokens += res.input_tokens or 0
        sc.latency.append(res.latency_ms or 0.0)
        mine = decision(res, t)
        if c.recorded:
            sc.comparable += 1
            sc.agree += mine == decision(_jev_from_record(c.recorded), t)
        if res.aligned_with_signal is not None:
            p = res.aligned_with_signal.noul
            if c.won is not None:
                sc.vs_trade.append((p, c.won))
            if c.up_15m is not None:
                sc.vs_move.append((p, c.up_15m))
        if i < stability_sample and repeats > 1:
            again = [client.ask(c.words, candidate_signal=True, in_position=False) for _ in range(repeats - 1)]
            seen = {mine} | {decision(a, t) for a in again if a.ok}
            sc.repeated += 1
            sc.flips += len(seen) > 1
    return sc


def markdown(scores: list[ModelScore], n_cases: int, price_per_mtok: float | None = None) -> str:
    L = [f"# Replay pe modele · {n_cases} decizii logate", "",
         "| Model | Răspunsuri ok | Acord cu decizia logată | Skill vs tranzacție | Skill vs preț 15m | "
         "Schimbă decizia la întrebare identică | Latență mediană | Tokeni / decizie | Cost / 1000 decizii |",
         "|---|---|---|---|---|---|---|---|---|"]
    for s in scores:
        bt, bm = brier(s.vs_trade), brier(s.vs_move)
        tok = s.tokens / s.ok if s.ok else 0
        cost = f"{tok * 1000 * price_per_mtok / 1e6:.3f}$" if price_per_mtok is not None else "—"
        L.append(f"| {s.model} | {s.ok}/{s.asked} | "
                 f"{f'{s.agree / s.comparable:.0%} ({s.comparable})' if s.comparable else '—'} | "
                 f"{f'{bt[2]:+.2f} ({len(s.vs_trade)})' if bt else '—'} | {f'{bm[2]:+.2f} ({len(s.vs_move)})' if bm else '—'} | "
                 f"{f'{s.flips / s.repeated:.0%} din {s.repeated}' if s.repeated else '—'} | "
                 f"{statistics.median(s.latency):.0f} ms | {tok:.0f} | {cost} |" if s.latency else
                 f"| {s.model} | 0/{s.asked} | — | — | — | — | — | — | — |")
    L += ["", "Skill = 1 − Brier/Brier de bază (a ghici mereu rata medie); ≤ 0 înseamnă că modelul nu ajută.",
          "Sub ~100 de cazuri judecate, diferențele dintre modele sunt de obicei zgomot.",
          "Un model care își schimbă des decizia pe același input e mai greu de folosit, chiar la aceeași acuratețe medie."]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(ROOT))
    ap.add_argument("--model", default="jev-latest")
    ap.add_argument("--base-url", default=None, help="local Jev-compatible server, e.g. Kev")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--sample", type=int, default=50, help="states asked repeatedly for the stability check")
    ap.add_argument("--price-per-mtok", type=float, default=None, help="USD per million input tokens, for the cost column")
    a = ap.parse_args()
    cases = load_cases(Path(a.base))
    client = JevClient(model=a.model, base_url=a.base_url, log_path=None)
    if not client.enabled:
        raise SystemExit("Niciun model disponibil: setează TYPESAFE_API_KEY sau --base-url.")
    md = markdown([replay(cases, client, a.repeats, a.sample)], len(cases), a.price_per_mtok)
    out = Path(a.base) / "reports" / "MODEL_REPLAY.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
