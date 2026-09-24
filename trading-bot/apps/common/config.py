"""Config loading. YAML files in /config are the single source of thresholds."""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


def load_yaml(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def build(cls, data: dict[str, Any]):
    """Construct a dataclass from a dict, ignoring unknown keys and failing on missing ones."""
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


@dataclass(frozen=True)
class PolicyThresholds:
    toxic_max_noul: float = 0.65
    setup_min_score: float = 2.0
    aligned_min_noul: float = 0.55
    low_confidence: float = 0.80
    low_confidence_risk_mult: float = 0.5
    jev_down_risk_mult: float = 1.0
    exit_tighten_at: float = 0.8
    exit_reduce_at: float = 1.5
    exit_flatten_at: float = 2.5

    @classmethod
    def load(cls) -> "PolicyThresholds":
        return build(cls, load_yaml("policy.yaml"))
