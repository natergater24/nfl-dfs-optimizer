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


FEATURES = ("z_value", "z_median", "z_env")
MIN_MODEL_WEEKS = 3
MIN_ROWS_PER_POSITION = 25


def ownership_features(pool: pd.DataFrame) -> pd.DataFrame:
    feats = pd.DataFrame(0.0, index=pool.index, columns=list(FEATURES))
    env = np.where(pool.position == "DST", -pool.opp_implied, pool.implied_total).astype(float)
    for pos in SLOT_TOTALS:
        m = ((pool.position == pos) & pool.playable).to_numpy()
        if not m.any():
            continue
        med = pool["median"].to_numpy(float)[m]
        value = med / (pool.salary.to_numpy(float)[m] / 1000)
        idx = pool.index[m]
        feats.loc[idx, "z_value"] = _z(value)
        feats.loc[idx, "z_median"] = _z(med)
        feats.loc[idx, "z_env"] = _z(env[m])
    return feats


def estimate_ownership(pool: pd.DataFrame, model: dict | None = None) -> pd.Series:
    own = pd.Series(0.0, index=pool.index)
    feats = ownership_features(pool)
    coefs = (model or {}).get("coef", {})
    for pos, total in SLOT_TOTALS.items():
        m = ((pool.position == pos) & pool.playable).to_numpy()
        if not m.any():
            continue
        X = feats.loc[pool.index[m], list(FEATURES)].to_numpy()
        if pos in coefs:
            b = np.asarray(coefs[pos], dtype=float)
            w = np.exp(np.clip(b[0] + X @ b[1:], -20, 20))
        else:
            w = np.exp((W_VALUE * X[:, 0] + W_MEDIAN * X[:, 1] + W_ENV * X[:, 2]) / TEMPERATURE)
        own[pool.index[m]] = _cap(w / w.sum() * total, MAX_OWN)
    return own


def fit_ownership_model(history: pd.DataFrame) -> dict | None:
    """Per-position log-linear fit of actual ownership on the same features the heuristic uses."""
    h = history.dropna(subset=["actual_own"])
    weeks = int(h["slate_date"].nunique()) if len(h) else 0
    if weeks < MIN_MODEL_WEEKS:
        return None
    parts = []
    for _, g in h.groupby("slate_date"):
        g = g.assign(playable=True).reset_index(drop=True)
        parts.append(pd.concat([g, ownership_features(g)], axis=1))
    data = pd.concat(parts, ignore_index=True)
    coef = {}
    for pos, g in data.groupby("position"):
        if len(g) < MIN_ROWS_PER_POSITION:
            continue
        X = np.column_stack([np.ones(len(g)), g[list(FEATURES)].to_numpy()])
        y = np.log(g["actual_own"].to_numpy(float) + 0.5)
        coef[pos] = np.linalg.lstsq(X, y, rcond=None)[0].round(5).tolist()
    return {"weeks": weeks, "rows": int(len(data)), "coef": coef} if coef else None


def ownership_tier(pct: float) -> str:
    for cutoff, label in OWNERSHIP_TIERS:
        if pct >= cutoff:
            return label
    return OWNERSHIP_TIERS[-1][1]
