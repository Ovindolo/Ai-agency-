"""The Jev question battery. One call, atomic questions, no numbers in the wording.

Thresholds are NOT here. Jev answers; apps/policy decides what the answers mean.
"""
from __future__ import annotations

ENTRY_QUESTIONS: dict = {
    "regime": {
        "type": "choice",
        "instructions": "Classify the current market regime for this asset.",
        "criteria": {
            "trending_up": "price is in a sustained rise with pullbacks being bought",
            "trending_down": "price is in a sustained decline with bounces being sold",
            "mean_reverting": "price oscillates around a level without direction",
            "chop": "no clear direction, erratic small moves in both directions",
            "high_vol": "large violent moves that make stops unreliable",
            "crisis": "disorderly market: crash, liquidation cascade, exchange or stablecoin stress",
        },
    },
    "setup_quality": {
        "type": "score",
        "instructions": "Rate this long pullback setup for a spot entry.",
        "criteria": [
            "do not trade: conditions contradict the setup",
            "marginal: setup is present but weak",
            "standard: a normal, acceptable setup",
            "excellent: trend, pullback, volume and flow all agree",
        ],
    },
    "aligned_with_signal": {
        "type": "noul",
        "instructions": "Does this state support entering the candidate long now?",
        "criteria": {
            "true": "trend, momentum and flow support a long entry",
            "false": "the state argues against a long entry",
        },
    },
    "toxic_or_unstable": {
        "type": "noul",
        "instructions": "Is this a poor environment to open any new position?",
        "criteria": {
            "true": "thin book, wide spread, violent or erratic conditions",
            "false": "orderly conditions where a stop is likely to be honoured",
        },
    },
}

EXIT_QUESTION: dict = {
    "exit_urgency": {
        "type": "score",
        "instructions": "For the open long position, how urgently should risk be reduced?",
        "criteria": [
            "hold: the trade thesis is intact",
            "tighten: move the stop closer",
            "reduce: take part of the position off",
            "flatten: the thesis is broken, exit",
        ],
    },
}


def questions(candidate_signal: bool, in_position: bool) -> dict:
    q: dict = {}
    if candidate_signal:
        q.update(ENTRY_QUESTIONS)
    if in_position:
        q.update(EXIT_QUESTION)
    return q
