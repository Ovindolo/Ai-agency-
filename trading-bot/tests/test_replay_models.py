import itertools
import json

from apps.jev.client import FakeBackend, JevClient
from apps.review.replay_models import load_cases, markdown, replay
from tests.test_jev_policy import GOOD

BAD = {**GOOD, "toxic_or_unstable": {"type": "noul", "noul": 0.9}}          # this answer makes the policy skip


def write_log(tmp_path, n=6):
    rows = []
    for i in range(n):
        rows.append({"type": "decision", "id": f"d{i}", "words": f"uptrend calm state {i}", "jev_model": "jev-latest",
                     "jev_answers": {k: v for k, v in GOOD.items() if k != "exit_urgency"}})
        rows.append({"type": "outcome", "decision_id": f"d{i}", "ret_15m": 0.002 if i % 2 == 0 else -0.002})
        if i < 4:
            rows.append({"type": "exit", "decision_id": f"d{i}", "pnl": 3.0 if i % 2 == 0 else -2.0})
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


class Flaky:
    """Answers alternate between GOOD and BAD on every call: an unstable model."""
    def __init__(self):
        self.cycle = itertools.cycle([GOOD, BAD])

    def system_one(self, state, questions, *, model, timeout):
        ans = next(self.cycle)
        return {"model": model, "usage": {"input_tokens": 40}, "answers": {k: v for k, v in ans.items() if k in questions}}


def test_cases_join_words_answers_and_outcomes(tmp_path):
    write_log(tmp_path)
    cases = load_cases(tmp_path)
    assert len(cases) == 6 and cases[0].won == 1 and cases[1].won == 0 and cases[5].won is None
    assert cases[0].up_15m == 1 and cases[0].recorded["model"] == "jev-latest"


def test_stable_model_agrees_and_never_flips(tmp_path):
    write_log(tmp_path)
    sc = replay(load_cases(tmp_path), JevClient(api_key="t", model="same", backend=FakeBackend(GOOD), log_path=None))
    assert (sc.ok, sc.agree, sc.comparable, sc.flips, sc.repeated) == (6, 6, 6, 0, 6)
    assert sc.tokens == 6 * 60 and len(sc.vs_trade) == 4 and len(sc.vs_move) == 6


def test_unstable_model_is_caught(tmp_path):
    write_log(tmp_path)
    sc = replay(load_cases(tmp_path), JevClient(api_key="t", model="flaky", backend=Flaky(), log_path=None), repeats=2)
    assert sc.flips == sc.repeated == 6                    # same state, different decision every time
    md = markdown([sc], 6, price_per_mtok=1.0)
    assert "flaky" in md and "100% din 6" in md
