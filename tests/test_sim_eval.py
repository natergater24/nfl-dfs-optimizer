import numpy as np
import pytest

from nfldfs import dk_rules, sim_eval


def _owned(pool):
    p = pool.copy()
    p["own_pct"] = np.where(p["name"].str.endswith("1"), 30.0, 3.0)
    return p


def test_sample_field_lineups_are_valid_and_follow_ownership(pool):
    p = _owned(pool)
    field = sim_eval.sample_field(p, 300, np.random.default_rng(0))
    assert field.shape == (300, 9)
    for lu in field[:50]:
        assert dk_rules.validate_lineup(p.loc[lu]) == []
        assert 45_000 <= p.salary.to_numpy()[lu].sum() <= 50_000
    counts = np.bincount(field.ravel(), minlength=len(p))
    assert counts[p["name"] == "AAA QB1"].sum() > counts[p["name"] == "AAA QB2"].sum()


def test_lineup_scores_sum_players():
    sims = np.arange(12, dtype=np.float32).reshape(3, 4)
    s = sim_eval.lineup_scores(sims, [[0, 1], [2, 3]])
    assert s.tolist() == [[1, 5], [9, 13], [17, 21]]


def test_contest_metric_h2h_and_top_pct():
    field = np.full((100, 50), 10.0, dtype=np.float32)
    cand = np.column_stack([np.full(100, 11.0), np.full(100, 9.0)])
    assert sim_eval.contest_metric(cand, field, {"kind": "h2h"}).tolist() == [1.0, 0.0]
    field = np.tile(np.arange(100, dtype=np.float32), (10, 1))
    cand = np.column_stack([np.full(10, 99.5), np.full(10, 50.0)])
    assert sim_eval.contest_metric(cand, field, {"kind": "top_pct", "pct": 0.01}).tolist() == [1.0, 0.0]
    assert sim_eval.contest_metric(cand, field, {"kind": "top_pct", "pct": 0.5}).tolist() == [1.0, 1.0]


def _extreme(pool):
    from nfldfs import ownership
    p = pool.copy()
    p["median"] = p.salary / 1000 * 2.4
    p["own_pct"] = ownership.estimate_ownership(p)
    return p


def test_sample_field_extreme_ownership_succeeds_and_is_valid(pool):
    from nfldfs import config
    p = _extreme(pool)
    field = sim_eval.sample_field(p, 300, np.random.default_rng(0))
    sal = p.salary.to_numpy()
    for lu in field:
        assert dk_rules.validate_lineup(p.loc[lu]) == []
        assert config.FIELD_MIN_SALARY <= sal[lu].sum() <= 50_000


def test_field_ownership_sums_to_900(pool):
    p = _owned(pool)
    field = sim_eval.sample_field(p, 200, np.random.default_rng(1))
    assert sim_eval.field_ownership(p, field).sum() == pytest.approx(900)


def test_build_all_warns_on_ownership_conflict(pool, team_exp, caplog):
    import logging
    from nfldfs import lineups, ownership, simulate
    p = _extreme(pool)
    sims = simulate.simulate(p, team_exp, 200, seed=7)
    p["tier"] = p.own_pct.map(ownership.ownership_tier)
    for c in ("floor", "ceiling"):
        p[c] = p["median"] * (0.5 if c == "floor" else 1.8)
    with caplog.at_level(logging.WARNING, logger="nfldfs.lineups"):
        lineups.build_all(p, sims, n_candidates=2, field_size=100, seed=1)
    assert any(r.name == "nfldfs.lineups" for r in caplog.records)
