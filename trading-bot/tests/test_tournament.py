from apps.backtest.tournament import param_grid, run_tournament
from tests.helpers import synthetic_15m


def test_no_candidate_survives_on_edgeless_data():
    """576 variants across 3 random walks produced zero passes; keep a cheap version as a guard."""
    df = synthetic_15m(n=20000, drift=0.0, vol=0.0035, seed=101, start=60000)
    grid = dict(list(param_grid().items())[::8])          # 24 variants
    res = run_tournament(df, "BTC/USDT", grid)
    assert not any(r.passed_oos for r in res)
    assert all(r.oos_rep is None for r in res if not r.passed_is)   # OOS is only spent on IS passes
