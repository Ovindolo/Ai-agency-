.PHONY: test paper paper-once replay backtest tournament live

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
