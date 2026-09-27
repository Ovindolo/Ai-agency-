"""Review loop: every 10 closed trades (bigger review every 25) the bot measures itself and writes
context/Learnings.md. It SUGGESTS; it never changes strategy, thresholds or risk. The operator decides.

  python -m apps.review.learn [--base runs/replay-...]

Calibration: for every trade Jev judged, P(aligned_with_signal) is compared with whether the trade won.
Brier = mean((p - outcome)^2). It only means something next to the baseline: always answering the
historical win rate. Skill = 1 - Brier/baseline; <= 0 means Jev adds nothing over the base rate.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from apps.risk.engine import RiskLimits, realized_kelly

ROOT = Path(__file__).resolve().parents[2]
MIN_CALIBRATION = 20      # fewer judged trades than this: report, don't conclude


@dataclass
class Review:
    n: int = 0
    wins: int = 0
    pnl: float = 0.0
    r: list[float] = field(default_factory=list)
    by_reason: dict[str, list[float]] = field(default_factory=dict)
    by_fallback: dict[str, list[float]] = field(default_factory=dict)
    judged: list[tuple[float, int]] = field(default_factory=list)          # (P aligned, won)
    judged_by_model: dict[str, list[tuple[float, int]]] = field(default_factory=dict)   # Jev vs a local Kev, etc.
    setup_buckets: dict[str, list[float]] = field(default_factory=dict)    # setup_quality bucket -> R
    move_15m: list[tuple[float, int]] = field(default_factory=list)        # (P aligned, price up 15m later)

    @property
    def profit_factor(self) -> float:
        gw = sum(x for x in self.r if x > 0)
        gl = -sum(x for x in self.r if x <= 0)
        return gw / gl if gl else float("inf")

    @property
    def expectancy_r(self) -> float:
        return sum(self.r) / len(self.r) if self.r else 0.0


def brier(pairs: list[tuple[float, int]]) -> tuple[float, float, float] | None:
    """(brier, baseline brier, skill). None without data."""
    if not pairs:
        return None
    b = sum((p - o) ** 2 for p, o in pairs) / len(pairs)
    rate = sum(o for _, o in pairs) / len(pairs)
    base = sum((rate - o) ** 2 for _, o in pairs) / len(pairs)
    return b, base, (1 - b / base) if base > 0 else 0.0


def calibration_table(pairs: list[tuple[float, int]], bins: int = 5) -> list[tuple[str, int, float, float]]:
    rows = []
    for k in range(bins):
        lo, hi = k / bins, (k + 1) / bins
        sel = [(p, o) for p, o in pairs if lo <= p < hi or (k == bins - 1 and p == 1.0)]
        if sel:
            rows.append((f"{lo:.1f}–{hi:.1f}", len(sel), sum(p for p, _ in sel) / len(sel),
                         sum(o for _, o in sel) / len(sel)))
    return rows


def load(base: Path) -> Review:
    path = base / "logs" / "decisions.jsonl"
    recs = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    decisions = {r["id"]: r for r in recs if r["type"] == "decision"}
    outcomes = {r["decision_id"]: r["ret_15m"] for r in recs if r["type"] == "outcome"}
    rv = Review()
    for d in decisions.values():
        ans = d.get("jev_answers") or {}
        if "aligned_with_signal" in ans and d["id"] in outcomes:
            rv.move_15m.append((ans["aligned_with_signal"]["noul"], int(outcomes[d["id"]] > 0)))
    for x in (r for r in recs if r["type"] == "exit"):
        r_mult = x.get("r", 0.0)
        won = int(x["pnl"] > 0)
        rv.n, rv.wins, rv.pnl = rv.n + 1, rv.wins + won, rv.pnl + x["pnl"]
        rv.r.append(r_mult)
        reason = x["reason"] if x["reason"] in ("stop", "target") else x["reason"].split(" ")[0]
        rv.by_reason.setdefault(reason, []).append(r_mult)
        d = decisions.get(x.get("decision_id"), {})
        rv.by_fallback.setdefault(d.get("policy_fallback", "?"), []).append(r_mult)
        ans = d.get("jev_answers") or {}
        if "aligned_with_signal" in ans:
            rv.judged.append((ans["aligned_with_signal"]["noul"], won))
            rv.judged_by_model.setdefault(d.get("jev_model") or "?", []).append((ans["aligned_with_signal"]["noul"], won))
        if "setup_quality" in ans:
            s = ans["setup_quality"]["score"]
            rv.setup_buckets.setdefault("≥2.5" if s >= 2.5 else "2.0–2.5" if s >= 2.0 else "<2.0", []).append(r_mult)
    return rv


def suggestions(rv: Review, limits: RiskLimits) -> list[str]:
    out = []
    if rv.n < 10:
        out.append(f"Doar {rv.n} tranzacții: prea puține pentru orice concluzie. Nu schimba nimic.")
        return out
    k = realized_kelly(rv.r)
    if rv.n >= limits.kelly_min_trades and k is not None and k <= 0:
        out.append(f"Kelly din rezultatele reale e {k:+.2f} după {rv.n} tranzacții: niciun avantaj măsurat. "
                   "Botul deja intră cu jumătate de mărime. Propunere: rămâi pe paper; strategia intră în turneu din nou.")
    elif k is not None and k > 0 and rv.n < limits.kelly_min_trades:
        out.append(f"Kelly pe {rv.n} tranzacții e zgomot; devine relevant de la {limits.kelly_min_trades}.")
    elif k is not None and k > 0:
        out.append(f"Kelly din rezultate {k:+.2f} (sfert de Kelly {k / 4:.1%} risc/tranzacție). "
                   "Informativ doar: mărimea NU crește peste limitele fixe.")
    stops = rv.by_reason.get("stop", [])
    if len(stops) / rv.n > 0.6:
        out.append(f"{len(stops)}/{rv.n} ieșiri pe stop. Propunere de testat în backtest, nu live: filtrul de trend sau stopul.")
    tstop = rv.by_reason.get("time", [])
    if len(tstop) / rv.n > 0.25:
        out.append(f"{len(tstop)}/{rv.n} ieșiri pe timp (48h): targetul poate fi prea departe pentru volatilitatea actuală.")
    cal = brier(rv.judged)
    if cal and len(rv.judged) >= MIN_CALIBRATION:
        if cal[2] <= 0:
            out.append(f"Jev nu bate rata de bază (skill {cal[2]:+.2f} pe {len(rv.judged)} tranzacții). "
                       "Propunere: Jev doar pentru veto, nu pentru mărime.")
        else:
            out.append(f"Jev bate rata de bază (skill {cal[2]:+.2f}). Nicio schimbare automată; testează în replay.")
    elif rv.judged:
        out.append(f"Calibrare Jev: {len(rv.judged)}/{MIN_CALIBRATION} tranzacții judecate, încă nu concluzionăm.")
    if not out:
        out.append("Nimic ieșit din comun. Nu schimba nimic.")
    return out


def _r(xs: list[float]) -> str:
    return f"{len(xs)} · medie {sum(xs) / len(xs):+.2f}R" if xs else "—"


def render(rv: Review, limits: RiskLimits, now: datetime, big: bool) -> str:
    k = realized_kelly(rv.r)
    lines = [f"## Review {'mare (25)' if big else '(10)'} · {now:%Y-%m-%d %H:%M} UTC · {rv.n} tranzacții",
             "",
             f"- Câștigătoare: {rv.wins}/{rv.n} ({rv.wins / rv.n:.0%}) · profit factor {rv.profit_factor:.2f} · "
             f"medie {rv.expectancy_r:+.2f}R/tranzacție · P&L {rv.pnl:+.2f} USDT" if rv.n else "- Nicio tranzacție închisă.",
             f"- Kelly din rezultatele noastre: {k:+.2f}" if k is not None else "- Kelly: încă nu (lipsesc câștiguri sau pierderi)",
             "- Ieșiri: " + " · ".join(f"{k2} {_r(v)}" for k2, v in sorted(rv.by_reason.items())),
             "- După sursa deciziei: " + " · ".join(f"{k2} {_r(v)}" for k2, v in sorted(rv.by_fallback.items()))]
    cal = brier(rv.judged)
    if cal:
        lines += ["", f"**Calibrare Jev** (aligned_with_signal vs tranzacție câștigată, {len(rv.judged)} tranzacții): "
                      f"Brier {cal[0]:.3f} · bază {cal[1]:.3f} · skill {cal[2]:+.2f}", "",
                  "| P(aligned) | tranzacții | P medie | câștigate |", "|---|---|---|---|"]
        lines += [f"| {b} | {n} | {p:.2f} | {o:.0%} |" for b, n, p, o in calibration_table(rv.judged)]
    if len(rv.judged_by_model) > 1:
        lines.append("\nPe model: " + " · ".join(
            f"{name} skill {b[2]:+.2f} ({len(pairs)} tranzacții)" for name, pairs in sorted(rv.judged_by_model.items())
            if (b := brier(pairs))))
    m = brier(rv.move_15m)
    if m:
        lines.append(f"\nAceeași întrebare vs prețul 15 min mai târziu ({len(rv.move_15m)} decizii): skill {m[2]:+.2f}")
    if big and rv.setup_buckets:
        lines.append("\nsetup_quality → rezultat: " + " · ".join(f"{b} {_r(v)}" for b, v in sorted(rv.setup_buckets.items())))
    lines += ["", "**Propuneri** (nimic nu se aplică automat; tu aprobi, se testează întâi în replay):"]
    lines += [f"- {s}" for s in suggestions(rv, limits)]
    return "\n".join(lines) + "\n"


def write(base: Path, now: datetime | None = None, limits: RiskLimits | None = None) -> tuple[Review, str]:
    now = now or datetime.now(timezone.utc)
    limits = limits or RiskLimits()
    rv = load(base)
    text = render(rv, limits, now, big=rv.n > 0 and rv.n % 25 == 0)
    path = base / "context" / "Learnings.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    head = "" if path.exists() else ("# Learnings\n\nScris de bot la fiecare 10 tranzacții (mare la 25). "
                                     "Doar observații și propuneri; strategia se schimbă numai cu aprobarea ta.\n\n")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(head + text + "\n")
    return rv, text


def telegram_summary(rv: Review) -> str:
    k = realized_kelly(rv.r)
    first = suggestions(rv, RiskLimits())[0]
    return (f"📊 Review la {rv.n} tranzacții: {rv.wins} câștigate · PF {rv.profit_factor:.2f} · "
            f"{rv.expectancy_r:+.2f}R medie · P&L {rv.pnl:+.2f} USDT"
            + (f" · Kelly {k:+.2f}" if k is not None else "") + f"\n{first}\nDetalii: /learnings")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(ROOT))
    a = ap.parse_args()
    _, text = write(Path(a.base))
    print(text)


if __name__ == "__main__":
    main()
