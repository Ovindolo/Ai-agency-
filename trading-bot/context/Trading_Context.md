# Trading Context

Filled in through the interview, one question at a time. The bot reads this; it never edits it.
Changes to strategy or risk come from here, with the operator's approval — never from a single trade.

## Operator
| # | Question | Answer | Date |
|---|---|---|---|
| 1 | Have you traded manually? | Yes, and still does | 2026-09-25 |
| 2 | How do you trade now? | Futures, by own admission without knowing them well; follows signals from several paid premium futures groups | 2026-09-25 |
| 2b | Style | 15m chart, holds a few hours; closes "when profit is good" (no fixed target); entries from trend lines, intuition, news on X/Twitter | 2026-09-25 |

## What maps onto the bot
- 15m chart, hours-long holds: same timeframe and horizon as trend_pullback. Good fit.
- Trend lines: partly codable (trend + pullback already; swing-line breaks could be a tournament candidate).
- Intuition, X/Twitter news: not codable and deliberately excluded (spec: no scraping X into entries).
- "Close when profit is good": discretionary exit. The bot uses fixed stop/target/trailing so results can be measured.

## Open questions
- Stop-loss habit: set from the start, or wait for a losing trade to come back?
- Net result of the group signals after fees, funding and subscriptions? Tracked or not?
- Leverage used; biggest single loss.
- Idea to propose: a signal journal (operator forwards group signals, bot paper-tracks them with fees) — measures the groups, never trades them.
- Capital, max acceptable loss, schedule, exchange, Telegram setup (the 5 setup answers).
