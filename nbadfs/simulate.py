"""Correlated Monte Carlo of DK points: shared game and team factors plus player noise."""
from __future__ import annotations

import numpy as np
import pandas as pd

GAME_SD = 0.06
TEAM_SD = 0.04


def simulate(pool: pd.DataFrame, n_sims: int, seed: int) -> np.ndarray:
    """float32 (n_sims x len(pool)); deterministic for the same pool row order, n_sims and seed."""
    rng = np.random.Generator(np.random.PCG64(seed))
    games = sorted(pool["game"].unique())
    teams = sorted(pool["team"].unique())
    gf = rng.normal(1.0, GAME_SD, size=(n_sims, len(games)))
    tf = rng.normal(1.0, TEAM_SD, size=(n_sims, len(teams)))
    z = rng.standard_normal((n_sims, len(pool)))
    gi = pd.Index(games).get_indexer(pool["game"])
    ti = pd.Index(teams).get_indexer(pool["team"])
    median = pool["median"].to_numpy(dtype=float)
    sd = pool["sd"].to_numpy(dtype=float)
    sims = median * gf[:, gi] * tf[:, ti] + sd * z
    sims = np.maximum(sims, 0.0)
    sims[:, ~pool["playable"].to_numpy(dtype=bool)] = 0.0
    return sims.astype(np.float32)


def summarize(sims: np.ndarray, pool: pd.DataFrame) -> pd.DataFrame:
    """Copy of pool with floor/ceiling = 15th/85th percentile; median stays the projected value."""
    out = pool.copy()
    out["floor"] = np.percentile(sims, 15, axis=0)
    out["ceiling"] = np.percentile(sims, 85, axis=0)
    return out
