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
| shiyu-coder/Kronos (AAAI 2026) | foundation model for OHLCV candles | **Wired, not yet judged**: `make kronos-setup && make kronos` scores forecast skill and runs it through the tournament, only on data after 2025-09 (it may have been pre-trained on anything earlier) |

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

## Challenge loop: "500$, a family, make it work" (2026-09-26)

Researched twice before building. What the evidence says, and what was built from it:

| Finding | Source | Built |
|---|---|---|
| 97% of people who day-traded futures for 300+ days lost money; no evidence of learning | Chague, De-Losso, Giovannetti, *Day Trading for a Living?* (SSRN 3423101) | Nothing to build; it is the base rate the bot must beat |
| No peer-reviewed evidence that paid Telegram signal groups make money; channels delete failed calls | web reviews, no academic study found | `apps/audit/signals.py`: replays the operator's group signals with fills, stop-first ambiguity, leverage liquidation, fees, funding and subscription |
| Costs dominate a small account: Binance spot VIP0 0.10% maker/taker, 0.075% with BNB | Binance fee pages (via search) | `make fees` reads the account's real per-symbol fees |
| BTC/FDUSD, ETH/FDUSD: 0% maker for regular users since 2024-04-25, kept in the 2026-01-15 update; taker standard | Binance announcements (via search) | Maker entries (post-only limit, 1 bar, 2 bps through-fill rule) and maker targets, exact backtest/runner parity |
| FDUSD depegged to $0.87 on 2025-04-02 | CoinDesk, BeInCrypto | Warning in `make fees`; only hold FDUSD while trading |
| Time-series momentum on DAILY data (20-65 days) is the best-documented crypto effect; benefit is mainly lower drawdowns, often lower return than buy-and-hold after costs | Le & Ruthbah (Monash / SSRN 4551518); Rozario et al. (arXiv 2009.12155) | `daily_mom_days` filter for the 15m strategy; `apps/strategy/daily_trend.py` core vs buy-and-hold vs weekly DCA |

Measured on simulated data (plumbing only; real data decides): on the same signals, zero-fee maker
execution added 20-50 USDT/year over taker on 500; on a pure random walk the 15m strategy with all
costs removed is break-even (PF ~1.0): its losses are its costs, not bad luck.

## Round 3: "use everything on the internet; memes, leverage, hacks, anything" (2026-09-26)

| Asked for | Verdict | Evidence | Built |
|---|---|---|---|
| 10 financial MCPs | In Claude's registry: LunarCrush, FMP, CoinDesk (not CoinGecko, Dune, CMC, CryptoPanic, altFINs, Perplexity, QuiverQuant, TradingView). MCPs help Claude research in chat; the bot needs direct APIs. FMP/QuiverQuant are equities data | registry search | Funding and Fear & Greed as testable entry filters (`apps/features/market_context.py`, `make tournament-context`) |
| Leverage | Growth-optimal leverage is mu/sigma^2; beyond it the MEDIAN outcome falls. On BTC-like simulated days (Kelly 1.4x, +73%/yr at 1x) constant 5x left a median of 25 from 500; 10x+ was liquidated in 95-100% of paths | Kelly; 10 Oct 2025: $19B liquidated in a day, 1.6M accounts | `apps/research/leverage.py` (`make leverage` on real candles) |
| Funding carry | Real and peer-reviewed (~8%/yr mean for BTC), compressed since 2024; a public walk-forward stopped trading in Dec 2024; ADL can break the hedge in a crash | BIS WP 1087 / Management Science 2026; github.com/zwmjj/funding-rate-arb | `apps/research/carry.py` (`make carry`, per year vs cash) |
| Memecoins | <1% of pump.fun tokens graduate; profitable wallets 30-50% per month through 2025 (more in 2026 after retail left); $10k+ realized puts a wallet in the top ~0.4% | CoinGecko research, Cointelegraph/Dune | Nothing: no backtestable edge without first-block on-chain infrastructure, and rugs are the base case |
| NostalgiaForInfinity | Most used freqtrade strategy (~2.9k stars); 5m timeframe; users reported repeated liquidated longs on futures during 10 Oct 2025 | GitHub repo and issues | Not yet: needs 5m data support in the adapter |
| "Hacks, vulnerabilities" | Refused: exploiting a protocol or exchange is theft. The legal version is bug bounties: Immunefi has paid $134M+ | Immunefi | Nothing (a skill, not a bot) |

## Round 4: the Jev ecosystem repos (2026-09-27)

All twelve exist (checked on GitHub). What each gives this bot:

| Repo | Verdict | Built |
|---|---|---|
| jaredpalmer/kev (~7.4k) | **Used.** Qwen-based Jev-like models, same `POST /v1/systemone` wire format; the official SDK points at it via `base_url`. Its own table: Brier 0.269 (Kev-4B) vs 0.211 (Jev) on non-trading tasks | `JEV_BASE_URL` in `JevClient`: free local decisions; review splits calibration per model so Jev and Kev are compared on OUR trades |
| typesafe-ai/skills (~2.3k) + the SDK itself | **Used to verify.** SDK default retry policy (2 retries, 0.5-5s backoff) would block the 15m loop on answers we discard as late. Score answers must carry `legend` | `RetryPolicy(max_retries=0)`; tests run through the real SDK with a mock HTTP transport |
| vinnylarouge/jevlike (~1.3k) | **Prepared.** Trainer for your own Jev-like model from `{context, options, label}` rows | `apps/review/export_training.py`: our logged states + what happened next |
| browser-use/jev-ultrafast (~20.8k) | Pattern only: one round trip per decision, re-check state freshness before acting. Already done (one battery call, data-age gate) | none |
| jarrodwatts/jev-trader (~2.6k) | Refused, as the original spec said: Monad market making every block, dry-run only, no P&L published | none |
| laya-mlx, clm, SemIf-OpenJev | Alternatives; not drop-in with the SDK (Kev is) | none |
| typesafe-computer-use, fast-jev-compaction, awesome-jev lists | Not trading. Compaction is a Claude Code plugin (needs a TypeSafe key) | none |

## Round 5: the "elite research analyst" prompt (2026-09-28)

A sound, ad-free research protocol. What it required that the project did not have yet, now in `make research`
(`apps/research/report.py`, `apps/research/metrics.py`):

| Requirement | Built |
|---|---|
| CAGR, Sharpe, Sortino, Calmar next to win rate / PF | `metrics.perf` on daily equity (365-day year) |
| Walk-forward instead of one split | re-select the best-Sharpe strategy at each fold start using only the past; stitched result vs buy & hold on the same days |
| Parameter sensitivity | 27 trend_pullback variants (ADX x R:R x stop); share with positive out-of-sample Sharpe |
| Overfitting / data snooping | Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014) over every variant tried per coin |
| Regime dependence | bull / sideways / bear days from the trailing 90-day return; compounded annualized return per regime |
| Not dependent on one asset | a strategy must beat buy & hold with positive OOS Sharpe on at least 2 coins |
| Charts | one SVG equity chart per coin (no plotting dependency) |
| Checklist and ranking | 7 checks; nothing is recommended unless it passes all of them |

Found while building it: near-zero return variance produced a huge fake Sharpe (guarded); the vol-targeted
daily core rebalances ~37x/year on BTC-like volatility, about 17% of capital in fees over 4 years (now
printed in the report).

## Round 6: DXRG, "What LLM Trading Agents Actually Do in Production" (arXiv 2609.05663, 2026-10-14)

Verified on arXiv/Hugging Face listings and the authors' artifact repo (github.com/ProjectDXAI/continuous-record-llm-trading-agents):
3,505 user-funded vaults + a 500-600 agent Hyperliquid fleet; no directional edge; median leverage 5x in
every volatility band, one setting held 62% of liquidations; 43.2% of positions reached +300 bps and 49.3%
of those closed red; a fixed 2%/4% bracket beat every discretionary exit (+39 bps/position); top-3
render cutoff 1.75x; three frontier models tied on replayed decisions but differed in choice stability.
Not found in the accessible material: "71 of 205 liquidations", "25x cheaper", "research agent worth zero".

| Rule | Status here | Built |
|---|---|---|
| Hard-coded exits, not model exits | Already: stop/target set by code at entry; Jev may only tighten | MFE/MAE per position (`Position.mfe_r/mae_r`), capture gap in the review |
| Volatility-aware leverage | Spot bot sizes from stop distance (ATR) already | Futures guard: alert when leverage x 30-day daily vol > 30% of margin per day, with the leverage that fits |
| The candidate list is part of the strategy | Universe is fixed in config; research report runs several coins | none |
| Switch each tool off | Rules-only vs rules+Jev already | Ablation table in `make research`; on simulated data StoplossGuard and the cost filter changed nothing |
| Second check before the exchange | Deterministic risk engine already sits there (code, not a model) | none |
| Save exactly what the model saw | Words + answers were logged | Full numeric snapshot now logged with every decision |
| Replay on a cheaper model first | Per-model calibration existed | `make replay-models`: agreement, Brier skill, flip rate on identical input, tokens, latency |

## Round 7: what is new on GitHub and arXiv for this bot (2026-10-25)

Searched GitHub trending lists, the weekly best-of-algorithmic-trading ranking, project releases and
issues, and arXiv (abstracts read at the source). GitHub's search API is not available in this session.

| Finding | Source | Verdict / built |
|---|---|---|
| Kronos pre-training data ends **June 2024** | Kronos paper (arXiv 2508.02739, appendix D); KQSP paper (arXiv 2607.26792) | `--since` can go back to 2024-07-01; default stays 2025-09 for the first run |
| Independent Kronos tests: direction ~50-53% on crypto (1-30 min), worse than "last price" on point error, does not beat fees; fine-tuning lowers token loss but not trading results | Kronos issue #355 (incl. a crypto 15m comment, 120k+ points); sumit-ai-ml/kronos-market-eval (BTC 24h: 50/100 direction, below buy & hold); Kairos crypto fine-tune numbers quoted in zayansalman/polymarket-crypto #258 | Expect `make kronos` direction to fail; not a reason to skip the test |
| Same commenter: Kronos **uncertainty** is stable across regimes and used live for sizing; its "80%" bands hold only 53-60% | Kronos issue #355 | **Built**: `pred_std` + volatility skill vs trailing vol in `make kronos` |
| TSFMs barely beat random walk on returns (Diebold-Mariano rejects in 2 of 10 tasks); on volatility, only TTM beats Log-HAR, and an equal-weight TTM + Log-HAR average is the robust choice | arXiv 2606.27100; arXiv 2607.05291 | Vol is the realistic use. Next candidate: HAR + Kronos average for sizing |
| Review through Aug 2026: no AI architecture shown to give persistent net alpha; failure points are contamination, repeated selection, costs | arXiv 2609.04917 | Matches the tournament's rules; nothing to change |
| Bitcoin time-series momentum: slow (12-week) signals beat fast ones; dynamic speed adds little | Kang & Ryu, *Risk Management* 28(3), 2026 | Next: 84-day lookback variant in `daily_trend` (now 20) |
| Crypto TSMOM vol-targeting / Kelly overlay found null; drawdown-state overlay cut max DD to ~-28% | Howden & Andreev, SSRN 7115459 (abstract via search, SSRN blocks scripts) | Not built; the bot's vol-targeted daily core already exists |
| 6h trend-following with vol-calibrated trailing stop, Sharpe 2.41 on 150+ pairs 2022-24 | arXiv 2602.11708 (AdaptiveTrend) | Unverified, no code, long/short, many pairs: not for a 800 USDT spot bot |
| Fee-only backtests inflate perpetual results vs full cost + funding + slippage | arXiv 2512.22476 (AutoQuant) | Already: cost engine, funding in futures research |
| Chronos-2 (Apache-2.0, covariates, CPU) and TimesFM 2.5 lead generic benchmarks; TiRex has a non-Apache licence | Chronos-2 paper (arXiv 2510.15821), FinVerse (arXiv 2608.03259) | Candidate only if Kronos' vol signal is useful; Chronos-2 is the one to try |
| freqtrade 2026.9: open interest as informative data, P-value in backtests, security fixes | freqtrade releases | Open interest is a candidate filter (needs Binance futures history) |
| Order-book imbalance repos (hftbacktest, orderbook-imbalance) | GitHub | Sub-second edge; irrelevant at 15m and with maker fees on 800 USDT |
| TradingAgents v0.7, OpenAlice, OctoBot | GitHub | LLM research agents / platforms; nothing for the order path |

## Kronos on real BTC data (2026-10-26)

`make kronos`, Kronos-small, BTC/USDT 15m, 2025-09-01 → 2026-10-25 (after its June 2024 cutoff), 5,037
forecasts of the next 2h. Direction: 51.3% right out-of-sample vs 50.6% for "always up", rank IC +0.037:
a real but tiny edge. Traded through the tournament it loses at every threshold (PF 0.41-0.53, in-sample
already). Volatility: its path spread ranks the next move's size worse than plain 24h trailing volatility
(IC 0.17 vs 0.22 out-of-sample); the average of both adds 0.006. Verdict: not for entries, not for sizing.

## One 15m model over everything (2026-10-26)

`make m15`: LightGBM over every indicator, order-flow measure (cumulative delta, VWAP, OBV, breakout
volume), structure, candle pattern and classic strategy the bot knows, plus funding and BTC context; the
operator's 20 coins, Binance futures 15m, walk-forward monthly 2024-01 → 2026-10. The model does read
something: 52-54% of directions right and +3 to +10 bp per trade BEFORE costs (rank IC +0.022). After
taker fees and slippage (14 bp a round trip) every variant loses: -4 to -11 bp per trade, at most 5 of 20
coins positive, last 6 months worse, Deflated Sharpe 0%. The edge exists but is a third of the cost. Only
lever left untested: maker-only execution (~4 bp round trip), which brings missed fills and adverse
selection that a candle backtest cannot measure; it would need paper trading with real order-book fills.
