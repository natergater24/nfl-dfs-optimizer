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
