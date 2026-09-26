import json
from datetime import datetime, timezone

import pytest

from apps.review.learn import brier, calibration_table, load, suggestions, write
from apps.risk.engine import RiskLimits, kelly_mult, r_multiple, realized_kelly

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


def test_r_multiple():
    assert r_multiple(-2.0, 100, 100, 98) == pytest.approx(-1.0)      # lost exactly the stop distance
    assert r_multiple(4.0, 100, 100, 98) == pytest.approx(2.0)


def test_realized_kelly():
    assert realized_kelly([2, -1] * 10) == pytest.approx(0.25)        # p=.5, b=2 -> .5 - .5/2
    assert realized_kelly([1, -1, -1] * 10) < 0
    assert realized_kelly([1, 2]) is None                              # no loss yet


def test_kelly_only_brakes():
    L = RiskLimits()
    assert kelly_mult([1, -1, -1] * 5, L) == 1.0                        # < 30 trades: no opinion
    assert kelly_mult([1, -1, -1] * 10, L) == L.kelly_negative_mult     # no edge -> half size
    assert kelly_mult([5, -1] * 20, L) == 1.0                           # big edge still never sizes up


def test_brier_skill_against_base_rate():
    perfect = [(1.0, 1), (0.0, 0)] * 10
    assert brier(perfect)[2] == pytest.approx(1.0)
    useless = [(0.5, 1), (0.5, 0)] * 10                                 # says the base rate: skill 0
    assert brier(useless)[2] == pytest.approx(0.0)
    overconfident_wrong = [(0.9, 0), (0.9, 1), (0.9, 0), (0.9, 0)]
    assert brier(overconfident_wrong)[2] < 0
    assert brier([]) is None


def test_calibration_table_bins():
    rows = calibration_table([(0.1, 0), (0.15, 0), (0.9, 1), (1.0, 1)], bins=5)
    assert rows[0][1] == 2 and rows[-1][1] == 2 and rows[-1][3] == 1.0


def _write_log(base, trades):
    (base / "logs").mkdir(parents=True)
    with open(base / "logs" / "decisions.jsonl", "w") as fh:
        for i, (p, pnl, r, reason) in enumerate(trades):
            ans = {"aligned_with_signal": {"type": "noul", "noul": p},
                   "setup_quality": {"type": "score", "score": 2.4, "confidence": 0.9}} if p is not None else None
            fh.write(json.dumps({"type": "decision", "id": f"d{i}", "jev_answers": ans,
                                 "policy_fallback": "normal" if p is not None else "jev_disabled"}) + "\n")
            fh.write(json.dumps({"type": "outcome", "decision_id": f"d{i}", "ret_15m": 0.001 if pnl > 0 else -0.001}) + "\n")
            fh.write(json.dumps({"type": "exit", "decision_id": f"d{i}", "pnl": pnl, "r": r, "reason": reason}) + "\n")


def test_review_reads_log_and_writes_learnings(tmp_path):
    trades = [(0.8, 2.6, 1.8, "target"), (0.3, -1.9, -1.0, "stop")] * 15
    _write_log(tmp_path, trades)
    rv = load(tmp_path)
    assert rv.n == 30 and rv.wins == 15 and len(rv.judged) == 30
    assert brier(rv.judged)[2] > 0                                     # informative Jev in this fake log
    _, text = write(tmp_path, NOW)
    md = (tmp_path / "context" / "Learnings.md").read_text()
    assert "Calibrare Jev" in md and "Propuneri" in md and text in md


def test_suggestions_never_raise_risk(tmp_path):
    _write_log(tmp_path, [(None, -1.9, -1.0, "stop"), (None, 1.0, 0.5, "target"), (None, -1.9, -1.0, "stop")] * 10)
    s = " ".join(suggestions(load(tmp_path), RiskLimits()))
    assert "niciun avantaj" in s and "jumătate" in s


def test_few_trades_means_no_conclusion(tmp_path):
    _write_log(tmp_path, [(0.9, 2.0, 1.0, "target")] * 3)
    assert "prea puține" in suggestions(load(tmp_path), RiskLimits())[0]
