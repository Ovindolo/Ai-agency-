"""Hard risk engine. Pure code, no model input, no overrides.

Everything that can stop money moving lives here. The policy layer may only ask for LESS risk
(risk_mult <= 1); this module clamps anything else. If a circuit breaker trips, nothing else runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum

from apps.common.config import build, load_yaml


class Action(str, Enum):
    ALLOW = "allow"
    SKIP = "skip"
    PAUSE = "pause"
    KILL = "kill"


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.20
    max_open_positions: int = 2
    cash_reserve_pct: float = 0.30
    risk_per_trade_pct: float = 0.01
    risk_per_trade_min_pct: float = 0.005
    risk_per_trade_max_pct: float = 0.015
    max_daily_loss_pct: float = 0.03
    max_weekly_loss_pct: float = 0.08
    max_drawdown_pct: float = 0.12
    profit_lock_trigger_pct: float = 0.10
    profit_lock_fraction: float = 0.50
    stop_min_pct: float = 0.015
    stop_max_pct: float = 0.025
    min_reward_risk: float = 1.8
    trailing_after_r: float = 1.2
    time_stop_minutes: int = 2880
    min_edge_fee_mult: float = 2.5
    taker_fee_pct: float = 0.001
    slippage_pct: float = 0.0008
    max_spread_bps: float = 10.0
    max_data_age_sec: int = 120
    pause_hours: int = 24
    min_stake_usd: float = 10.0
    cooldown_bars_after_loss: int = 8

    @classmethod
    def load(cls) -> "RiskLimits":
        return build(cls, load_yaml("risk.yaml"))

    def clamp_risk_pct(self, value: float) -> float:
        return min(max(value, self.risk_per_trade_min_pct), self.risk_per_trade_max_pct)

    @property
    def round_trip_cost_pct(self) -> float:
        return 2 * (self.taker_fee_pct + self.slippage_pct)


@dataclass
class AccountState:
    starting_equity: float
    equity: float
    peak_equity: float
    day_start_equity: float
    week_start_equity: float
    realized_pnl_total: float = 0.0
    open_positions: int = 0
    inventory_usd: float = 0.0
    risk_per_trade_pct: float | None = None   # runtime override from /set, clamped
    paused_until: datetime | None = None
    killed: bool = False
    kill_reason: str | None = None
    open_symbols: frozenset[str] = field(default_factory=frozenset)

    @property
    def drawdown_pct(self) -> float:
        return 0.0 if self.peak_equity <= 0 else (self.peak_equity - self.equity) / self.peak_equity

    @property
    def daily_pnl_pct(self) -> float:
        return (self.equity - self.day_start_equity) / self.day_start_equity

    @property
    def weekly_pnl_pct(self) -> float:
        return (self.equity - self.week_start_equity) / self.week_start_equity


@dataclass(frozen=True)
class Candidate:
    symbol: str
    entry: float
    stop: float
    take: float
    spread_bps: float
    data_age_sec: float


@dataclass(frozen=True)
class Verdict:
    action: Action
    reasons: tuple[str, ...] = ()
    stake_usd: float = 0.0
    stop: float | None = None
    take: float | None = None
    stop_pct: float | None = None
    reward_risk: float | None = None

    @property
    def allowed(self) -> bool:
        return self.action is Action.ALLOW


# ---------------------------------------------------------------- circuit breakers

def locked_reserve(state: AccountState, limits: RiskLimits) -> float:
    """Half of realized profit is locked once realized profit reaches +10% of starting equity."""
    trigger = limits.profit_lock_trigger_pct * state.starting_equity
    if state.realized_pnl_total >= trigger:
        return limits.profit_lock_fraction * state.realized_pnl_total
    return 0.0


def circuit_breakers(state: AccountState, limits: RiskLimits, now: datetime) -> Verdict | None:
    """Returns a PAUSE/KILL verdict if any breaker is tripped, else None. Mutates state on trip."""
    if state.killed:
        return Verdict(Action.KILL, (f"killed: {state.kill_reason or 'manual'}",))

    if state.drawdown_pct >= limits.max_drawdown_pct:
        return _kill(state, f"drawdown {state.drawdown_pct:.2%} >= {limits.max_drawdown_pct:.0%}")
    if state.weekly_pnl_pct <= -limits.max_weekly_loss_pct:
        return _kill(state, f"weekly loss {state.weekly_pnl_pct:.2%} <= -{limits.max_weekly_loss_pct:.0%}")

    if state.daily_pnl_pct <= -limits.max_daily_loss_pct:
        if state.paused_until is None or state.paused_until <= now:
            state.paused_until = now + timedelta(hours=limits.pause_hours)
        return Verdict(Action.PAUSE, (f"daily loss {state.daily_pnl_pct:.2%} -> paused until {state.paused_until:%Y-%m-%d %H:%M}",))

    if state.paused_until is not None and state.paused_until > now:
        return Verdict(Action.PAUSE, (f"paused until {state.paused_until:%Y-%m-%d %H:%M}",))
    return None


def _kill(state: AccountState, reason: str) -> Verdict:
    state.killed = True
    state.kill_reason = reason
    return Verdict(Action.KILL, (reason,))


def manual_kill(state: AccountState, reason: str = "manual /kill") -> Verdict:
    return _kill(state, reason)


# ---------------------------------------------------------------- sizing

def position_size(state: AccountState, limits: RiskLimits, stop_pct: float, risk_mult: float = 1.0) -> tuple[float, list[str]]:
    """Stake in USD such that hitting the stop loses risk_pct of equity, capped by every limit.

    risk_mult can only reduce risk. Values above 1 are clamped to 1.
    """
    notes: list[str] = []
    if stop_pct <= 0:
        return 0.0, ["invalid stop"]
    mult = min(max(risk_mult, 0.0), 1.0)
    if risk_mult > 1.0:
        notes.append(f"risk_mult {risk_mult} clamped to 1.0")

    risk_pct = limits.clamp_risk_pct(state.risk_per_trade_pct if state.risk_per_trade_pct is not None else limits.risk_per_trade_pct)
    by_risk = state.equity * risk_pct * mult / stop_pct
    by_position_cap = state.equity * limits.max_position_pct
    deployable = state.equity * (1 - limits.cash_reserve_pct) - state.inventory_usd - locked_reserve(state, limits)

    stake = max(0.0, min(by_risk, by_position_cap, deployable))
    if stake == by_position_cap and by_risk > by_position_cap:
        notes.append("capped by max_position_pct")
    if stake == max(0.0, deployable) and deployable < min(by_risk, by_position_cap):
        notes.append("capped by cash reserve / inventory")
    return round(stake, 2), notes


# ---------------------------------------------------------------- entry gate

def evaluate_entry(state: AccountState, limits: RiskLimits, cand: Candidate, now: datetime, risk_mult: float = 1.0) -> Verdict:
    tripped = circuit_breakers(state, limits, now)
    if tripped:
        return tripped

    reasons: list[str] = []
    if cand.data_age_sec > limits.max_data_age_sec:
        reasons.append(f"stale data {cand.data_age_sec:.0f}s > {limits.max_data_age_sec}s")
    if cand.spread_bps > limits.max_spread_bps:
        reasons.append(f"spread {cand.spread_bps:.1f}bps > {limits.max_spread_bps}bps")
    if state.open_positions >= limits.max_open_positions:
        reasons.append(f"open positions {state.open_positions} >= {limits.max_open_positions}")
    if cand.symbol in state.open_symbols:
        reasons.append(f"already in {cand.symbol}")
    if cand.stop >= cand.entry or cand.take <= cand.entry:
        reasons.append("spot long only: need stop < entry < take")
    if reasons:
        return Verdict(Action.SKIP, tuple(reasons))

    raw_stop_pct = (cand.entry - cand.stop) / cand.entry
    if raw_stop_pct > limits.stop_max_pct:
        return Verdict(Action.SKIP, (f"stop {raw_stop_pct:.2%} > {limits.stop_max_pct:.1%}: too volatile",))
    stop_pct = max(raw_stop_pct, limits.stop_min_pct)
    stop = cand.entry * (1 - stop_pct)
    notes = [f"stop widened {raw_stop_pct:.2%} -> {stop_pct:.2%}"] if stop_pct > raw_stop_pct else []

    target_pct = (cand.take - cand.entry) / cand.entry
    rr = target_pct / stop_pct
    if rr < limits.min_reward_risk:
        return Verdict(Action.SKIP, (*notes, f"reward/risk {rr:.2f} < {limits.min_reward_risk}"))
    min_target = limits.min_edge_fee_mult * limits.round_trip_cost_pct
    if target_pct < min_target:
        return Verdict(Action.SKIP, (*notes, f"target {target_pct:.2%} < {min_target:.2%} edge after fees"))

    stake, size_notes = position_size(state, limits, stop_pct, risk_mult)
    if stake < limits.min_stake_usd:
        return Verdict(Action.SKIP, (*notes, *size_notes, f"stake {stake:.2f} < min {limits.min_stake_usd}"))

    return Verdict(Action.ALLOW, (*notes, *size_notes), stake_usd=stake, stop=round(stop, 8),
                   take=cand.take, stop_pct=stop_pct, reward_risk=round(rr, 2))


# ---------------------------------------------------------------- open-position management

@dataclass
class Position:
    symbol: str
    entry: float
    stop: float
    take: float
    stake_usd: float
    opened_at: datetime
    initial_stop: float | None = None

    def __post_init__(self) -> None:
        if self.initial_stop is None:
            self.initial_stop = self.stop

    @property
    def r_value(self) -> float:
        return self.entry - (self.initial_stop or self.stop)


@dataclass(frozen=True)
class ExitDecision:
    action: str            # hold | tighten | exit
    new_stop: float | None = None
    reason: str = ""


def manage_position(pos: Position, price: float, now: datetime, limits: RiskLimits) -> ExitDecision:
    """Stops, targets, time-stop and trailing. Stops only ever move up."""
    if price <= pos.stop:
        return ExitDecision("exit", reason=f"stop hit {price} <= {pos.stop}")
    if price >= pos.take:
        return ExitDecision("exit", reason=f"target hit {price} >= {pos.take}")
    if now - pos.opened_at >= timedelta(minutes=limits.time_stop_minutes):
        return ExitDecision("exit", reason=f"time stop {limits.time_stop_minutes}m")

    r = pos.r_value
    if r > 0 and price - pos.entry >= limits.trailing_after_r * r:
        trail = price - r                      # trail one R behind price
        if trail > pos.stop:
            return ExitDecision("tighten", new_stop=round(trail, 8), reason=f"trailing after +{limits.trailing_after_r}R")
    return ExitDecision("hold")


def tighten_only(pos: Position, proposed_stop: float) -> Position:
    """A stop may be raised, never lowered. Used for any Jev-requested tightening too."""
    return replace(pos, stop=max(pos.stop, proposed_stop))
