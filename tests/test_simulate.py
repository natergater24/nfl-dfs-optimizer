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


def test_allocated_tds_never_exceed_team_tds_and_track_weights():
    rng = np.random.default_rng(7)
    n = 20000
    team_tds = rng.poisson(2.0, n)
    draw = np.tile([0.4, 0.3, 0.2], (n, 1))
    rest = np.full(n, 0.1)
    weights = np.array([1.0, 1.0, 2.0])
    out = simulate._allocate_tds(rng, team_tds, draw, rest, weights)
    assert out.shape == (n, 3)
    assert (out.sum(axis=1) <= team_tds).all()
    w = draw[0] * weights
    expected = team_tds.mean() * w / (w.sum() + 0.1)
    assert np.allclose(out.mean(axis=0), expected, rtol=0.05)


def test_game_and_dst_correlations(pool, team_exp):
    sims = simulate.simulate(pool, team_exp, 4000, seed=2)
    a_qb, b_qb = _col(pool, "AAA", "QB1"), _col(pool, "BBB", "QB1")
    a_dst = _col(pool, "AAA", "DST1")
    c_qb = np.corrcoef(sims[:, a_qb], sims[:, b_qb])[0, 1]
    c_dst = np.corrcoef(sims[:, a_dst], sims[:, b_qb])[0, 1]
    print("qb-qb", c_qb, "dst-oppqb", c_dst)
    assert c_qb > 0.05
    assert c_dst < -0.1


def test_questionable_sits_in_15pct_of_sims(pool, team_exp):
    from nfldfs import config
    j = _col(pool, "AAA", "WR1")
    raw = simulate.simulate(pool, team_exp, 10_000, seed=3)           # no play_prob column: untouched
    p = pool.copy()
    p["play_prob"] = 1.0
    p.loc[j, "play_prob"] = config.Q_PLAY_PROB
    a = simulate.simulate(p, team_exp, 10_000, seed=3)
    b = simulate.simulate(p, team_exp, 10_000, seed=3)
    assert np.array_equal(a, b)                                        # seeded: same build, same sims
    others = np.arange(len(p)) != j
    assert np.array_equal(a[:, others], raw[:, others])                # everyone else unchanged
    sat = a[:, j] != raw[:, j]
    assert (a[sat, j] == 0).all()
    played = raw[:, j] > 0
    assert (sat[played].mean()) == pytest.approx(1 - config.Q_PLAY_PROB, abs=0.015)
    c = simulate.simulate(p, team_exp, 10_000, seed=4)
    assert not np.array_equal(c[:, j] == 0, a[:, j] == 0)              # a different seed sits different sims


def test_play_prob_zero_and_one(pool, team_exp):
    j, k = _col(pool, "AAA", "WR1"), _col(pool, "BBB", "WR1")
    p = pool.copy()
    p["play_prob"] = 1.0
    p.loc[j, "play_prob"] = 0.0
    a = simulate.simulate(p, team_exp, 500, seed=1)
    raw = simulate.simulate(pool, team_exp, 500, seed=1)
    assert (a[:, j] == 0).all() and np.array_equal(a[:, k], raw[:, k])
