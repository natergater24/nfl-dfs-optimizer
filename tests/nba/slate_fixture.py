"""Synthetic NBA slate pools for the optimizer / lineup tests (no network)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from nbadfs.rules import eligible_slots

POSITION_CYCLE = ["PG", "SG", "SF", "PF", "C", "PG/SG", "SG/SF", "SF/PF", "PF/C", "C"]


def player(dk_id, name, team, opp, game, positions, salary, median, playable=True, implied=112.0):
    return dict(dk_id=dk_id, name=name, team=team, opp=opp, game=game, tip="2026-10-24T19:00:00",
                positions=positions, slots=eligible_slots(positions), salary=int(salary),
                status="" if playable else "O", dk_avg=float(median), playable=playable,
                minutes=30.0, rate=1.0, implied_total=implied, opp_implied=implied, line_missing=False,
                median=float(median) if playable else 0.0, sd=0.3 * float(median) + 2.0, floor=np.nan,
                ceiling=np.nan)


def slate_pool(n_games: int = 4, per_team: int = 10, seed: int = 0) -> pd.DataFrame:
    """n_games games x 2 teams x per_team players; salaries $3,000-$11,000, medians ~ 5x value."""
    rng = np.random.default_rng(seed)
    rows, k = [], 1000
    for g in range(n_games):
        away, home = f"A{g}", f"H{g}"
        game = f"{away}@{home}"
        imp = 105.0 + 3.0 * g
        for team, opp in ((away, home), (home, away)):
            for j in range(per_team):
                salary = int(round(rng.uniform(3000, 11000) / 100) * 100)
                median = salary / 1000 * rng.uniform(4.2, 5.8)
                rows.append(player(k, f"P{k}", team, opp, game, POSITION_CYCLE[j % len(POSITION_CYCLE)],
                                   salary, median, implied=imp))
                k += 1
    return pd.DataFrame(rows)


def ready_pool(pool: pd.DataFrame, n_sims: int = 2000, seed: int = 1):
    """Pool with floor/ceiling and ownership filled in, plus its sims."""
    from nbadfs.ownership import add_ownership
    from nbadfs.simulate import simulate, summarize
    sims = simulate(pool, n_sims, seed)
    return add_ownership(summarize(sims, pool)), sims
