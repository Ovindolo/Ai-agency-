.PHONY: test paper paper-once replay backtest tournament live fees daily audit review leverage carry tournament-context journal guard export-training research

test:            ## all tests
	python -m pytest -q

paper:           ## paper trading on live market data, virtual money, every 15m
	python -m apps.trader.paper

paper-once:      ## one paper tick (for cron)
	python -m apps.trader.paper --once

replay:          ## 30 days of SIMULATED market through the full bot (demo, writes runs/)
	python -m apps.trader.paper --replay simulated --days 30

backtest:        ## rules-only vs rules+recorded-Jev on downloaded history
	python -m apps.backtest.run --download

tournament:      ## import community strategies, reject lookahead, in/out-of-sample ranking
	python -m apps.backtest.tournament_run

live:            ## intentionally locked: no live order path exists yet
	@echo "LIVE este blocat. Nu există cale de ordine reale; vezi docs/LIVE_CHECKLIST.md." && exit 1

fees:            ## real maker/taker fees of YOUR account (read-only key in .env) -> data/fees.json
	python -m apps.trader.fees

daily:           ## daily trend core vs buy-and-hold vs weekly DCA, ~6 years of BTC/ETH
	python -m apps.strategy.daily_trend

audit:           ## audit paid signal groups: make audit CSV=context/semnale.csv FEE=30
	python -m apps.audit.signals $(CSV) --fetch --fee $(or $(FEE),0)

review:          ## write context/Learnings.md from the paper log now
	python -m apps.review.learn

leverage:        ## Monte Carlo on real BTC days: what 1x..50x leverage does to 500 in a year
	python -m apps.research.leverage --symbol BTC/USDT

carry:           ## funding carry (long spot + short perp) on real funding history, per year vs cash
	python -m apps.research.carry --symbol BTC/USDT:USDT

tournament-context: ## tournament + funding-crowding and Fear&Greed filters (needs internet)
	python -m apps.backtest.tournament_run --context

journal:         ## your futures journal from Binance (read-only key): deposits vs profit, fees, win rate, luck test
	set -a; [ -f .env ] && . ./.env; set +a; python -m apps.futures.journal --days 90

guard:           ## watch your manual futures positions, Telegram alerts (no stop, leverage, risk, liquidation, daily loss)
	set -a; [ -f .env ] && . ./.env; set +a; python -m apps.futures.guard

export-training: ## logged states + outcomes -> data/train_*.jsonl for a Jev-like model (jevlike format)
	python -m apps.review.export_training

research:        ## full research report: 8 strategies x BTC/ETH/SOL, OOS, walk-forward, sensitivity, Deflated Sharpe, regimes
	python -m apps.research.report --symbols BTC/USDT,ETH/USDT,SOL/USDT --download
