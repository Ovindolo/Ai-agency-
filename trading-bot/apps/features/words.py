"""Numbers -> words. The only thing Jev ever sees.

Models read tokens, not numbers: they get magnitudes and decimal comparisons wrong. So the code does
every comparison against thresholds from config/buckets.yaml and hands over one word per dimension.
The mapping is deterministic and unit-tested; change a cut point in YAML, not here.
"""
from __future__ import annotations

from apps.common.config import load_yaml
from apps.features.snapshot import Snapshot

_B = None


def buckets() -> dict:
    global _B
    if _B is None:
        _B = load_yaml("buckets.yaml")
    return _B


def _tri(x: float, hi: float, lo: float, up: str, down: str, mid: str) -> str:
    return up if x > hi else down if x < lo else mid


def to_words(s: Snapshot, b: dict | None = None) -> list[str]:
    b = b or buckets()
    in_pos = s.inventory_usd > 0
    words = [
        _tri(s.ema_gap, b["ema_gap"]["up"], b["ema_gap"]["down"], "uptrend", "downtrend", "flat_trend"),
        "trending" if s.adx_1h >= 20 else "choppy",
        _tri(s.return_15m, b["return_15m"]["up"], b["return_15m"]["down"], "pumping", "dumping", "drifting"),
        _tri(s.return_1h, b["return_1h"]["up"], b["return_1h"]["down"], "hour_up", "hour_down", "hour_flat"),
        "violent" if s.atr_pct > b["atr_pct"]["violent"] else "calm" if s.atr_pct < b["atr_pct"]["calm"] else "normal_vol",
        _tri(s.vol_vs_24h, b["vol_vs_24h"]["expanding"], b["vol_vs_24h"]["contracting"],
             "vol_expanding", "vol_contracting", "vol_steady"),
        "wide_spread" if s.spread_bps > b["spread_bps"]["wide"] else "tight_spread",
        "thin_book" if s.depth_usd_l1 < b["depth_usd_l1"]["thin"] else "deep_book",
        _tri(s.volume_vs_avg, b["volume_vs_avg"]["heavy"], b["volume_vs_avg"]["light"],
             "heavy_volume", "light_volume", "normal_volume"),
        _tri(s.taker_buy_ratio, b["taker_buy_ratio"]["buyers"], b["taker_buy_ratio"]["sellers"],
             "buyers_aggressive", "sellers_aggressive", "balanced_flow"),
        ("long_winning" if s.unrealized_pnl_pct > 0 else "long_losing") if in_pos else "flat",
        _tri(s.daily_pnl_pct, b["daily_pnl_pct"]["up"], b["daily_pnl_pct"]["down"], "day_up", "day_down", "day_flat"),
        "signal_long_pullback" if s.strategy_side == "long" else "no_signal",
        ("rr_good" if s.strategy_rr >= b["rr"]["good"] else "rr_ok") if s.strategy_side == "long" else "rr_none",
    ]
    return words


def state_text(s: Snapshot, b: dict | None = None) -> str:
    """Space-separated words. ~14 tokens. No digits, no decimals, no secrets."""
    return " ".join(to_words(s, b))
