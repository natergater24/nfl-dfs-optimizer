"""One NBA slate end to end (salaries + lines + rates -> pool, sims, field, lineups, swaps) and its published files."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from nfldfs.injuries import apply_play_prob, classify
from nfldfs.lineups import BACKUP_COLUMNS
from nfldfs.status import atomic_save_npy, atomic_write_parquet, atomic_write_text

from .config import FIELD_SIZE, N_SIMS, SEED
from .dk import parse_salaries
from .lineups import N_CANDIDATES, build_all, rank0_backups
from .ownership import add_ownership, sample_field
from .project import project
from .simulate import simulate, summarize
from .stats import match_rates

log = logging.getLogger("nbadfs.build")

PUBLISHED_FILES = ["pool.parquet", "lineups.parquet", "swaps.parquet", "injury_backups.parquet", "field.npy",
                   "build_meta.json"]
# Extras the pipeline fetches (Sleeper + ESPN, see nfldfs.injuries.add_injury_columns), merged by dk_id.
INJURY_INFO_COLUMNS = ["lean", "body_part", "injury_updated", "espn_id", "news_headline", "news_story",
                       "news_published"]


def sims_fingerprint(sims: np.ndarray) -> str:
    """sha256 of the first 64 simulated rows: lets another machine tell whether numpy regenerated the same sims."""
    return hashlib.sha256(np.ascontiguousarray(sims[:64]).tobytes()).hexdigest()


def with_injuries(base: pd.DataFrame, injury_info: pd.DataFrame | None = None) -> pd.DataFrame:
    """DraftKings tags (inj_tag, inj_class, recommendable, play_prob) on the parsed salaries, plus any news
    extras from `injury_info` (rows keyed by dk_id); missing extras are blank."""
    out = base.copy()
    info = None
    if injury_info is not None and len(injury_info) and "dk_id" in injury_info.columns:
        info = injury_info.drop_duplicates("dk_id")
        info = info.set_index(info["dk_id"].astype("int64"))
    for col in INJURY_INFO_COLUMNS:
        vals = (out["dk_id"].astype("int64").map(info[col]) if info is not None and col in info.columns
                else pd.Series("", index=out.index))
        out[col] = vals.fillna("").astype(str).to_numpy()
    return classify(out)


def build_slate(salaries_text: str, lines: pd.DataFrame, rates_last: pd.DataFrame, rates_cur: pd.DataFrame, *,
                n_sims: int = N_SIMS, seed: int = SEED, field_size: int = FIELD_SIZE,
                n_candidates: int = N_CANDIDATES, injury_info: pd.DataFrame | None = None) -> dict:
    """Returns pool (row order == the order `simulate` saw), sims (not published), lineups, swaps,
    injury_backups, field, meta. Pure: injury news (lean etc.) comes in through `injury_info`; without it
    the DraftKings tags alone still decide who is suggested and who sits in some sims."""
    base = with_injuries(parse_salaries(salaries_text), injury_info)
    matched, match_rate = match_rates(base, rates_last, rates_cur)
    proj = project(base, lines, matched).reset_index(drop=True)
    raw = simulate(proj, n_sims, seed, sit=False)
    pool = add_ownership(summarize(raw, proj))           # displayed numbers: when he plays
    sims = apply_play_prob(raw, proj, seed)                 # == simulate(pool, n_sims, seed), as the app regenerates
    del raw
    field = sample_field(pool, field_size, np.random.default_rng(seed)).astype(np.int32)
    lineups, swaps = build_all(pool, sims, field, n_candidates=n_candidates, seed=seed)
    try:    # backups must never fail a slate: without them the app computes them on the device
        backups = rank0_backups(pool, sims, field, lineups)
    except Exception:  # noqa: BLE001
        log.exception("injury backups failed; the app will compute them on the device")
        backups = pd.DataFrame(columns=["contest_key", *BACKUP_COLUMNS])
    meta = {"n_sims": int(n_sims), "seed": int(seed), "stats_match_rate": float(match_rate),
            "sims_fingerprint": sims_fingerprint(sims),
            "built_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    return {"pool": pool, "sims": sims, "lineups": lineups, "swaps": swaps, "injury_backups": backups,
            "field": field, "meta": meta}


def write_published(res: dict, out_dir) -> None:
    """The per-slate files; each written atomically. No sims file (the app regenerates them from pool + seed)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_parquet(res["pool"], out / "pool.parquet")
    atomic_write_parquet(res["lineups"], out / "lineups.parquet")
    atomic_write_parquet(res["swaps"], out / "swaps.parquet")
    if "injury_backups" in res:
        atomic_write_parquet(res["injury_backups"], out / "injury_backups.parquet")
    atomic_save_npy(res["field"].astype(np.int32), out / "field.npy")
    atomic_write_text(out / "build_meta.json", json.dumps(res["meta"], indent=2, default=str))
