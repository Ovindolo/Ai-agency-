# Backtest — BTC/USDT · B · rules + recorded Jev

**Verdict: FAIL** (buy-and-hold comparison is reported, not gated)

| Metric | Value |
|---|---|
| Bars | 34820 |
| Signals | 227 |
| Vetoed by policy | 0 |
| Vetoed by risk | 0 |
| Jev answers available | 0% of signals |
| Trades | 227 |
| Win rate | 48.5% |
| Avg win / avg loss | +2.22 / -2.08 |
| Net P&L after fees | +0.47 (+0.09%) |
| Fees paid | 45.90 |
| Profit factor | 1.00 |
| Max drawdown | 6.2% |
| **Buy-and-hold, same bars** | **+432.12%** (max DD 40.7%) |

| Gate | Result | Value |
|---|---|---|
| profit_factor >= 1.2 | FAIL | 1.00 |
| max drawdown <= 20% | PASS | 6.2% |
| trades >= 80 | PASS | 227 |
| not owned by top 3 trades | FAIL | net without top 3: -9.96 |
| beats buy-and-hold | FAIL | +0.1% vs +432.1% |

> **No recorded Jev answers yet.** B equals A until the paper runner has logged real answers. That is by design: Jev is never simulated in a backtest.
