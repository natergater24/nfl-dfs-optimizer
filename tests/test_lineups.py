import numpy as np
import pytest

from nfldfs import config, dk_rules, lineups, ownership, simulate


@pytest.fixture
def projected(pool, team_exp):
    sims = simulate.simulate(pool, team_exp, 400, seed=7)
    p = pool.join(simulate.summarize(sims, pool))
    p["own_pct"] = ownership.estimate_ownership(p)
    p["tier"] = p.own_pct.map(ownership.ownership_tier)
    return p, sims


def test_objective_values(projected):
    p, _ = projected
    v = lineups.objective_values(p, {"ceiling": 1.0, "own_penalty": 0.3})
    assert np.allclose(v, p.ceiling - 0.3 * p.own_pct)


def test_candidates_are_distinct_and_valid(projected):
    p, sims = projected
    c = lineups.generate_candidates(p, sims, config.CONTEST_TYPES["tournament"], 4, np.random.default_rng(0))
    assert len(c) == 4
    for i, a in enumerate(c):
        assert dk_rules.validate_lineup(p.loc[a]) == []
        for b in c[:i]:
            assert len(set(a) - set(b)) >= config.MIN_UNIQUE_PLAYERS


def test_build_all_covers_every_contest_type(projected):
    p, sims = projected
    lus, swaps = lineups.build_all(p, sims, n_candidates=3, field_size=150, seed=1)
    assert list(lus.columns) == lineups.LINEUP_COLUMNS
    assert set(lus.contest_key) == set(config.CONTEST_TYPES)
    for key, g in lus[lus["rank"] == 0].groupby("contest_key"):
        assert len(g) == 9 and list(g.slot) == list(dk_rules.ROSTER_SLOTS)
        assert dk_rules.validate_lineup(g) == [] and g.total_salary.iloc[0] <= 50_000
        assert g.metric.between(0, 1).all()
        if config.CONTEST_TYPES[key]["stack"]:
            qb = g[g.position == "QB"].iloc[0]
            assert ((g.team == qb.team) & g.position.isin(["WR", "TE"])).any()
    assert list(swaps.columns) == ["contest_key"] + lineups.SWAP_COLUMNS


def test_swaps_respect_cap_position_and_ownership(projected):
    p, sims = projected
    lus, swaps = lineups.build_all(p, sims, n_candidates=3, field_size=150, seed=1)
    assert (swaps.remaining_salary >= 0).all()
    pos = dict(zip(p.dk_id, p.position))
    assert all(pos[a] == pos[b] for a, b in zip(swaps.out_dk_id, swaps.in_dk_id))
    for key, g in swaps.groupby("contest_key"):
        rec = set(lus[(lus.contest_key == key) & (lus["rank"] == 0)].dk_id)
        assert not set(g.in_dk_id) & rec and set(g.out_dk_id) <= rec
        assert len(g) <= config.N_SWAPS
        if config.CONTEST_TYPES[key]["group"] == "Tournament":
            assert (g.in_own_pct < config.SWAP_MAX_OWN_TOURNAMENT).all()
