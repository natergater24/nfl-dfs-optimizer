"""Pre-lock ownership estimate (v1 heuristic; replaced by a fitted model once results are imported — Plan 2)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import OWNERSHIP_TIERS

# Expected total ownership per position across the field: 9 roster spots = 900%.
# FLEX (100%) split roughly RB 30 / WR 55 / TE 15.
SLOT_TOTALS = {"QB": 100.0, "RB": 230.0, "WR": 355.0, "TE": 115.0, "DST": 100.0}
MAX_OWN = 60.0
TEMPERATURE = 0.6
W_VALUE, W_MEDIAN, W_ENV = 1.0, 0.6, 0.3


def _z(x: np.ndarray) -> np.ndarray:
    sd = x.std()
    return (x - x.mean()) / sd if sd > 0 else np.zeros_like(x)


def _cap(own: np.ndarray, cap: float) -> np.ndarray:
    own = own.copy()
    for _ in range(50):
        over = own > cap
        if not over.any():
            break
        excess = float((own[over] - cap).sum())
        own[over] = cap
        free = own < cap
        if not free.any() or own[free].sum() == 0:
            break
        own[free] += excess * own[free] / own[free].sum()
    return own


def estimate_ownership(pool: pd.DataFrame) -> pd.Series:
    own = pd.Series(0.0, index=pool.index)
    env = np.where(pool.position == "DST", -pool.opp_implied, pool.implied_total).astype(float)
    for pos, total in SLOT_TOTALS.items():
        m = ((pool.position == pos) & pool.playable).to_numpy()
        if not m.any():
            continue
        med = pool["median"].to_numpy(float)[m]
        value = med / (pool.salary.to_numpy(float)[m] / 1000)
        score = W_VALUE * _z(value) + W_MEDIAN * _z(med) + W_ENV * _z(env[m])
        w = np.exp(score / TEMPERATURE)
        own[pool.index[m]] = _cap(w / w.sum() * total, MAX_OWN)
    return own


def ownership_tier(pct: float) -> str:
    for cutoff, label in OWNERSHIP_TIERS:
        if pct >= cutoff:
            return label
    return OWNERSHIP_TIERS[-1][1]
