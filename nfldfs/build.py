"""Turn loaded inputs into a full slate build: projections, ownership, lineups, swaps."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import lineups, matchups, ownership, shares, simulate, team_env
from .config import FIELD_SIZE, N_CANDIDATES, N_SIMS, N_SIMS_PUBLISHED, SEED
from .dk_rules import write_upload_csv
from .status import atomic_save_npy, atomic_write_parquet, atomic_write_text
from .vegas import implied_totals


def assemble_team_expectations(pool_base: pd.DataFrame, vegas_games: pd.DataFrame, team_model: dict):
    slate_games = set(pool_base.game_id)
    it = implied_totals(vegas_games[vegas_games.game_id.isin(slate_games)])
    slate_teams = set(pool_base.team) | set(pool_base.opp)
    missing = sorted(slate_teams - set(it.team))
    if missing:
        raise ValueError("No Vegas lines yet for: " + ", ".join(missing)
                         + ". Lines are usually posted early in the week; re-run once they are.")
    pool = pool_base.drop(columns=[c for c in ("implied_total", "opp_implied", "exp_margin")
                                   if c in pool_base.columns])
    pool = pool.merge(it[["team", "implied_total", "exp_margin"]], on="team", how="left")
    pool["opp_implied"] = pool.opp.map(it.set_index("team").implied_total)
    team_exp = team_env.expected_team_stats(it, team_model).set_index("team")
    return pool.reset_index(drop=True), team_exp


def build_slate(pool_base, player_weeks, team_weeks, team_model, vegas_games, *, n_sims: int = N_SIMS,
                seed: int = SEED, n_candidates: int = N_CANDIDATES, field_size: int = FIELD_SIZE, schedule_rows=None,
                ownership_model=None) -> dict:
    pool, team_exp = assemble_team_expectations(pool_base, vegas_games, team_model)
    pool = shares.attach_shares(pool, shares.compute_shares(player_weeks, team_weeks))
    pool = shares.redistribute(pool).reset_index(drop=True)
    sims = simulate.simulate(pool, team_exp, n_sims, seed)
    pool = pool.join(simulate.summarize(sims, pool))
    pool["own_pct"] = ownership.estimate_ownership(pool, ownership_model)
    pool["tier"] = pool.own_pct.map(ownership.ownership_tier)
    dvp = (matchups.defense_vs_position(player_weeks, schedule_rows) if schedule_rows is not None
           else pd.DataFrame(columns=["defense", "position", "allowed", "ratio", "rank"]))
    pool = matchups.attach_matchups(pool, dvp)
    lus, swaps, field = lineups.build_all(pool, sims, n_candidates=n_candidates, field_size=field_size, seed=seed)
    offense = pool[(pool.position != "DST") & pool.playable]
    return {"pool": pool, "sims": sims, "lineups": lus, "swaps": swaps, "field": field,
            "match_rate": float(offense.matched.mean()) if len(offense) else 1.0,
            "unmatched": sorted(offense.loc[~offense.matched, "name"].tolist())}


def write_published(res: dict, out_dir, meta: dict) -> None:
    """Everything the app reads. Each file is written atomically; build_meta.json goes last."""
    out = Path(out_dir)
    atomic_write_parquet(res["pool"], out / "player_pool.parquet")
    atomic_write_parquet(res["lineups"], out / "lineups.parquet")
    atomic_write_parquet(res["swaps"], out / "swaps.parquet")
    atomic_save_npy(res["sims"][:N_SIMS_PUBLISHED].astype(np.float16), out / "sims.npy")
    atomic_save_npy(np.asarray(res["field"]).astype(np.int16), out / "field.npy")
    rec = res["lineups"][res["lineups"]["rank"] == 0]
    write_upload_csv([g for _, g in rec.groupby("contest_key", sort=False)], out / "dk_upload_recommended.csv")
    atomic_write_text(out / "build_meta.json", json.dumps(meta, indent=2, default=str))
