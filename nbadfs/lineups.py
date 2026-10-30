"""Per-contest NBA lineups: candidate generation, simulation-based pick, single-player swaps, rebuilds.

Conventions: `field` and anything handed to `nfldfs.sim_eval.lineup_scores` are pool ROW indices; lineups
returned to callers (solve_lineup, best_lineup, lineups_df) are dk_ids in ROSTER_SLOTS order. `to_rows`
is the one place that converts between them.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from nfldfs.config import CANDIDATE_PERTURBATION, SWAP_MAX_OWN_TOURNAMENT
from nfldfs.injuries import classify, recommendable
from nfldfs.lineups import BACKUP_COLUMNS, NO_BACKUP, _shortlist, objective_values
from nfldfs.sim_eval import contest_metric, lineup_scores

from .config import MIN_GAMES, MIN_SALARY_DEFAULT, MIN_UNIQUE_PLAYERS, NBA_CONTEST_TYPES, SALARY_CAP, SEED
from .optimizer import InfeasibleError, solve_lineup
from .rules import ROSTER_SLOTS

LINEUP_COLUMNS = ["contest_key", "rank", "slot", "dk_id", "metric"]
SWAP_COLUMNS = ["contest_key", "out_id", "in_id", "delta"]
N_CANDIDATES = 30
REBUILD_CANDIDATES = 30
N_SWAPS = 5
SWAPS_PER_SLOT = 15
KEEP_TOP = 3


def to_rows(pool: pd.DataFrame, dk_ids) -> list[int]:
    """dk_ids -> pool row positions (same order)."""
    pos = pd.Index(pool["dk_id"].astype("int64")).get_indexer([int(d) for d in dk_ids])
    if (pos < 0).any():
        raise KeyError(f"dk_id(s) not in pool: {[d for d, p in zip(dk_ids, pos) if p < 0]}")
    return [int(p) for p in pos]


def generate_candidates(pool, sims, contest: dict, n: int, rng, *, min_salary: int = MIN_SALARY_DEFAULT,
                        locks=(), excludes=()) -> list[list[int]]:
    """Up to n distinct lineups (dk_ids, slot order): the plain optimum, then optima of objectives nudged
    toward random simulated nights. Raises InfeasibleError only if not even the first one exists."""
    base = objective_values(pool, contest["weights"])
    med = pool["median"].to_numpy(float)
    picks: list[list[int]] = []
    for k in range(n):
        obj = base if k == 0 else base + CANDIDATE_PERTURBATION * (sims[rng.integers(len(sims))] - med)
        try:
            picks.append(solve_lineup(pool, obj, min_salary=min_salary, locks=locks, excludes=excludes,
                                      previous=picks, min_unique=MIN_UNIQUE_PLAYERS))
        except InfeasibleError:
            if not picks:
                raise
            break
    return picks


def _eligible(pool: pd.DataFrame, slot: str) -> np.ndarray:
    return np.array([slot in s for s in pool["slots"]], dtype=bool)


def find_swaps(pool, sims, lineup: list[int], contest: dict, field_scores, n: int = N_SWAPS,
               per_slot: int = SWAPS_PER_SLOT) -> pd.DataFrame:
    """Best single-player swaps for `lineup` (dk_ids, slot order). The incoming player must be recommendable,
    able to fill the outgoing player's slot, keep the lineup under the cap and from >= 2 games.
    `delta` = change in the contest metric. Columns out_id, in_id, delta (no contest_key)."""
    rows = to_rows(pool, lineup)
    sal = pool["salary"].to_numpy().astype(int)
    games = pool["game"].to_numpy()
    own = pool["own_pct"].to_numpy(float)
    # Never suggest D/OUT/IR or "news leans out" players (playable-only on pools without injury columns).
    # Phase 2's nbadfs/late_swap.py re-picks must use this same recommendable filter.
    playable = recommendable(pool)
    dkid = pool["dk_id"].to_numpy().astype(np.int64)
    obj = objective_values(pool, contest["weights"])
    in_lineup = np.zeros(len(pool), dtype=bool)
    in_lineup[rows] = True
    total = int(sal[rows].sum())
    base = sims[:, rows].sum(axis=1)
    pairs = []
    for k, o in enumerate(rows):
        others = {games[r] for r in rows if r != o}
        ok = playable & ~in_lineup & _eligible(pool, ROSTER_SLOTS[k]) & (total - sal[o] + sal <= SALARY_CAP)
        if len(others) < MIN_GAMES:
            ok &= ~np.isin(games, list(others))
        if contest["group"] == "Tournament":
            ok &= own < SWAP_MAX_OWN_TOURNAMENT
        cand = np.where(ok)[0]
        pairs += [(o, int(j)) for j in cand[np.argsort(-obj[cand], kind="stable")][:per_slot]]
    if not pairs:
        return pd.DataFrame(columns=SWAP_COLUMNS[1:])
    scores = np.column_stack([base] + [base - sims[:, o] + sims[:, j] for o, j in pairs])
    metric = contest_metric(scores, field_scores, contest["metric"])
    df = pd.DataFrame({"out_id": [int(dkid[o]) for o, _ in pairs], "in_id": [int(dkid[j]) for _, j in pairs],
                       "delta": metric[1:] - metric[0]})
    df = df.sort_values("delta", ascending=False, kind="stable").drop_duplicates("in_id")
    return df.head(n).reset_index(drop=True)


def _n_games(base_games: set, *new) -> np.ndarray:
    """Distinct games in a lineup: `base_games` plus each column of the incoming players' games."""
    known = list(base_games)
    count = np.full(len(new[0]), len(known))
    seen = []
    for g in new:
        fresh = ~np.isin(g, known)
        for prev in seen:
            fresh &= g != prev
        count = count + fresh
        seen.append(g)
    return count


def injury_backups(pool: pd.DataFrame, sims: np.ndarray, field_scores, lineup, contest: dict,
                   per_slot: int = 10) -> pd.DataFrame:
    """One row per tagged (non-healthy) player in `lineup` (dk_ids in ROSTER_SLOTS order): the best healthy
    1:1 replacement for his slot under the cap; else the best two-player rework (him + one other spot);
    else NO_BACKUP. Columns as nfldfs.lineups.BACKUP_COLUMNS.

    Replacements are healthy (no tag or P), recommendable, not already in the lineup, eligible for the
    slot they fill, and the new lineup keeps players from >= MIN_GAMES games. Scored with the contest
    metric against the field (`field_scores` = lineup_scores(sims, field))."""
    rows = to_rows(pool, lineup)
    p = pool if {"inj_class", "recommendable"} <= set(pool.columns) else classify(pool)
    cls = p["inj_class"].to_numpy()
    tagged = [k for k, r in enumerate(rows) if cls[r] != "healthy"]
    if not tagged:
        return pd.DataFrame(columns=BACKUP_COLUMNS)
    sal = p["salary"].to_numpy().astype(int)
    games = p["game"].to_numpy()
    dk = p["dk_id"].to_numpy().astype(np.int64)
    in_lineup = np.zeros(len(p), dtype=bool)
    in_lineup[rows] = True
    free = (cls == "healthy") & recommendable(p) & ~in_lineup
    obj = objective_values(p, contest["weights"])
    total = int(sal[rows].sum())
    base = sims[:, rows].sum(axis=1)
    fs = field_scores

    def metric(scores):
        return contest_metric(scores.astype(np.float32, copy=False), fs, contest["metric"])

    before = float(metric(base[:, None])[0])

    def fits(k):
        return np.where(free & _eligible(p, ROSTER_SLOTS[k]))[0]

    def name(i):
        return str(p["name"].iat[i])

    def row(t, kind, outs, ins, after, message):
        return {"tagged_dk_id": int(dk[t]), "kind": kind, "out_dk_ids": [int(dk[i]) for i in outs],
                "in_dk_ids": [int(dk[i]) for i in ins],
                "remaining_salary": int(SALARY_CAP - total + (sal[list(outs)].sum() - sal[list(ins)].sum() if ins else 0)),
                "metric_before": before, "metric_after": float(after), "message": message}

    out = []
    for kt in tagged:
        t = rows[kt]
        keep = {games[r] for r in rows if r != t}
        cand = fits(kt)
        cand = cand[(total - sal[t] + sal[cand] <= SALARY_CAP) & (_n_games(keep, games[cand]) >= MIN_GAMES)]
        if len(cand):
            m = metric(base[:, None] - sims[:, [t]] + sims[:, cand])
            b = int(np.argmax(m))
            j = int(cand[b])
            out.append(row(t, "1:1", [t], [j], m[b], f"If {name(t)} sits: {name(j)}"))
            continue
        best = None
        jt = _shortlist(fits(kt), obj, sal, per_slot)
        for ko, o in enumerate(rows):
            if o == t or not len(jt):
                continue
            kk = _shortlist(fits(ko), obj, sal, per_slot)
            if not len(kk):
                continue
            J, K = (a.ravel() for a in np.meshgrid(jt, kk, indexing="ij"))
            keep2 = {games[r] for r in rows if r not in (t, o)}
            ok = ((J != K) & (total - sal[t] - sal[o] + sal[J] + sal[K] <= SALARY_CAP)
                  & (_n_games(keep2, games[J], games[K]) >= MIN_GAMES))
            if not ok.any():
                continue
            J, K = J[ok], K[ok]
            m = metric((base - sims[:, t] - sims[:, o])[:, None] + sims[:, J] + sims[:, K])
            b = int(np.argmax(m))
            if best is None or m[b] > best[0]:
                best = (float(m[b]), o, int(J[b]), int(K[b]))
        if best is not None:
            m, o, j, k = best
            out.append(row(t, "two-player", [t, o], [j, k], m,
                           f"If {name(t)} sits: {name(j)}, {name(k)} for {name(t)}, {name(o)}"))
        else:
            out.append(row(t, "none", [t], [], before, NO_BACKUP))
    return pd.DataFrame(out, columns=BACKUP_COLUMNS)


def rank0_backups(pool: pd.DataFrame, sims: np.ndarray, field: np.ndarray, lineups: pd.DataFrame,
                  contest_types: dict = NBA_CONTEST_TYPES) -> pd.DataFrame:
    """injury_backups for every contest type's rank-0 lineup (one row per tagged player in it)."""
    cols = ["contest_key", *BACKUP_COLUMNS]
    rec = lineups[lineups["rank"] == 0]
    p = pool if {"inj_class", "recommendable"} <= set(pool.columns) else classify(pool)
    healthy = dict(zip(p["dk_id"].astype("int64"), p["inj_class"] == "healthy"))
    order = {s: k for k, s in enumerate(ROSTER_SLOTS)}
    frames, field_scores = [], None
    for key, g in rec.groupby("contest_key", sort=False):
        if all(healthy[int(d)] for d in g["dk_id"]):
            continue
        if field_scores is None:
            field_scores = lineup_scores(sims, field)
        ids = g.sort_values("slot", key=lambda s: s.map(order), kind="stable")["dk_id"].tolist()
        bk = injury_backups(p, sims, field_scores, ids, contest_types[key])
        bk.insert(0, "contest_key", key)
        frames.append(bk)
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True)[cols] if frames else pd.DataFrame(columns=cols)


def build_all(pool: pd.DataFrame, sims: np.ndarray, field: np.ndarray, contest_types: dict = NBA_CONTEST_TYPES,
              n_candidates: int = N_CANDIDATES, seed: int = SEED, *, keep_top: int = KEEP_TOP,
              min_salary: int = MIN_SALARY_DEFAULT) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Recommended lineups (up to keep_top per contest, rank 0 = best) and swaps for the rank-0 lineup.
    Candidates are shared between contest types with identical objective weights."""
    rng = np.random.default_rng(seed)
    field_scores = lineup_scores(sims, field)
    cache: dict[str, list[list[int]]] = {}
    lineup_rows, swap_frames = [], []
    for key, contest in contest_types.items():
        ck = json.dumps(contest["weights"], sort_keys=True)
        if ck not in cache:
            cache[ck] = generate_candidates(pool, sims, contest, n_candidates, rng, min_salary=min_salary)
        cands = cache[ck]
        metric = contest_metric(lineup_scores(sims, [to_rows(pool, c) for c in cands]), field_scores,
                                contest["metric"])
        order = np.argsort(-metric, kind="stable")
        for rank, c in enumerate(order[:keep_top]):
            for slot, dk in zip(ROSTER_SLOTS, cands[c]):
                lineup_rows.append({"contest_key": key, "rank": rank, "slot": slot, "dk_id": int(dk),
                                    "metric": float(metric[c])})
        sw = find_swaps(pool, sims, cands[int(order[0])], contest, field_scores)
        sw.insert(0, "contest_key", key)
        swap_frames.append(sw)
    swap_frames = [f for f in swap_frames if len(f)]
    swaps = pd.concat(swap_frames, ignore_index=True) if swap_frames else pd.DataFrame(columns=SWAP_COLUMNS)
    return pd.DataFrame(lineup_rows, columns=LINEUP_COLUMNS), swaps[SWAP_COLUMNS]


def best_lineup(pool: pd.DataFrame, sims: np.ndarray, field: np.ndarray, contest: dict, *, locks=(),
                excludes=(), n_candidates: int = REBUILD_CANDIDATES, seed: int = SEED,
                min_salary: int = MIN_SALARY_DEFAULT) -> tuple[list[int], float]:
    """Best lineup (dk_ids, slot order) and its contest metric under the user's locks/excludes.
    A lock on an Out player is honored; show `out_lock_warnings` alongside."""
    rng = np.random.default_rng(seed)
    cands = generate_candidates(pool, sims, contest, n_candidates, rng, min_salary=min_salary,
                                locks=locks, excludes=excludes)
    metric = contest_metric(lineup_scores(sims, [to_rows(pool, c) for c in cands]), lineup_scores(sims, field),
                            contest["metric"])
    i = int(np.argmax(metric))
    return cands[i], float(metric[i])


_TAG_WORD = {"OUT": "Out", "D": "Doubtful", "IR": "on IR"}


def out_lock_warnings(pool: pd.DataFrame, locks) -> list[str]:
    """One ⚠ per locked player the app would never pick itself: "⚠ <name> is listed Out" (Doubtful, on IR)
    for DraftKings-unplayable players, "⚠ <name>: news leans out" for a questionable one whose news leans out."""
    lock_ids = {int(d) for d in locks}
    hit = pool[pool["dk_id"].astype("int64").isin(lock_ids)]
    tags = hit["inj_tag"] if "inj_tag" in hit.columns else pd.Series("OUT", index=hit.index)
    rec = hit["recommendable"].astype(bool) if "recommendable" in hit.columns else hit["playable"].astype(bool)
    out = []
    for i in hit.index:
        name = hit.at[i, "name"]
        if not bool(hit.at[i, "playable"]):
            tag = str(tags.at[i]) or "OUT"
            out.append(f"⚠ {name} is listed {_TAG_WORD.get(tag, tag)}")
        elif not rec.at[i]:
            out.append(f"⚠ {name}: news leans out")
    return out
