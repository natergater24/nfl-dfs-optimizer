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
