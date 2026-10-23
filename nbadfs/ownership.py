"""Pre-lock NBA ownership estimate (heuristic), tiers, and the simulated opponent field."""
from __future__ import annotations

import numpy as np
import pandas as pd

from nfldfs.ownership import ownership_tier

from .config import MIN_GAMES, SALARY_CAP
from .rules import ROSTER_SLOTS

TOTAL_OWN = 100.0 * len(ROSTER_SLOTS)    # 8 roster spots x 100% = 800% across the field
MAX_OWN = 70.0
TEMPERATURE = 0.6
W_VALUE, W_MEDIAN, W_ENV = 1.0, 0.5, 0.3
FIELD_MIN_SALARY = 46_000                # simulated opponents leave a little salary unused


def _z(x: np.ndarray) -> np.ndarray:
    sd = x.std()
    return (x - x.mean()) / sd if sd > 0 else np.zeros_like(x)


def _cap(own: np.ndarray, cap: float) -> np.ndarray:
    """Clip at `cap`, handing the excess to the uncapped players in proportion (total unchanged)."""
    own = own.copy()
    for _ in range(100):
        over = own > cap + 1e-12
        if not over.any():
            break
        excess = float((own[over] - cap).sum())
        own[over] = cap
        free = own < cap - 1e-12
        if not free.any() or own[free].sum() == 0:
            break
        own[free] += excess * own[free] / own[free].sum()
    return own


def estimate_ownership(pool: pd.DataFrame) -> pd.Series:
    """Percent owned: softmax of z(value) + 0.5 z(median) + 0.3 z(implied_total) over playable players,
    scaled to sum to 800 and capped at 70. Non-playable players get 0."""
    own = pd.Series(0.0, index=pool.index)
    m = pool["playable"].to_numpy(dtype=bool)
    if not m.any():
        return own
    med = pool["median"].to_numpy(float)[m]
    value = med / (pool["salary"].to_numpy(float)[m] / 1000)
    score = W_VALUE * _z(value) + W_MEDIAN * _z(med) + W_ENV * _z(pool["implied_total"].to_numpy(float)[m])
    w = np.exp((score - score.max()) / TEMPERATURE)
    own[pool.index[m]] = _cap(w / w.sum() * TOTAL_OWN, MAX_OWN)
    return own


def add_ownership(pool: pd.DataFrame) -> pd.DataFrame:
    out = pool.copy()
    out["own_pct"] = estimate_ownership(pool)
    out["tier"] = out["own_pct"].map(ownership_tier)
    return out


def _eligibility(pool: pd.DataFrame) -> np.ndarray:
    """bool (len(ROSTER_SLOTS) x len(pool)): player row may fill slot."""
    elig = np.zeros((len(ROSTER_SLOTS), len(pool)), dtype=bool)
    for r, slots in enumerate(pool["slots"]):
        for s in slots:
            elig[ROSTER_SLOTS.index(s), r] = True
    return elig


def sample_field(pool: pd.DataFrame, n: int, rng, *, cap: int = SALARY_CAP,
                 min_salary: int = FIELD_MIN_SALARY, max_tries_per_lineup: int = 200) -> np.ndarray:
    """n random legal lineups as pool ROW indices in ROSTER_SLOTS order. Slots are filled in random order;
    each draw is weighted by own_pct + 0.05 among eligible, unused players whose salary still leaves the
    remaining slots fillable between `min_salary` and the cap (reserve uses the cheapest / priciest unused
    salaries, so it is an approximation — the final check enforces legality)."""
    playable = pool["playable"].to_numpy(dtype=bool)
    elig = _eligibility(pool) & playable
    w_all = pool["own_pct"].to_numpy(float) + 0.05
    sal = pool["salary"].to_numpy(float)
    game = pd.factorize(pool["game"])[0]
    asc = np.where(playable)[0][np.argsort(sal[playable], kind="stable")]
    k = len(ROSTER_SLOTS)
    out = np.empty((n, k), dtype=np.int64)
    made = tries = 0
    while made < n:
        tries += 1
        if tries > n * max_tries_per_lineup:
            raise RuntimeError("Could not sample a valid simulated field — check the slate and ownership estimates")
        taken = np.zeros(len(pool), dtype=bool)
        spent = 0.0
        lu = np.full(k, -1, dtype=np.int64)
        ok = True
        for step, si in enumerate(rng.permutation(k)):
            left = k - step - 1
            free = asc[~taken[asc]]
            lo_rest = sal[free[:left]].sum() if left else 0.0
            hi_rest = sal[free[len(free) - left:]].sum() if left else 0.0
            cand = np.where(elig[si] & ~taken)[0]
            cand = cand[(spent + sal[cand] + lo_rest <= cap) & (spent + sal[cand] + hi_rest >= min_salary)]
            if left == 0 and len(set(game[lu[lu >= 0]])) < MIN_GAMES:
                cand = cand[~np.isin(game[cand], game[lu[lu >= 0]])]
            if len(cand) == 0:
                ok = False
                break
            w = w_all[cand]
            pick = int(rng.choice(cand, p=w / w.sum()))
            lu[si] = pick
            taken[pick] = True
            spent += sal[pick]
        if ok and min_salary <= spent <= cap and len(set(game[lu])) >= MIN_GAMES:
            out[made] = lu
            made += 1
    return out
