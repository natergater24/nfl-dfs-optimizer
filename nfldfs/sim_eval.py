"""Simulated opponent field and contest-specific success probabilities."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FIELD_MIN_SALARY, SALARY_CAP


_SLOTS = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST")
_FLEX_POS = ("RB", "WR", "TE")


def _reserve(slots, sal_by_pos, chosen) -> float:
    """Approximate cheapest total salary for the still-unfilled slots (None if impossible)."""
    total, need_flex = 0.0, 0
    taken: dict[str, int] = {}
    for sl in slots:
        if sl == "FLEX":
            need_flex += 1
        else:
            taken[sl] = taken.get(sl, 0) + 1
    leftovers = []
    for pos in ("QB", "RB", "WR", "TE", "DST"):
        sal = sal_by_pos[pos][~chosen[pos]]
        k = taken.get(pos, 0)
        if len(sal) < k:
            return None
        total += sal[:k].sum()
        if pos in _FLEX_POS:
            leftovers.append(sal[k:])
    if need_flex:
        rest = np.sort(np.concatenate(leftovers))
        if len(rest) < need_flex:
            return None
        total += rest[:need_flex].sum()
    return total


def sample_field(pool: pd.DataFrame, n: int, rng, *, cap: int = SALARY_CAP,
                 min_salary: int = FIELD_MIN_SALARY, max_tries_per_lineup: int = 200) -> np.ndarray:
    """Random valid lineups: slots filled in random order, each draw proportional to ownership
    among players who still leave the remaining slots affordable under the cap."""
    rows = np.where(pool.playable.to_numpy())[0]
    pos = pool.position.to_numpy()
    w_all = pool.own_pct.to_numpy(float) + 0.05
    sal = pool.salary.to_numpy().astype(float)
    by = {p: rows[pos[rows] == p] for p in ("QB", "RB", "WR", "TE", "DST")}
    order_by = {p: ix[np.argsort(sal[ix], kind="stable")] for p, ix in by.items()}
    sal_by_pos = {p: sal[ix] for p, ix in order_by.items()}
    idx_in = {p: {r: i for i, r in enumerate(ix)} for p, ix in order_by.items()}
    flex_ids = np.concatenate([by[p] for p in _FLEX_POS])
    out = np.empty((n, 9), dtype=np.int64)
    made = tries = 0
    while made < n:
        tries += 1
        if tries > n * max_tries_per_lineup:
            raise RuntimeError("Could not sample a valid simulated field — check the ownership estimates")
        chosen = {p: np.zeros(len(ix), dtype=bool) for p, ix in order_by.items()}
        taken = np.zeros(len(pool), dtype=bool)
        left = float(cap)
        lu = [0] * 9
        perm = rng.permutation(9)
        ok = True
        for step, si in enumerate(perm):
            slot = _SLOTS[si]
            cand = flex_ids if slot == "FLEX" else by[slot]
            cand = cand[~taken[cand]]
            remaining = [_SLOTS[j] for j in perm[step + 1:]]
            # reserve ignores the candidate itself (approximation; final check enforces validity)
            res = _reserve(remaining, sal_by_pos, chosen)
            if res is None:
                ok = False
                break
            cand = cand[sal[cand] <= left - res]
            if len(cand) == 0:
                ok = False
                break
            w = w_all[cand]
            pick = int(rng.choice(cand, p=w / w.sum()))
            lu[si] = pick
            taken[pick] = True
            left -= sal[pick]
            chosen[pos[pick]][idx_in[pos[pick]][pick]] = True
        if not ok:
            continue
        total = sal[lu].sum()
        if min_salary <= total <= cap:
            out[made] = lu
            made += 1
    return out


def field_ownership(pool: pd.DataFrame, field: np.ndarray) -> pd.Series:
    """Percent of field lineups containing each pool row."""
    counts = np.bincount(np.asarray(field).ravel(), minlength=len(pool))
    return pd.Series(100.0 * counts / len(field), index=pool.index)


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
