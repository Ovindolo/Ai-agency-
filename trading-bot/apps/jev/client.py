"""Jev (TypeSafe System One) client with a hard deadline and a fallback ladder.

Status is always one of:
  ok        answers arrived before the deadline
  timeout   answers were late or the call timed out  -> policy HOLDs
  down      API error / network / auth               -> deterministic fallback
  disabled  no key, JEV_ENABLED=false, or SDK missing -> deterministic fallback

Nothing here raises into the trading loop.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from apps.jev.battery import questions as build_questions

LOG_PATH = Path(os.getenv("JEV_LOG", Path(__file__).resolve().parents[2] / "logs" / "jev.jsonl"))


@dataclass(frozen=True)
class ChoiceA:
    choice: str
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class ScoreA:
    score: float
    confidence: float


@dataclass(frozen=True)
class NoulA:
    noul: float


@dataclass(frozen=True)
class JevResult:
    status: str
    model: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    regime: ChoiceA | None = None
    setup_quality: ScoreA | None = None
    aligned_with_signal: NoulA | None = None
    toxic_or_unstable: NoulA | None = None
    exit_urgency: ScoreA | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def as_log(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d


class Backend(Protocol):
    def system_one(self, state: Any, questions: dict, *, model: str, timeout: float) -> Any: ...


def parse_answers(answers: dict[str, Any]) -> dict[str, Any]:
    """Turn SDK answer objects (or plain dicts) into our frozen types. Unknown names are ignored."""
    def g(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)

    out: dict[str, Any] = {}
    for name, a in answers.items():
        kind = g(a, "type")
        if kind == "choice":
            out[name] = ChoiceA(str(g(a, "choice")), float(g(a, "confidence")), dict(g(a, "probabilities") or {}))
        elif kind == "score":
            out[name] = ScoreA(float(g(a, "score")), float(g(a, "confidence")))
        elif kind == "noul":
            out[name] = NoulA(float(g(a, "noul")))
    return out


class JevClient:
    def __init__(self, *, api_key: str | None = None, model: str | None = None, timeout_ms: int | None = None,
                 enabled: bool | None = None, backend: Backend | None = None, log_path: Path | None = LOG_PATH):
        self.api_key = api_key if api_key is not None else os.getenv("TYPESAFE_API_KEY", "")
        self.model = model or os.getenv("JEV_MODEL_ID", "jev-latest")
        self.timeout_s = (timeout_ms or int(os.getenv("JEV_TIMEOUT_MS", "800"))) / 1000
        env_enabled = os.getenv("JEV_ENABLED", "true").lower() == "true"
        self.enabled = (enabled if enabled is not None else env_enabled) and (bool(self.api_key) or backend is not None)
        self.log_path = log_path
        self._backend = backend
        self.last: JevResult | None = None

    def _get_backend(self) -> Backend | None:
        if self._backend is not None:
            return self._backend
        try:
            from typesafe_sdk import TypeSafeClient   # optional dependency
        except ImportError:
            return None
        self._backend = TypeSafeClient(api_key=self.api_key, model=self.model, timeout=self.timeout_s)
        return self._backend

    def ask(self, state_text: str, *, candidate_signal: bool, in_position: bool) -> JevResult:
        qs = build_questions(candidate_signal, in_position)
        if not qs:
            return self._record(JevResult(status="disabled", error="no questions for this state"), state_text)
        if not self.enabled:
            return self._record(JevResult(status="disabled", error="JEV_ENABLED=false or no TYPESAFE_API_KEY"), state_text)
        backend = self._get_backend()
        if backend is None:
            return self._record(JevResult(status="disabled", error="typesafe-sdk not installed"), state_text)

        t0 = time.perf_counter()
        try:
            resp = backend.system_one(state_text, qs, model=self.model, timeout=self.timeout_s)
        except Exception as exc:  # never let the model take the loop down
            latency = (time.perf_counter() - t0) * 1000
            status = "timeout" if "timeout" in type(exc).__name__.lower() else "down"
            return self._record(JevResult(status=status, model=self.model, latency_ms=round(latency, 1),
                                          error=f"{type(exc).__name__}: {exc}"[:300]), state_text)

        latency = (time.perf_counter() - t0) * 1000
        if latency > self.timeout_s * 1000:
            # answered, but too late for this decision: never trade on stale judgment
            return self._record(JevResult(status="timeout", model=self.model, latency_ms=round(latency, 1),
                                          error="late answer discarded"), state_text)

        answers = resp.get("answers", {}) if isinstance(resp, dict) else getattr(resp, "answers", {})
        usage = resp.get("usage") if isinstance(resp, dict) else getattr(resp, "usage", None)
        tokens = (usage.get("input_tokens") if isinstance(usage, dict) else getattr(usage, "input_tokens", None)) if usage else None
        model = (resp.get("model") if isinstance(resp, dict) else getattr(resp, "model", None)) or self.model
        parsed = parse_answers(answers)
        return self._record(JevResult(status="ok", model=model, latency_ms=round(latency, 1), input_tokens=tokens,
                                      **parsed), state_text)

    def _record(self, result: JevResult, state_text: str) -> JevResult:
        self.last = result
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": time.time(), "state": state_text, **result.as_log()}) + "\n")
        return result


class FakeBackend:
    """Deterministic stand-in for tests, replays and dry runs without a key."""

    def __init__(self, answers: dict | None = None, delay_s: float = 0.0, error: Exception | None = None):
        self.answers = answers or {}
        self.delay_s = delay_s
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def system_one(self, state, questions, *, model, timeout):
        self.calls.append((state, questions))
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.error:
            raise self.error
        return {"model": model, "usage": {"input_tokens": 60, "output_tokens": 5},
                "answers": {k: v for k, v in self.answers.items() if k in questions}}
