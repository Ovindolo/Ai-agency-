# What we took from outside, and what we refused (2026-09-24)

## From the "one-person AI hedge fund" prompt

| Idea | Verdict | Where |
|---|---|---|
| Log every decision with strategy_id, decision_id, model_version, expected vs actual price | **Taken** | `apps/trader/runner.py` (strategy/config version hashes, expected_price, fill, slippage_bps) |
| Correlation limits | **Taken** | `correlation_mult` in `apps/risk/engine.py`: >0.70 1h-return correlation with an open position -> half size |
| `crisis` regime | **Taken** as a Jev choice; policy skips every entry on it | `apps/jev/battery.py`, `apps/policy/engine.py` |
| Brier score / calibration | **Next** — decisions + 15m outcomes are already logged for it | review loop |
| Shadow mode between paper and live | **Next** — part of the graduation checklist | docs/LIVE_CHECKLIST.md |
| Machine-readable strategy spec | **Next** — `strategies/*.yaml` once there is a second strategy | |
| Jev `should_trade`, `expected_edge 0-100`, `confidence` as a question | **Refused** — `should_trade` makes the model the decider; a 0-100 "edge" is an invented number; confidence already comes with every choice/score answer | |
| `direction: short` | **Refused** — spot only | |
| "Escalate to Opus when confidence < 0.60" in the hot path | **Refused** — a slow model in a 15m loop; low confidence already means smaller size or skip; the case is logged for the evening review | |
| 11 LLM "departments", 5-10 asymmetric token theses | **Refused for this bot** — discretionary research at fund scale; with 500 USDT, fees and correctness matter more than theses | |
| AgenKit orchestration | **Refused** — a paid Claude Code add-on; the original spec forbids depending on it | |

## From the most-starred repos

| Repo | What it is | Taken |
|---|---|---|
| freqtrade/freqtrade (~54k★) | spot/futures bot, Telegram, backtesting | **StoplossGuard** (3 stops in 12h -> 6h without entries), already had CooldownPeriod; lookahead check already ported; their *recursive analysis* idea verified: indicators on the 1000-bar live window equal full history to 5e-9 |
| nautechsystems/nautilus_trader (~29k★) | Rust event-driven engine, same code for backtest and live | **Parity test**: paper runner and backtest take the same trades on the same data (`test_paper_runner_matches_backtest`) |
| TauricResearch/TradingAgents | LLM analysts + bull/bear debate + decision memory with realized returns | Pattern for the **evening review** only (bull vs bear case on the week's trades, lessons with realized results). Never in the order path |
| virattt/ai-hedge-fund (~64k★) | multi-agent stock analysis, educational, no live trading | Nothing new: risk manager before portfolio manager is already our order |
| hummingbot | market making / execution | Nothing now (market making is forbidden); its order-tracking/reconciliation matters when live exists |
| shiyu-coder/Kronos (AAAI 2026) | foundation model for OHLCV candles | **Candidate** for the tournament as a feature, only if it survives out-of-sample after costs |

## A bug these sources exposed

`risk_mult` (low confidence, correlation) scaled only the risk-based size, and with 1.5-2.5% stops the 20%
position cap always bound first, so "reduce size" did nothing. Fixed: the multiplier applies after the caps
(`test_reduce_size_bites_even_when_cap_binds`). Consequence worth knowing: real risk per trade is about
20% x stop = 0.3-0.5% of equity, not the nominal 1%.

## From the "elite quant architect" prompt (2026-09-26)

A variant of the fund prompt (AgenKit named four times). New items only:

| Idea | Verdict | Where |
|---|---|---|
| Fractional Kelly "from Jev's calibrated probability", capped at quarter Kelly | **Taken, inverted.** Kelly is computed from OUR closed trades (win rate, avg win/loss in R), never from a model probability that has not been shown to be calibrated. It only brakes: after 30 trades with Kelly <= 0, size halves. A positive Kelly never raises size (quarter Kelly of our stats would be ~3-4% risk per trade, far above the hard limit) | `realized_kelly`, `kelly_mult` in `apps/risk/engine.py`, both engines |
| Nightly review, Brier score | **Taken.** Every 10 trades (big at 25): win rate, PF, R per trade, exits by reason, Jev calibration vs base rate (skill), suggestions. Nothing applied automatically | `apps/review/learn.py` -> `context/Learnings.md` + Telegram |
| "Rewrite the Jev schema and ship it before the next open" automatically | **Refused.** Changes go through replay + operator approval; one night of data is not evidence | |
| Jev `risk_state` (safe/near_limit/reduce) | **Refused.** Drawdown and daily loss are known exactly in code; asking a model to guess them adds error | |
| `direction` confidence > 0.80 gate | **Refused.** Spot long only; confidence already gates size | |
| Max drawdown 15% | **Kept ours: 12%** (stricter) | |
| State snapshot < 400 tokens, causal timestamps, numbers computed in code | **Already there**: ~14 words, closed candles only, parity- and lookahead-tested | |
