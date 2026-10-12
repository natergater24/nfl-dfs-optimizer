import numpy as np
import pytest

from nfldfs import dk_rules
from nfldfs.optimizer import InfeasibleError, solve_lineup


def _obj(pool):
    return np.array(pool.salary / 1000 * 2.4, dtype=float)  # writable copy


def _check(pool, rows, min_salary=49_000):
    lu = pool.loc[rows]
    assert dk_rules.validate_lineup(lu) == []
    assert min_salary <= lu.salary.sum() <= 50_000
    return lu


def test_valid_lineup_within_cap(pool):
    _check(pool, solve_lineup(pool, _obj(pool)))


def test_takes_an_obviously_best_player(pool):
    obj = _obj(pool)
    star = int(pool.index[pool["name"] == "CCC WR6"][0])     # $3,000 receiver
    obj[star] = 1000.0
    assert star in solve_lineup(pool, obj)


def test_locks_and_excludes(pool):
    lock = int(pool.loc[pool["name"] == "DDD TE3", "dk_id"].iloc[0])
    excl = int(pool.loc[pool["name"] == "AAA WR1", "dk_id"].iloc[0])
    lu = _check(pool, solve_lineup(pool, _obj(pool), locks=[lock], excludes=[excl]))
    assert lock in lu.dk_id.tolist() and excl not in lu.dk_id.tolist()


def test_unplayable_never_selected(pool):
    p = pool.copy()
    best = int(np.argmax(_obj(p)))
    p.loc[best, "playable"] = False
    assert best not in solve_lineup(p, _obj(p))


def test_uniqueness_against_previous(pool):
    first = solve_lineup(pool, _obj(pool))
    second = solve_lineup(pool, _obj(pool), previous=[first], min_unique=3)
    assert len(set(first) - set(second)) >= 3


def test_tournament_stack_rules(pool):
    lu = _check(pool, solve_lineup(pool, _obj(pool), stack=True))
    qb = lu[lu.position == "QB"].iloc[0]
    assert ((lu.team == qb.team) & lu.position.isin(["WR", "TE"])).sum() >= 1
    assert ((lu.team == qb.opp) & lu.position.isin(["RB", "WR", "TE"])).sum() >= 1
    dst = lu[lu.position == "DST"].iloc[0]
    assert not ((lu.position != "DST") & (lu.team == dst.opp)).any()


def test_impossible_min_salary_raises(pool):
    with pytest.raises(InfeasibleError, match="No valid lineup"):
        solve_lineup(pool, _obj(pool), min_salary=50_001)


def test_lock_of_unplayable_player_raises(pool):
    p = pool.copy()
    p.loc[0, "playable"] = False
    with pytest.raises(InfeasibleError, match="not playable"):
        solve_lineup(p, _obj(p), locks=[int(p.dk_id.iloc[0])])
