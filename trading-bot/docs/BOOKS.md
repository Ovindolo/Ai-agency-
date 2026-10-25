# What the operator's trading library says, and what of it is testable (2026-10-25)

Read from the PDFs the operator shared (the files themselves stay out of git). Rules are paraphrased;
"Built" points to the code that turns a rule into a backtest.

## The books

| Book | What it teaches | Testable rules | Built |
|---|---|---|---|
| Matov, *The Ultimate Price Action Trading Guide* (2019) | S/R, supply & demand zones, pin bar, engulfing, inside bar, wedges, RSI/MACD | Pin bar: tail ≥ 2× body, after a counter move, enter on the break, stop at the tail, target ≥ 2× its length. Engulfing: continuation only after a pullback in trend. Inside bar: continuation in trend away from S/R. Zones: base before a sharp move, enter mid-zone, stop beyond, 1:3. Use 1h+, best 4h/daily | `apps/pa/setups.py`: `pin_bar`, `pin_bar_at_level`, `engulfing_in_trend`, `inside_bar_in_trend`, `supply_demand_zone` |
| *5 Supply and Demand Rules You Need To Know* | Which zones to trade | (1) Strength comes from the move BEFORE the zone. (2) First touch only. (3) Trend of the time frame you trade (last HH/LL), not the daily. (4) Avoid rally-base-rally / drop-base-drop. (5) No old zones | `supply_demand_5rules` (rules 1, 2, 4, 5; rule 3 read literally rejects almost every reversal zone, see docstring) |
| *Supply and Demand Ebook* | Same zones, candlestick confirmation (hammer, shooting star) | Covered by the two above | — |
| Wade FX, *Market Structure and Powerful Setups* | Expansion/retracement legs, break of market structure (BMS), optimal trade entry (OTE) at the 0.62-0.79 retracement after a BMS | BMS + retracement to 0.618-0.786 of the break leg | Not yet: next candidate |
| *Top 12 Candlesticks* | 12 patterns with prior trend, reliability, confirmation | Each pattern is a mechanical rule; the book rates most as needing confirmation | Engulfing and hammer/pin covered |
| *Big Book of Chart Patterns* | ~40 patterns: type, entry at breakout, target = pattern height | Height-projection targets | — |
| Bulkowski, *Encyclopedia of Chart Patterns* (2nd ed., 2005) | Statistics on thousands of US-stock patterns, daily bars, 1991-2004, bull and bear markets | See below | — |
| Al Brooks, *Trading Price Action: Trading Ranges* | Bar-by-bar reading of ranges, breakouts and failed breakouts on the 5-minute E-mini | Mostly discretionary; core claim: most breakouts of a trading range fail | — |
| Swing Trader Society lessons: *Risk Management*, *Psychology* | Risk 1-3% per trade (2% default), size from the stop distance, reward > risk, journal everything | Already the bot's rules: 1% risk, size from stop, stops always on | `config/risk.yaml`, `apps/risk/engine.py` |

## Bulkowski's numbers, read honestly

87 "Results Snapshot" tables parsed (pattern, breakout direction, bull/bear market). Across them, in a
bull market:

- **Break-even failure rate** (breakout fails to move 5%): mostly **2-20%**; best: high-and-tight flag 0%,
  flags and pennants 2-4%, reversal and rounding bottoms 2-5%.
- **Average rise after an upward breakout**: mostly **25-45%** (high-and-tight flag 69%).

Two things make these numbers far rosier than what a trader gets:

1. The rise is measured from the breakout to the **ultimate high**, the top before a 20% reversal, known
   only in hindsight. No exit rule captures it; a fixed target captures a fraction.
2. The data are **US stocks, daily, 1991-2004**, no costs, no leverage. Crypto on 1h-4h with futures
   costs and funding is a different market; nothing here says the edge transfers.

The useful takeaway is relative: patterns with tight, well-defined breakouts (flags, pennants, double and
rounding bottoms) fail least, and wide, ragged ones (scallops, broadening, rising wedges) fail most. Our
own backtest is the place to check whether that ranking survives on crypto.

## Results on the operator's own data (2026-10-25)

**Price action from the books** (`make pa`, 20 coins, Binance futures 1h/4h, 2022-10/2026): every setup
loses after costs, in-sample and on unseen 2025-26 data. A first run showed supply/demand zones at
+0.2-0.3 R; that came from the simulator counting a target on the same bar a resting limit order filled
(the bar's high may come before the fill). With stop-or-nothing on the fill bar, zones lose too
(1h: -0.29 R in-sample, -0.24 R unseen, positive on 4 of 20 coins, negative every year).

**The group admin's buy-zone calls** (`apps/audit/zone_calls.py`, Telegram export 2019-07 → 2022-01):
157 structured calls, 111 filled. 84% reached target 1 (median +9%, ~4 days), but 31% first fell 20% or
more, and the median return was -2% after 30 days, -5% after 90. Baseline: the same coins entered 1-10
days after each post, same target distance: 88% reached it, mean +4.6% vs the calls' +2.7% (sell at T1, no
stop); with a -20% stop 72% vs 69%. The calls do no better than entering the same coins at another time:
in 2019-21 the coins rose, the timing added nothing measurable.
