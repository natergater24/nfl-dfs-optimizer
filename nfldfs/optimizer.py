"""Integer-programming lineup solver. Salary cap and roster rules are hard constraints."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pulp

from .config import MIN_SALARY_DEFAULT, MIN_UNIQUE_PLAYERS, QB_STACK_MIN, SALARY_CAP
from .dk_rules import POSITION_BOUNDS, ROSTER_SLOTS
from .injuries import recommendable

_SOLVER_NAME = None


class InfeasibleError(RuntimeError):
    pass


def _solver():
    global _SOLVER_NAME
    if _SOLVER_NAME is None:
        available = pulp.listSolvers(onlyAvailable=True)
        _SOLVER_NAME = "HiGHS" if "HiGHS" in available else "PULP_CBC_CMD"
    return pulp.getSolver(_SOLVER_NAME, msg=False)


def solve_lineup(pool: pd.DataFrame, objective: np.ndarray, *, min_salary: int = MIN_SALARY_DEFAULT,
                 max_salary: int = SALARY_CAP, stack: bool = False, stack_min: int = QB_STACK_MIN,
                 locks=(), excludes=(), previous=(), min_unique: int = MIN_UNIQUE_PLAYERS) -> list[int]:
    dkid = pool.dk_id.to_numpy()
    pos, team, opp = pool.position.to_numpy(), pool.team.to_numpy(), pool.opp.to_numpy()
    sal = pool.salary.to_numpy()
    excluded = set(int(d) for d in excludes)
    # App-made picks come from recommendable players only (no D/OUT/IR, no "leans out"). A user lock wins
    # whatever the tag on an injury-aware pool; pools without injury columns keep the old playable-only rule.
    ok = recommendable(pool)
    playable = pool.playable.to_numpy(dtype=bool)
    lockable = "recommendable" in pool.columns
    locked = set(int(d) for d in locks)
    rows = [i for i in range(len(pool)) if int(dkid[i]) not in excluded
            and (ok[i] or (int(dkid[i]) in locked and (lockable or playable[i])))]

    prob = pulp.LpProblem("lineup", pulp.LpMaximize)
    x = {i: prob.add_variable(f"x_{i}", cat="Binary") for i in rows}
    prob += pulp.lpSum(float(objective[i]) * x[i] for i in rows)
    prob += pulp.lpSum(int(sal[i]) * x[i] for i in rows) <= max_salary
    prob += pulp.lpSum(int(sal[i]) * x[i] for i in rows) >= min_salary
    prob += pulp.lpSum(x.values()) == len(ROSTER_SLOTS)
    for p, (lo, hi) in POSITION_BOUNDS.items():
        terms = [x[i] for i in rows if pos[i] == p]
        if len(terms) < lo:
            raise InfeasibleError(f"Not enough playable {p}s on this slate to build a lineup")
        prob += pulp.lpSum(terms) >= lo
        prob += pulp.lpSum(terms) <= hi
    for d in locks:
        match = [i for i in rows if int(dkid[i]) == int(d)]
        if not match:
            raise InfeasibleError(f"Locked player {d} is not playable on this slate (injured, excluded or not listed)")
        prob += x[match[0]] == 1
    for prev in previous:
        prob += pulp.lpSum(x[i] for i in prev if i in x) <= len(ROSTER_SLOTS) - min_unique
    if stack:
        for q in (i for i in rows if pos[i] == "QB"):
            mates = [x[i] for i in rows if team[i] == team[q] and pos[i] in ("WR", "TE")]
            bring_back = [x[i] for i in rows if team[i] == opp[q] and pos[i] in ("RB", "WR", "TE")]
            prob += pulp.lpSum(mates) >= stack_min * x[q]
            prob += pulp.lpSum(bring_back) >= x[q]
        for d in (i for i in rows if pos[i] == "DST"):
            for i in rows:
                if pos[i] != "DST" and team[i] == opp[d]:
                    prob += x[d] + x[i] <= 1

    status = prob.solve(_solver()).status_str  # PuLP 4 removed pulp.LpStatus
    if status != "Optimal":
        raise InfeasibleError(f"No valid lineup exists under these rules (solver status: {status}). "
                              "Loosen locks, excludes or the minimum salary.")
    return sorted(i for i in rows if x[i].value() is not None and x[i].value() > 0.5)
