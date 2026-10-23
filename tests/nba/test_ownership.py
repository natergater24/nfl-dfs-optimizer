import numpy as np
import pandas as pd

from nbadfs import ownership as O
from nbadfs.config import MIN_GAMES, SALARY_CAP
from nbadfs.rules import ROSTER_SLOTS, validate_lineup
from nfldfs.ownership import ownership_tier

from .slate_fixture import ready_pool, slate_pool


def test_ownership_sums_and_caps():
    pool = slate_pool()
    pool.loc[3, ["playable", "status", "median"]] = [False, "O", 0.0]
    pool.loc[5, "median"] = 200.0            # absurd value -> would exceed the cap without capping
    own = O.estimate_ownership(pool)
    playable = pool["playable"].to_numpy()
    assert abs(own[playable].sum() - 800.0) < 0.5
    assert own.max() <= 70.0 + 1e-9 and own[5] == 70.0
    assert own[3] == 0.0
    out = O.add_ownership(pool)
    assert list(out["own_pct"]) == list(own)
    assert all(t == ownership_tier(p) for t, p in zip(out["tier"], out["own_pct"]))
    assert "own_pct" not in pool


def test_field_lineups_legal():
    pool, _ = ready_pool(slate_pool())
    pool.loc[0, "playable"] = False
    field = O.sample_field(pool, 300, np.random.default_rng(3))
    assert field.shape == (300, len(ROSTER_SLOTS)) and np.issubdtype(field.dtype, np.integer)
    for lu in field:
        players = pool.iloc[lu]
        assert validate_lineup(players, list(ROSTER_SLOTS)) == []
        assert players["playable"].all() and players["salary"].sum() <= SALARY_CAP
        assert players["game"].nunique() >= MIN_GAMES
    counts = np.bincount(field.ravel(), minlength=len(pool))
    hi, lo = pool["own_pct"].idxmax(), pool.loc[pool.playable, "own_pct"].idxmin()
    assert counts[hi] > counts[lo]                    # draws follow ownership
    assert counts[0] == 0
    again = O.sample_field(pool, 300, np.random.default_rng(3))
    assert np.array_equal(field, again)
