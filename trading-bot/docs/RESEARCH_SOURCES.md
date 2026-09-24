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
