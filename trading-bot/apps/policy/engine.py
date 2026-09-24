"""Policy: compose an action from strategy signal + Jev answers + thresholds.

Invariants, enforced here and tested:
  * Jev can veto or shrink a trade. It can never create one or enlarge one.
  * No signal -> no trade, whatever Jev says.
  * Jev late -> HOLD. Never trade on stale judgment.
  * Jev down/disabled -> deterministic rules only, risk_mult <= 1.
  * The risk engine runs AFTER this and can still veto everything.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.common.config import PolicyThresholds
from apps.features.snapshot import Snapshot
from apps.jev.client import JevResult


@dataclass(frozen=True)
class EntryDecision:
    action: str              # enter | skip | hold
    risk_mult: float
    reasons: tuple[str, ...]
    fallback: str            # normal | low_confidence | jev_late_hold | jev_down | jev_disabled | no_signal
    confidence: float | None = None


@dataclass(frozen=True)
class ExitAdvice:
    action: str              # hold | tighten | reduce | flatten
    reason: str


def compose_entry(snap: Snapshot, jev: JevResult, t: PolicyThresholds, *, strategy_is_trend: bool = True) -> EntryDecision:
    if snap.strategy_side != "long":
        return EntryDecision("skip", 0.0, ("no strategy signal",), "no_signal")

    if jev.status == "timeout":
        return EntryDecision("hold", 0.0, (f"jev late ({jev.latency_ms}ms) -> hold",), "jev_late_hold")
    if jev.status in ("down", "disabled"):
        mult = min(t.jev_down_risk_mult, 1.0)
        return EntryDecision("enter", mult, (f"jev {jev.status}: deterministic rules only",),
                             "jev_down" if jev.status == "down" else "jev_disabled")

    missing = [n for n in ("regime", "setup_quality", "aligned_with_signal", "toxic_or_unstable") if getattr(jev, n) is None]
    if missing:
        return EntryDecision("hold", 0.0, (f"jev answer missing: {', '.join(missing)} -> hold",), "jev_late_hold")

    reasons: list[str] = []
    if jev.toxic_or_unstable.noul > t.toxic_max_noul:
        reasons.append(f"toxic p={jev.toxic_or_unstable.noul:.2f} > {t.toxic_max_noul}")
    if jev.setup_quality.score < t.setup_min_score:
        reasons.append(f"setup {jev.setup_quality.score:.2f} < {t.setup_min_score}")
    if jev.aligned_with_signal.noul < t.aligned_min_noul:
        reasons.append(f"aligned p={jev.aligned_with_signal.noul:.2f} < {t.aligned_min_noul}")
    if strategy_is_trend and jev.regime.choice in ("chop", "high_vol", "trending_down"):
        reasons.append(f"regime {jev.regime.choice} vs trend strategy")

    # Confidence: only choice and score answers carry one. Noul answers are gated by their own thresholds.
    confidence = min(jev.regime.confidence, jev.setup_quality.confidence)
    if reasons:
        return EntryDecision("skip", 0.0, tuple(reasons), "normal", confidence)

    if confidence < t.low_confidence:
        return EntryDecision("enter", min(t.low_confidence_risk_mult, 1.0),
                             (f"confidence {confidence:.2f} < {t.low_confidence} -> reduced size",), "low_confidence", confidence)
    return EntryDecision("enter", 1.0, ("all gates passed",), "normal", confidence)


def compose_exit(jev: JevResult, t: PolicyThresholds) -> ExitAdvice:
    """Advice for an open position. The risk engine's stops/targets/time-stop apply regardless."""
    if not jev.ok or jev.exit_urgency is None:
        return ExitAdvice("hold", f"no jev exit advice ({jev.status}); hard stops still active")
    u = jev.exit_urgency.score
    if u >= t.exit_flatten_at:
        return ExitAdvice("flatten", f"exit_urgency {u:.2f}")
    if u >= t.exit_reduce_at:
        return ExitAdvice("reduce", f"exit_urgency {u:.2f}")
    if u >= t.exit_tighten_at:
        return ExitAdvice("tighten", f"exit_urgency {u:.2f}")
    return ExitAdvice("hold", f"exit_urgency {u:.2f}")
