import time

import pytest

from apps.common.config import PolicyThresholds
from apps.features.snapshot import build_snapshot
from apps.jev.client import FakeBackend, JevClient, JevResult
from apps.policy.engine import compose_entry, compose_exit
from tests.helpers import synthetic_15m

T = PolicyThresholds()
GOOD = {
    "regime": {"type": "choice", "choice": "trending_up", "confidence": 0.9,
               "probabilities": {"trending_up": 0.9, "chop": 0.1}},
    "setup_quality": {"type": "score", "score": 2.4, "confidence": 0.88},
    "aligned_with_signal": {"type": "noul", "noul": 0.8},
    "toxic_or_unstable": {"type": "noul", "noul": 0.1},
    "exit_urgency": {"type": "score", "score": 0.2, "confidence": 0.9},
}


@pytest.fixture
def signal_snap():
    return build_snapshot("BTC/USDT", synthetic_15m(), signal={"side": "long", "rr": 2.0, "stop_pct": 0.02, "take_pct": 0.04})


def client(answers=None):
    return JevClient(api_key="test", backend=FakeBackend(answers if answers is not None else GOOD), log_path=None)


def ask(c, **kw):
    return c.ask("uptrend trending", candidate_signal=kw.get("sig", True), in_position=kw.get("pos", False))


def test_config_matches_defaults():
    assert PolicyThresholds.load() == T


# ------------------------------------------------ client
def test_disabled_without_key():
    r = JevClient(api_key="", log_path=None).ask("x", candidate_signal=True, in_position=False)
    assert r.status == "disabled"

def test_ok_parses_all_types():
    r = ask(client())
    assert r.ok and r.regime.choice == "trending_up" and r.setup_quality.score == 2.4
    assert r.aligned_with_signal.noul == 0.8 and r.input_tokens == 60

def test_only_relevant_questions_are_sent():
    fb = FakeBackend(GOOD)
    c = JevClient(api_key="t", backend=fb, log_path=None)
    c.ask("x", candidate_signal=True, in_position=False)
    assert "exit_urgency" not in fb.calls[-1][1]
    c.ask("x", candidate_signal=False, in_position=True)
    assert set(fb.calls[-1][1]) == {"exit_urgency"}

def test_late_answer_is_timeout():
    c = JevClient(api_key="t", backend=FakeBackend(GOOD, delay_s=0.06), timeout_ms=20, log_path=None)
    assert ask(c).status == "timeout"

def test_api_error_is_down_and_does_not_raise():
    c = JevClient(api_key="t", backend=FakeBackend(error=ConnectionError("boom")), log_path=None)
    assert ask(c).status == "down"

def test_timeout_exception_classified():
    class TypeSafeAPITimeoutError(Exception): ...
    c = JevClient(api_key="t", backend=FakeBackend(error=TypeSafeAPITimeoutError("slow")), log_path=None)
    assert ask(c).status == "timeout"


# ------------------------------------------------ policy
def test_all_gates_pass(signal_snap):
    d = compose_entry(signal_snap, ask(client()), T)
    assert d.action == "enter" and d.risk_mult == 1.0 and d.fallback == "normal"

def test_no_signal_means_no_trade_even_if_jev_loves_it():
    s = build_snapshot("BTC/USDT", synthetic_15m())
    assert compose_entry(s, ask(client()), T).action == "skip"

def test_timeout_holds(signal_snap):
    d = compose_entry(signal_snap, JevResult(status="timeout", latency_ms=900), T)
    assert d.action == "hold" and d.risk_mult == 0

@pytest.mark.parametrize("status", ["down", "disabled"])
def test_jev_unavailable_falls_back_without_extra_size(signal_snap, status):
    d = compose_entry(signal_snap, JevResult(status=status), T)
    assert d.action == "enter" and d.risk_mult <= 1.0

@pytest.mark.parametrize("patch,fragment", [
    ({"toxic_or_unstable": {"type": "noul", "noul": 0.7}}, "toxic"),
    ({"setup_quality": {"type": "score", "score": 1.6, "confidence": 0.9}}, "setup"),
    ({"aligned_with_signal": {"type": "noul", "noul": 0.5}}, "aligned"),
    ({"regime": {"type": "choice", "choice": "chop", "confidence": 0.9, "probabilities": {}}}, "regime chop"),
    ({"regime": {"type": "choice", "choice": "crisis", "confidence": 0.9, "probabilities": {}}}, "crisis"),
])
def test_each_gate_can_veto(signal_snap, patch, fragment):
    d = compose_entry(signal_snap, ask(client({**GOOD, **patch})), T)
    assert d.action == "skip" and any(fragment in r for r in d.reasons), d.reasons

def test_low_confidence_halves_size(signal_snap):
    low = {**GOOD, "regime": {**GOOD["regime"], "confidence": 0.7}}
    d = compose_entry(signal_snap, ask(client(low)), T)
    assert d.action == "enter" and d.risk_mult == 0.5 and d.fallback == "low_confidence"

def test_jev_can_never_enlarge():
    t = PolicyThresholds(low_confidence_risk_mult=3.0, jev_down_risk_mult=5.0)
    s = build_snapshot("BTC/USDT", synthetic_15m(), signal={"side": "long", "rr": 2})
    low = {**GOOD, "regime": {**GOOD["regime"], "confidence": 0.5}}
    assert compose_entry(s, ask(client(low)), t).risk_mult <= 1.0
    assert compose_entry(s, JevResult(status="down"), t).risk_mult <= 1.0

@pytest.mark.parametrize("u,expected", [(0.2, "hold"), (1.0, "tighten"), (1.8, "reduce"), (2.7, "flatten")])
def test_exit_advice(u, expected):
    r = ask(client({"exit_urgency": {"type": "score", "score": u, "confidence": 0.9}}), sig=False, pos=True)
    assert compose_exit(r, T).action == expected

def test_exit_advice_holds_when_jev_unavailable():
    assert compose_exit(JevResult(status="down"), T).action == "hold"
