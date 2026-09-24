"""Run community Freqtrade strategies through OUR pipeline.

We keep only a strategy's ENTRY logic (populate_indicators + populate_entry_trend -> enter_long).
Its stoploss / minimal_roi / trailing settings are discarded: those are usually hyperopt artefacts
(stoploss = -0.34549 is an optimiser's fingerprint, not a decision). Every imported entry exits
through our stops, targets, risk engine and fees, exactly like the built-in strategy.

Before any strategy is allowed into a tournament it must pass the lookahead check.
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from apps.features.snapshot import resample_1h
from apps.strategy.trend_pullback import StrategyParams, exit_frame

SUPPORTED_TF = {"15m": "15min", "30m": "30min", "1h": "1h", "2h": "2h", "4h": "4h"}


@dataclass
class Imported:
    name: str
    path: str
    timeframe: str | None = None
    status: str = "unknown"      # ok | load_error | unsupported_timeframe | needs_dataprovider | run_error | lookahead | no_signals
    detail: str = ""
    entries: pd.Series | None = field(default=None, repr=False)

    @property
    def usable(self) -> bool:
        return self.status == "ok"


def load_strategy_classes(path: Path) -> list[type]:
    from freqtrade.strategy import IStrategy
    spec = importlib.util.spec_from_file_location(f"ext_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return [c for _, c in inspect.getmembers(mod, inspect.isclass)
            if issubclass(c, IStrategy) and c is not IStrategy and c.__module__ == mod.__name__]


def _resample(df15: pd.DataFrame, rule: str) -> pd.DataFrame:
    if rule == "15min":
        return df15
    if rule == "1h":
        return resample_1h(df15)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    bars = df15.resample(rule, label="left", closed="left").agg(agg).dropna()
    need = pd.Timedelta(rule) // pd.Timedelta("15min")
    counts = df15["close"].resample(rule, label="left", closed="left").count()
    return bars[counts.reindex(bars.index) == need]


class _MiniDataProvider:
    """Just enough of Freqtrade's DataProvider for single-pair strategies. Serves ONLY the data it was given."""

    def __init__(self, df15: pd.DataFrame, pair: str):
        self._df15, self._pair = df15, pair

    def current_whitelist(self) -> list[str]:
        return [self._pair]

    def get_pair_dataframe(self, pair: str, timeframe: str | None = None, candle_type: str = "") -> pd.DataFrame:
        rule = SUPPORTED_TF.get(timeframe or "15m")
        if rule is None:
            raise RuntimeError(f"informative timeframe {timeframe} unavailable")
        return _resample(self._df15, rule).reset_index(names="date")

    historic_ohlcv = get_pair_dataframe

    def runmode(self):  # pragma: no cover - some strategies probe it
        return None


def _run(cls: type, df15: pd.DataFrame, pair: str = "BTC/USDT") -> tuple[pd.DataFrame, pd.DatetimeIndex, str]:
    tf = getattr(cls, "timeframe", "15m")
    strat = cls(config={"stake_currency": "USDT", "timeframe": tf, "dry_run": True,
                        "exchange": {"name": "binance", "pair_whitelist": [pair]}})
    strat.dp = _MiniDataProvider(df15, pair)
    rule = SUPPORTED_TF[tf]
    bars = _resample(df15, rule).copy()
    df = bars.reset_index(names="date")
    meta = {"pair": pair}
    df = strat.populate_indicators(df, meta)
    df = strat.populate_entry_trend(df, meta)
    return df, bars.index, rule


def indicator_frame(cls: type, df15: pd.DataFrame) -> pd.DataFrame:
    """Every numeric column the strategy computes, indexed by its own candle time."""
    df, idx, _ = _run(cls, df15)
    num = df.select_dtypes(include=[np.number, "bool"]).astype(float)
    num.index = idx
    return num


def entry_signals(cls: type, df15: pd.DataFrame) -> pd.Series:
    """Boolean entry per 15m bar. Higher-timeframe signals land on the 15m bar that CLOSES that candle."""
    df, idx, rule = _run(cls, df15)
    col = "enter_long" if "enter_long" in df else ("buy" if "buy" in df else None)
    if col is None:
        raise RuntimeError("strategy produced no enter_long column")
    sig = pd.Series(df[col].fillna(0).astype(float).to_numpy() > 0, index=idx)
    if rule == "15min":
        return sig.reindex(df15.index, fill_value=False)
    # candle [t, t+rule) closes at the 15m bar starting t+rule-15m
    closing = sig.index + pd.Timedelta(rule) - pd.Timedelta("15min")
    mapped = pd.Series(sig.to_numpy(), index=closing)
    return mapped.reindex(df15.index, fill_value=False)


def has_lookahead(cls: type, df15: pd.DataFrame, cuts: int = 8, rtol: float = 1e-9) -> tuple[bool, str]:
    """Every value the strategy computes for a past candle must be identical whether it is computed with
    data up to that candle or with the full history. Checks ALL numeric columns, not just entries - a
    strategy that never fires can still leak the future into its indicators."""
    full = indicator_frame(cls, df15)
    n = len(df15)
    for k in np.linspace(n * 0.5, n - 1, cuts).astype(int):
        part = indicator_frame(cls, df15.iloc[:k])
        common = part.index.intersection(full.index)
        cols = [c for c in part.columns if c in full.columns]
        a = full.loc[common, cols].to_numpy()
        b = part.loc[common, cols].to_numpy()
        same = np.isclose(a, b, rtol=rtol, atol=1e-12, equal_nan=True)
        if not same.all():
            bad_cols = [cols[j] for j in np.flatnonzero(~same.all(axis=0))]
            return True, f"{len(bad_cols)} column(s) change when later data is added: {', '.join(bad_cols[:4])}"
    return False, ""


def import_strategy(path: Path, df15: pd.DataFrame) -> list[Imported]:
    out: list[Imported] = []
    try:
        classes = load_strategy_classes(path)
    except Exception as exc:
        return [Imported(path.stem, str(path), status="load_error", detail=f"{type(exc).__name__}: {exc}"[:160])]
    for cls in classes:
        imp = Imported(cls.__name__, str(path), getattr(cls, "timeframe", None))
        if imp.timeframe not in SUPPORTED_TF:
            imp.status, imp.detail = "unsupported_timeframe", f"{imp.timeframe} (we have 15m data)"
            out.append(imp)
            continue
        try:
            look, why = has_lookahead(cls, df15)
            if look:
                imp.status, imp.detail = "lookahead", why
            else:
                imp.entries = entry_signals(cls, df15)
                imp.status = "ok" if imp.entries.any() else "no_signals"
        except AttributeError as exc:
            imp.status = "needs_dataprovider" if "dp" in str(exc) or "NoneType" in str(exc) else "run_error"
            imp.detail = f"{type(exc).__name__}: {exc}"[:160]
        except Exception as exc:
            imp.status, imp.detail = "run_error", f"{type(exc).__name__}: {exc}"[:160]
        out.append(imp)
    return out


def signal_frame(entries: pd.Series, df15: pd.DataFrame, p: StrategyParams = StrategyParams()) -> pd.DataFrame:
    """Imported entries + our exits, in the shape run_backtest expects."""
    ef = exit_frame(df15, p)
    ef["signal"] = entries.reindex(df15.index, fill_value=False) & ef["tradable"]
    return ef
