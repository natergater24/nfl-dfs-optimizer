import numpy as np
import pandas as pd
import pytest

from nfldfs import ownership


def _projected(pool):
    p = pool.copy()
    p["median"] = p.salary / 1000 * 2.4
    return p


def test_position_totals_match_roster_slots_and_cap(pool):
    p = _projected(pool)
    own = ownership.estimate_ownership(p)
    sums = own.groupby(p.position).sum()
    for pos, total in ownership.SLOT_TOTALS.items():
        assert sums[pos] == pytest.approx(total, rel=1e-6)
    assert own.max() <= ownership.MAX_OWN + 1e-9
    assert sum(ownership.SLOT_TOTALS.values()) == pytest.approx(900)


def test_better_value_is_more_owned(pool):
    p = _projected(pool)
    a = p.index[(p.team == "AAA") & (p["name"] == "AAA WR3")][0]
    b = p.index[(p.team == "AAA") & (p["name"] == "AAA WR4")][0]
    p.loc[a, "median"] = p.loc[b, "median"] = 14.0      # same projection, a costs $1,000 more
    own = ownership.estimate_ownership(p)
    assert own[b] > own[a]


def test_unplayable_players_have_zero_ownership(pool):
    p = _projected(pool)
    p.loc[0, "playable"] = False
    assert ownership.estimate_ownership(p)[0] == 0.0


@pytest.mark.parametrize("pct,tier", [(60, "Chalk"), (25.0, "Chalk"), (24.9, "Popular"), (10.0, "Popular"),
                                      (9.99, "Moderate"), (5.0, "Moderate"), (4.99, "Contrarian"), (0.0, "Contrarian")])
def test_ownership_tiers(pct, tier):
    assert ownership.ownership_tier(pct) == tier


def _history(weeks=3, n=30, seed=0):
    rng = np.random.default_rng(seed)
    parts = []
    for w in range(weeks):
        sal = rng.integers(30, 90, n) * 100
        med = rng.uniform(5, 20, n)
        h = pd.DataFrame({"slate_date": f"2026-10-{11 + 7 * w:02d}", "position": "WR", "salary": sal,
                          "median": med, "implied_total": rng.uniform(18, 28, n), "opp_implied": 22.0})
        value = med / (sal / 1000)
        h["actual_own"] = np.exp(1.5 * (value - value.mean()) / value.std()) * 5      # value drives ownership
        parts.append(h)
    return pd.concat(parts, ignore_index=True)


def test_estimate_without_model_matches_heuristic(pool):
    p = _projected(pool)
    assert ownership.estimate_ownership(p).equals(ownership.estimate_ownership(p, None))


def test_fit_needs_three_weeks():
    assert ownership.fit_ownership_model(_history(weeks=2)) is None


def test_fit_learns_value_effect_and_model_keeps_totals(pool):
    model = ownership.fit_ownership_model(_history())
    assert model["weeks"] == 3 and "WR" in model["coef"]
    b = model["coef"]["WR"]
    assert len(b) == 4 and b[1] > 1.0                          # strong positive z_value coefficient
    p = _projected(pool)
    own = ownership.estimate_ownership(p, model)
    sums = own.groupby(p.position).sum()
    for pos, total in ownership.SLOT_TOTALS.items():
        assert sums[pos] == pytest.approx(total, rel=1e-6)    # positions without a model use the heuristic


def test_ownership_features_zero_for_unplayable(pool):
    p = _projected(pool)
    p.loc[0, "playable"] = False
    f = ownership.ownership_features(p)
    assert list(f.columns) == list(ownership.FEATURES) and (f.loc[0] == 0).all()
