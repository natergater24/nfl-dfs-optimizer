"""Correlated Monte Carlo of DK points: shared game and team factors plus player noise."""
from __future__ import annotations

import numpy as np
import pandas as pd

from nfldfs.injuries import apply_play_prob

GAME_SD = 0.06
TEAM_SD = 0.04


def _live(pool: pd.DataFrame) -> np.ndarray:
    """DraftKings-playable and, on injury-aware pools, recommendable (a lean-out player never plays)."""
    live = pool["playable"].to_numpy(dtype=bool)
    if "recommendable" in pool.columns:
        live = live & pool["recommendable"].to_numpy(dtype=bool)
    return live


def simulate(pool: pd.DataFrame, n_sims: int, seed: int, *, sit: bool = True) -> np.ndarray:
    """float32 (n_sims x len(pool)); deterministic for the same pool row order, n_sims and seed.

    With a play_prob column (published with the pool), a questionable player scores 0 in a seeded
    (1 - play_prob) share of sims, so the app regenerates exactly the build's sims. sit=False returns the
    when-he-plays draws (used for the displayed floor/ceiling)."""
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
    sims[:, ~_live(pool)] = 0.0
    sims = sims.astype(np.float32)
    return apply_play_prob(sims, pool, seed) if sit else sims


def summarize(sims: np.ndarray, pool: pd.DataFrame) -> pd.DataFrame:
    """Copy of pool with floor/ceiling = 15th/85th percentile; median stays the projected value."""
    out = pool.copy()
    out["floor"] = np.percentile(sims, 15, axis=0)
    out["ceiling"] = np.percentile(sims, 85, axis=0)
    return out
