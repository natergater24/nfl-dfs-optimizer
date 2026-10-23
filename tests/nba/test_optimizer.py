import numpy as np
import pandas as pd
import pytest

from nbadfs import optimizer as OPT
from nbadfs.rules import ROSTER_SLOTS, validate_lineup
from nfldfs.optimizer import InfeasibleError as NFLInfeasible

from .slate_fixture import player, slate_pool


def _check(pool, ids):
    players = pool.set_index("dk_id").loc[ids].reset_index()
    assert validate_lineup(players, list(ROSTER_SLOTS)) == []
    return players


def test_slot_assignment_multi_eligible_and_two_games():
    # Stars: 2 PGs, 3 SG/SFs, 1 PF, 2 Cs -> one SG/SF has to play F (and both PGs fill PG + G).
    stars = [("PG", "A1"), ("PG", "H1"), ("SG/SF", "A1"), ("SG/SF", "H1"), ("SG/SF", "A2"),
             ("PF", "H2"), ("C", "A1"), ("C", "H2")]
    opp = {"A1": "H1", "H1": "A1", "A2": "H2", "H2": "A2"}
    game = {"A1": "A1@H1", "H1": "A1@H1", "A2": "A2@H2", "H2": "A2@H2"}
    rows = [player(i, f"Star{i}", t, opp[t], game[t], pos, 5000, 60.0) for i, (pos, t) in enumerate(stars)]
    for i, pos in enumerate(["PG", "SG", "SF", "PF", "C", "PG/SG", "SF/PF", "SG"] * 2):
        t = ["A1", "H1", "A2", "H2"][i % 4]
        rows.append(player(100 + i, f"Bench{i}", t, opp[t], game[t], pos, 4000, 10.0))
    pool = pd.DataFrame(rows)
    ids = OPT.solve_lineup(pool, pool["median"].to_numpy(), min_salary=0)
    assert sorted(ids) == list(range(8))
    players = _check(pool, ids)
    assert players.loc[ROSTER_SLOTS.index("F"), "positions"] == "SG/SF"
    assert set(players.loc[[0, 5], "positions"]) == {"PG"}       # PG and G slots

    one_game = pool[pool["game"] == "A1@H1"].reset_index(drop=True)
    with pytest.raises(OPT.InfeasibleError, match="2 games"):
        OPT.solve_lineup(one_game, one_game["median"].to_numpy(), min_salary=0)
    assert OPT.InfeasibleError is NFLInfeasible
    three_centers = [["C", "UTIL"]] * 3 + [["PG", "G", "UTIL"]] * 5
    assert OPT.assign_slots(three_centers) is None


def test_locks_excludes_uniqueness():
    pool = slate_pool()
    obj = pool["median"].to_numpy()
    best = OPT.solve_lineup(pool, obj)
    _check(pool, best)
    assert 49_000 <= pool.set_index("dk_id").loc[best, "salary"].sum() <= 50_000
    cheap = int(pool.loc[pool["median"].idxmin(), "dk_id"])
    locked = OPT.solve_lineup(pool, obj, locks=[cheap])
    assert cheap in locked
    _check(pool, locked)
    ex = OPT.solve_lineup(pool, obj, excludes=[best[0], best[1]])
    assert best[0] not in ex and best[1] not in ex
    second = OPT.solve_lineup(pool, obj, previous=[set(best)], min_unique=3)
    assert len(set(second) - set(best)) >= 3
    _check(pool, second)
    with pytest.raises(OPT.InfeasibleError):
        OPT.solve_lineup(pool, obj, locks=[999_999])
    with pytest.raises(OPT.InfeasibleError):
        OPT.solve_lineup(pool, obj, locks=[cheap], excludes=[cheap])
    with pytest.raises(OPT.InfeasibleError):
        OPT.solve_lineup(pool, obj, min_salary=50_001)
