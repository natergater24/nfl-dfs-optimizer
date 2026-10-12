"""Per-contest-type candidate generation, simulation-based pick, and outlier swaps."""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from .config import (CANDIDATE_PERTURBATION, CONTEST_TYPES, FIELD_SIZE, MIN_SALARY_DEFAULT,
                     MIN_UNIQUE_PLAYERS, N_CANDIDATES, N_SWAPS, SALARY_CAP, SEED, SWAP_MAX_OWN_TOURNAMENT)
from .dk_rules import ROSTER_SLOTS, assign_slots
from .optimizer import InfeasibleError, solve_lineup
from .sim_eval import contest_metric, field_ownership, lineup_scores, sample_field, thresholds

log = logging.getLogger("nfldfs.lineups")

LINEUP_COLUMNS = ["contest_key", "contest_label", "contest_group", "rank", "slot", "dk_id", "name", "position",
                  "team", "opp", "kickoff", "salary", "median", "floor", "ceiling", "own_pct", "tier",
                  "metric", "total_salary"]
SWAP_COLUMNS = ["out_dk_id", "out_name", "in_dk_id", "in_name", "position", "in_team", "salary_delta",
                "remaining_salary", "median_delta", "ceiling_delta", "in_own_pct", "in_tier", "metric_delta"]


def objective_values(pool: pd.DataFrame, weights: dict) -> np.ndarray:
    return (weights.get("floor", 0) * pool["floor"].to_numpy(float)
            + weights.get("median", 0) * pool["median"].to_numpy(float)
            + weights.get("ceiling", 0) * pool["ceiling"].to_numpy(float)
            - weights.get("own_penalty", 0) * pool["own_pct"].to_numpy(float))


def generate_candidates(pool, sims, contest: dict, n: int, rng, *, min_salary: int = MIN_SALARY_DEFAULT,
                        locks=(), excludes=()) -> list[list[int]]:
    base = objective_values(pool, contest["weights"])
    med = pool["median"].to_numpy(float)
    picks: list[list[int]] = []
    for k in range(n):
        obj = base if k == 0 else base + CANDIDATE_PERTURBATION * (sims[rng.integers(len(sims))] - med)
        try:
            picks.append(solve_lineup(pool, obj, min_salary=min_salary, stack=contest["stack"], locks=locks,
                                      excludes=excludes, previous=picks, min_unique=MIN_UNIQUE_PLAYERS))
        except InfeasibleError:
            if not picks:
                raise
            break
    return picks


def find_swaps(pool, sims, lineup: list[int], contest: dict, field_scores, n: int = N_SWAPS,
               per_slot: int = 15) -> pd.DataFrame:
    thr = thresholds(field_scores, contest["metric"])
    base = sims[:, lineup].sum(axis=1)
    base_metric = float((base >= thr).mean())
    sal, pos = pool.salary.to_numpy(), pool.position.to_numpy()
    own, playable = pool.own_pct.to_numpy(float), pool.playable.to_numpy()
    total = int(sal[lineup].sum())
    obj = objective_values(pool, contest["weights"])
    in_lineup = np.zeros(len(pool), dtype=bool)
    in_lineup[lineup] = True
    rows = []
    for o in lineup:
        ok = playable & ~in_lineup & (pos == pos[o]) & (total - sal[o] + sal <= SALARY_CAP)
        if contest["group"] == "Tournament":
            ok &= own < SWAP_MAX_OWN_TOURNAMENT
        cand = np.where(ok)[0]
        for j in cand[np.argsort(-obj[cand])][:per_slot]:
            new = base - sims[:, o] + sims[:, j]
            rows.append({
                "out_dk_id": int(pool.dk_id.iat[o]), "out_name": pool["name"].iat[o],
                "in_dk_id": int(pool.dk_id.iat[j]), "in_name": pool["name"].iat[j], "position": pos[j],
                "in_team": pool.team.iat[j], "salary_delta": int(sal[j] - sal[o]),
                "remaining_salary": int(SALARY_CAP - (total - sal[o] + sal[j])),
                "median_delta": float(pool["median"].iat[j] - pool["median"].iat[o]),
                "ceiling_delta": float(pool["ceiling"].iat[j] - pool["ceiling"].iat[o]),
                "in_own_pct": float(own[j]), "in_tier": pool["tier"].iat[j],
                "metric_delta": float((new >= thr).mean() - base_metric),
            })
    if not rows:
        return pd.DataFrame(columns=SWAP_COLUMNS)
    df = pd.DataFrame(rows).sort_values("metric_delta", ascending=False, kind="stable")
    return df.drop_duplicates("in_dk_id").head(n).reset_index(drop=True)[SWAP_COLUMNS]


def _warn_ownership_conflict(pool: pd.DataFrame, field: np.ndarray) -> None:
    got = field_ownership(pool, field)
    diff = (got - pool["own_pct"].astype(float)).abs()
    bad = diff[diff > 15].sort_values(ascending=False).head(10)
    if len(bad):
        items = "; ".join(f"{pool.loc[i, 'name']} est {pool.loc[i, 'own_pct']:.0f}% / field {got[i]:.0f}%"
                          for i in bad.index)
        log.warning("Simulated field ownership differs from the estimates by >15 points for: %s. "
                    "The ownership estimates cannot all co-exist under the salary cap.", items)


def build_all(pool: pd.DataFrame, sims: np.ndarray, *, contest_types: dict = CONTEST_TYPES,
              n_candidates: int = N_CANDIDATES, field_size: int = FIELD_SIZE, seed: int = SEED,
              keep_top: int = 3, min_salary: int = MIN_SALARY_DEFAULT) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    field = sample_field(pool, field_size, rng)
    field_scores = lineup_scores(sims, field)
    _warn_ownership_conflict(pool, field)
    cache: dict[str, list[list[int]]] = {}
    lineup_rows, swap_frames = [], []
    by_id = pool.set_index("dk_id")
    for key, contest in contest_types.items():
        ck = json.dumps({"w": contest["weights"], "s": contest["stack"]}, sort_keys=True)
        if ck not in cache:
            cache[ck] = generate_candidates(pool, sims, contest, n_candidates, rng, min_salary=min_salary)
        cands = cache[ck]
        metric = contest_metric(lineup_scores(sims, cands), field_scores, contest["metric"])
        for rank, c in enumerate(np.argsort(-metric, kind="stable")[:keep_top]):
            players = pool.loc[cands[c]]
            total = int(players.salary.sum())
            for slot, dk in zip(ROSTER_SLOTS, assign_slots(players)):
                r = by_id.loc[dk]
                lineup_rows.append({
                    "contest_key": key, "contest_label": contest["label"], "contest_group": contest["group"],
                    "rank": rank, "slot": slot, "dk_id": int(dk), "name": r["name"], "position": r.position,
                    "team": r.team, "opp": r.opp, "kickoff": r.kickoff, "salary": int(r.salary),
                    "median": float(r["median"]), "floor": float(r["floor"]), "ceiling": float(r["ceiling"]),
                    "own_pct": float(r.own_pct), "tier": r["tier"], "metric": float(metric[c]),
                    "total_salary": total,
                })
        best = cands[int(np.argmax(metric))]
        sw = find_swaps(pool, sims, best, contest, field_scores)
        sw.insert(0, "contest_key", key)
        swap_frames.append(sw)
    return (pd.DataFrame(lineup_rows, columns=LINEUP_COLUMNS),
            pd.concat(swap_frames, ignore_index=True))
