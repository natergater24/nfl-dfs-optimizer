import numpy as np
import pytest

from nfldfs import simulate


def _col(pool, team, name):
    return int(pool.index[(pool.team == team) & (pool["name"] == f"{team} {name}")][0])


def test_shape_dtype_and_determinism(pool, team_exp):
    a = simulate.simulate(pool, team_exp, 500, seed=1)
    b = simulate.simulate(pool, team_exp, 500, seed=1)
    assert a.shape == (500, len(pool)) and a.dtype == np.float32
    assert np.array_equal(a, b) and np.isfinite(a).all()


def test_starter_qb_scores_and_correlates_with_own_receiver(pool, team_exp):
    sims = simulate.simulate(pool, team_exp, 4000, seed=2)
    qb1, qb2 = _col(pool, "AAA", "QB1"), _col(pool, "AAA", "QB2")
    wr1, other_wr1 = _col(pool, "AAA", "WR1"), _col(pool, "CCC", "WR1")
    assert 12 < sims[:, qb1].mean() < 30
    assert sims[:, qb2].min() == 0 and sims[:, qb2].max() == 0     # backup with no role scores exactly 0
    assert np.corrcoef(sims[:, qb1], sims[:, wr1])[0, 1] > 0.2
    assert abs(np.corrcoef(sims[:, qb1], sims[:, other_wr1])[0, 1]) < 0.1


def test_backup_qb_throws_when_starter_out(pool, team_exp):
    p = pool.copy()
    p.loc[_col(p, "AAA", "QB1"), "playable"] = False
    sims = simulate.simulate(p, team_exp, 2000, seed=3)
    assert sims[:, _col(p, "AAA", "QB1")].max() == 0
    assert sims[:, _col(p, "AAA", "QB2")].mean() > 10


def test_dst_scores_are_plausible(pool, team_exp):
    sims = simulate.simulate(pool, team_exp, 2000, seed=4)
    d = sims[:, _col(pool, "AAA", "DST1")]
    assert -4 <= d.min() and 3 < d.mean() < 12


def test_missing_team_expectations_raise(pool, team_exp):
    with pytest.raises(KeyError, match="DDD"):
        simulate.simulate(pool, team_exp.drop(index="DDD"), 10, seed=0)


def test_summarize_orders_percentiles(pool, team_exp):
    sims = simulate.simulate(pool, team_exp, 2000, seed=5)
    s = simulate.summarize(sims, pool)
    assert list(s.columns) == ["mean", "floor", "median", "ceiling", "boom_rate"]
    assert (s.floor <= s["median"]).all() and (s["median"] <= s.ceiling).all()
    assert s.boom_rate.between(0, 1).all()
