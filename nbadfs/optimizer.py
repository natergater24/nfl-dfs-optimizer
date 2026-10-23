"""NBA Classic lineup MILP: picks 8 players AND assigns each to a roster slot in one solve."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pulp

from nfldfs.optimizer import InfeasibleError, _solver

from .config import MIN_GAMES, MIN_SALARY_DEFAULT, MIN_UNIQUE_PLAYERS, SALARY_CAP
from .rules import ROSTER_SLOTS

__all__ = ["InfeasibleError", "assign_slots", "solve_lineup"]


def solve_lineup(pool: pd.DataFrame, objective: np.ndarray, *, min_salary: int = MIN_SALARY_DEFAULT,
                 max_salary: int = SALARY_CAP, locks=(), excludes=(), previous=(),
                 min_unique: int = MIN_UNIQUE_PLAYERS) -> list[int]:
    """Best lineup as 8 dk_ids in ROSTER_SLOTS order. `objective` is aligned with pool rows.
    Locks force a player in even when he is not playable (the user's lock wins); `previous` is an
    iterable of dk_id collections, each of which the new lineup must differ from by >= `min_unique`."""
    dkid = pool["dk_id"].to_numpy().astype(np.int64)
    sal = pool["salary"].to_numpy().astype(int)
    playable = pool["playable"].to_numpy(dtype=bool)
    games = pool["game"].to_numpy()
    slots_of = list(pool["slots"])
    lock_ids = {int(d) for d in locks}
    excluded = {int(d) for d in excludes}
    both = lock_ids & excluded
    if both:
        raise InfeasibleError(f"Player(s) {sorted(both)} are both locked and excluded — pick one")
    missing = lock_ids - set(dkid.tolist())
    if missing:
        raise InfeasibleError(f"Locked player(s) {sorted(missing)} are not on this slate")
    rows = [i for i in range(len(pool))
            if int(dkid[i]) in lock_ids or (playable[i] and int(dkid[i]) not in excluded)]
    n_games = len({games[i] for i in rows})
    if n_games < MIN_GAMES:
        raise InfeasibleError(f"A lineup needs players from at least {MIN_GAMES} games, but only {n_games} "
                              f"game(s) have available players")

    # z[i] = player i is in the lineup (binary). x[i, s] = player i fills slot s; for fixed z the slot
    # assignment is a bipartite matching (integral polytope), so x can stay continuous and HiGHS only
    # branches on players (about 2x faster than binary x, which has many equivalent slot permutations).
    prob = pulp.LpProblem("nba_lineup", pulp.LpMaximize)
    cand = [i for i in rows if slots_of[i]]
    z = {i: prob.add_variable(f"z_{i}", cat="Binary") for i in cand}
    x = {(i, s): prob.add_variable(f"x_{i}_{s}", lowBound=0, upBound=1) for i in cand for s in slots_of[i]}
    by_player: dict[int, list] = {i: [] for i in cand}
    by_slot: dict[str, list] = {s: [] for s in ROSTER_SLOTS}
    for (i, s), v in x.items():
        by_player[i].append(v)
        by_slot[s].append(v)
    for s, vs in by_slot.items():
        if not vs:
            raise InfeasibleError(f"No available player can fill {s} on this slate")
        prob += pulp.lpSum(vs) == 1
    for i, vs in by_player.items():
        prob += pulp.lpSum(vs) == z[i]
    used = z
    prob += pulp.lpSum(z.values()) == len(ROSTER_SLOTS)
    prob += pulp.lpSum(float(objective[i]) * z[i] for i in cand)
    salary = pulp.lpSum(int(sal[i]) * z[i] for i in cand)
    prob += salary <= max_salary
    prob += salary >= min_salary
    y = {}
    for g in sorted({games[i] for i in by_player}):
        y[g] = prob.add_variable(f"y_{len(y)}", cat="Binary")
        prob += y[g] <= pulp.lpSum(used[i] for i in by_player if games[i] == g)
    prob += pulp.lpSum(y.values()) >= MIN_GAMES
    for i in rows:
        if int(dkid[i]) in lock_ids:
            if i not in used:
                raise InfeasibleError(f"Locked player {pool['name'].iat[i]} has no DraftKings roster slot")
            prob += used[i] == 1
    row_of = {int(dkid[i]): i for i in by_player}
    for prev in previous:
        terms = [used[row_of[int(d)]] for d in prev if int(d) in row_of]
        if terms:
            prob += pulp.lpSum(terms) <= len(ROSTER_SLOTS) - min_unique

    status = prob.solve(_solver()).status_str
    if status != "Optimal":
        raise InfeasibleError(f"No valid lineup exists under these rules (solver status: {status}). "
                              "Loosen locks, excludes or the minimum salary.")
    chosen = [i for i in cand if z[i].value() is not None and z[i].value() > 0.5]
    order = assign_slots([slots_of[i] for i in chosen])
    if order is None:   # cannot happen when the solver is right; fail loudly rather than emit a bad lineup
        raise InfeasibleError("Solver returned players that cannot fill every roster slot")
    return [int(dkid[chosen[k]]) for k in order]


def assign_slots(eligible: list[list[str]]) -> list[int] | None:
    """Given each player's eligible slots, the player index for each slot in ROSTER_SLOTS order
    (None if no perfect assignment). Most-constrained slot first; deterministic."""
    n = len(ROSTER_SLOTS)
    if len(eligible) != n:
        return None
    can = [[k for k in range(n) if s in eligible[k]] for s in ROSTER_SLOTS]
    order = sorted(range(n), key=lambda j: (len(can[j]), j))
    out: list[int | None] = [None] * n
    used = [False] * n

    def go(t: int) -> bool:
        if t == n:
            return True
        j = order[t]
        for k in can[j]:
            if not used[k]:
                used[k], out[j] = True, k
                if go(t + 1):
                    return True
                used[k] = False
        return False

    return [int(k) for k in out] if go(0) else None
