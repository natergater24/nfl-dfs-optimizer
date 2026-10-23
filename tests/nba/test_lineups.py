import numpy as np
import pandas as pd

from nbadfs import lineups as L
from nbadfs.config import NBA_CONTEST_TYPES, SALARY_CAP
from nbadfs.ownership import sample_field
from nbadfs.rules import ROSTER_SLOTS, validate_lineup

from .slate_fixture import ready_pool, slate_pool


def _legal(pool, ids):
    players = pool.set_index("dk_id").loc[list(ids)].reset_index()
    return validate_lineup(players, list(ROSTER_SLOTS)) == []


def _setup(out_best=False):
    pool, sims = ready_pool(slate_pool())
    if out_best:
        star = int(pool["median"].idxmax())
        pool.loc[star, ["playable", "status"]] = [False, "O"]
        pool, sims = ready_pool(pool.drop(columns=["own_pct", "tier"]))
    field = sample_field(pool, 300, np.random.default_rng(5))
    return pool, sims, field


def test_out_player_excluded_but_lock_wins_with_flag():
    pool, sims, field = _setup(out_best=True)
    out_row = pool[~pool["playable"]].iloc[0]
    out_id = int(out_row["dk_id"])
    lineups, swaps = L.build_all(pool, sims, field, n_candidates=4)
    assert out_id not in set(lineups["dk_id"]) and out_id not in set(swaps["in_id"])
    contest = NBA_CONTEST_TYPES["tournament"]
    ids, metric = L.best_lineup(pool, sims, field, contest, locks=[out_id], n_candidates=4)
    assert out_id in ids and len(ids) == 8 and _legal(pool, ids) and 0.0 <= metric <= 1.0
    warn = L.out_lock_warnings(pool, [out_id, int(pool.loc[pool.playable, "dk_id"].iloc[0])])
    assert warn == [f"⚠ {out_row['name']} is listed Out"]
    assert L.out_lock_warnings(pool, []) == []


def test_build_all_shapes():
    pool, sims, field = _setup()
    lineups, swaps = L.build_all(pool, sims, field, n_candidates=4)
    assert list(lineups.columns) == ["contest_key", "rank", "slot", "dk_id", "metric"]
    assert list(swaps.columns) == ["contest_key", "out_id", "in_id", "delta"]
    assert set(lineups["contest_key"]) == set(NBA_CONTEST_TYPES)
    by_id = pool.set_index("dk_id")
    for key, g in lineups.groupby("contest_key"):
        assert 1 <= g["rank"].nunique() <= 3
        for rank, lu in g.groupby("rank"):
            assert list(lu["slot"]) == list(ROSTER_SLOTS)
            assert lu["metric"].nunique() == 1
            assert _legal(pool, lu["dk_id"])
        metrics = g.groupby("rank")["metric"].first()
        assert metrics.is_monotonic_decreasing
        rec = g[g["rank"] == 0]
        sw = swaps[swaps["contest_key"] == key]
        assert len(sw) <= 5 and sw["delta"].is_monotonic_decreasing
        for _, s in sw.iterrows():
            ids = [s["in_id"] if d == s["out_id"] else d for d in rec["dk_id"]]
            assert s["out_id"] in set(rec["dk_id"]) and s["in_id"] not in set(rec["dk_id"])
            assert _legal(pool, ids)                  # same slot, under the cap, >= 2 games
            assert by_id.loc[ids, "salary"].sum() <= SALARY_CAP
    assert len(swaps) > 0
    again, _ = L.build_all(pool, sims, field, n_candidates=4)
    pd.testing.assert_frame_equal(lineups, again)


def test_swap_delta_is_metric_change():
    pool, sims, field = _setup()
    lineups, swaps = L.build_all(pool, sims, field, contest_types={"tournament": NBA_CONTEST_TYPES["tournament"]},
                                 n_candidates=3)
    from nfldfs.sim_eval import contest_metric, lineup_scores
    rec = list(lineups[lineups["rank"] == 0]["dk_id"])
    s = swaps.iloc[0]
    new = [s["in_id"] if d == s["out_id"] else d for d in rec]
    fs = lineup_scores(sims, field)
    m = contest_metric(lineup_scores(sims, [L.to_rows(pool, rec), L.to_rows(pool, new)]), fs,
                       NBA_CONTEST_TYPES["tournament"]["metric"])
    assert abs(s["delta"] - (m[1] - m[0])) < 1e-9
