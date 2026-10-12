"""Simulated opponent field and contest-specific success probabilities."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FIELD_MIN_SALARY, SALARY_CAP


def sample_field(pool: pd.DataFrame, n: int, rng, *, cap: int = SALARY_CAP,
                 min_salary: int = FIELD_MIN_SALARY, max_tries_per_lineup: int = 200) -> np.ndarray:
    """Random valid lineups drawn in proportion to estimated ownership."""
    rows = np.where(pool.playable.to_numpy())[0]
    pos = pool.position.to_numpy()
    raw_own = pool.own_pct.to_numpy(float) + 0.05
    sal = pool.salary.to_numpy()
    by = {p: rows[pos[rows] == p] for p in ("QB", "RB", "WR", "TE", "DST")}
    flex_all = np.concatenate([by["RB"], by["WR"], by["TE"]])
    out = np.empty((n, 9), dtype=np.int64)
    made = tries = misses = 0
    alpha = 1.0     # ownership exponent; flattened only if concentrated ownership can't fit under the cap
    own = raw_own
    prob = {p: own[ix] / own[ix].sum() for p, ix in by.items()}
    while made < n:
        tries += 1
        if tries > n * max_tries_per_lineup:
            raise RuntimeError("Could not sample a valid simulated field — check the ownership estimates")
        if misses >= 500:
            misses, alpha = 0, alpha * 0.8
            own = raw_own ** alpha
            prob = {p: own[ix] / own[ix].sum() for p, ix in by.items()}
        core = np.concatenate([rng.choice(by["QB"], 1, p=prob["QB"]),
                               rng.choice(by["RB"], 2, replace=False, p=prob["RB"]),
                               rng.choice(by["WR"], 3, replace=False, p=prob["WR"]),
                               rng.choice(by["TE"], 1, p=prob["TE"])])
        rest = flex_all[~np.isin(flex_all, core)]
        flex = rng.choice(rest, 1, p=own[rest] / own[rest].sum())
        lu = np.concatenate([core, flex, rng.choice(by["DST"], 1, p=prob["DST"])])
        if min_salary <= sal[lu].sum() <= cap:
            out[made] = lu
            made += 1
            misses = 0
        else:
            misses += 1
    return out


def lineup_scores(sims: np.ndarray, lineups) -> np.ndarray:
    m = np.zeros((sims.shape[1], len(lineups)), dtype=np.float32)
    for c, lu in enumerate(lineups):
        m[np.asarray(lu), c] = 1.0
    return sims @ m


def thresholds(field_scores: np.ndarray, metric: dict) -> np.ndarray:
    if metric["kind"] == "h2h":
        return np.median(field_scores, axis=1)
    return np.quantile(field_scores, 1 - metric["pct"], axis=1)


def contest_metric(cand_scores: np.ndarray, field_scores: np.ndarray, metric: dict) -> np.ndarray:
    if metric["kind"] == "h2h":     # P(beat one randomly drawn opponent); ties lose
        fs = np.sort(field_scores, axis=1)
        wins = np.zeros(cand_scores.shape[1])
        for s in range(fs.shape[0]):
            wins += np.searchsorted(fs[s], cand_scores[s], side="left")
        return wins / (fs.shape[0] * fs.shape[1])
    thr = thresholds(field_scores, metric)
    return (cand_scores >= thr[:, None]).mean(axis=0)
