"""One NBA slate end to end (salaries + lines + rates -> pool, sims, field, lineups, swaps) and its published files."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from nfldfs.status import atomic_save_npy, atomic_write_parquet, atomic_write_text

from .config import FIELD_SIZE, N_SIMS, SEED
from .dk import parse_salaries
from .lineups import N_CANDIDATES, build_all
from .ownership import add_ownership, sample_field
from .project import project
from .simulate import simulate, summarize
from .stats import match_rates

PUBLISHED_FILES = ["pool.parquet", "lineups.parquet", "swaps.parquet", "field.npy", "build_meta.json"]


def sims_fingerprint(sims: np.ndarray) -> str:
    """sha256 of the first 64 simulated rows: lets another machine tell whether numpy regenerated the same sims."""
    return hashlib.sha256(np.ascontiguousarray(sims[:64]).tobytes()).hexdigest()


def build_slate(salaries_text: str, lines: pd.DataFrame, rates_last: pd.DataFrame, rates_cur: pd.DataFrame, *,
                n_sims: int = N_SIMS, seed: int = SEED, field_size: int = FIELD_SIZE,
                n_candidates: int = N_CANDIDATES) -> dict:
    """Returns pool (row order == the order `simulate` saw), sims (not published), lineups, swaps, field, meta."""
    base = parse_salaries(salaries_text)
    matched, match_rate = match_rates(base, rates_last, rates_cur)
    proj = project(base, lines, matched).reset_index(drop=True)
    sims = simulate(proj, n_sims, seed)
    pool = add_ownership(summarize(sims, proj))
    field = sample_field(pool, field_size, np.random.default_rng(seed)).astype(np.int32)
    lineups, swaps = build_all(pool, sims, field, n_candidates=n_candidates, seed=seed)
    meta = {"n_sims": int(n_sims), "seed": int(seed), "stats_match_rate": float(match_rate),
            "sims_fingerprint": sims_fingerprint(sims),
            "built_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    return {"pool": pool, "sims": sims, "lineups": lineups, "swaps": swaps, "field": field, "meta": meta}


def write_published(res: dict, out_dir) -> None:
    """The per-slate files; each written atomically. No sims file (the app regenerates them from pool + seed)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_parquet(res["pool"], out / "pool.parquet")
    atomic_write_parquet(res["lineups"], out / "lineups.parquet")
    atomic_write_parquet(res["swaps"], out / "swaps.parquet")
    atomic_save_npy(res["field"].astype(np.int32), out / "field.npy")
    atomic_write_text(out / "build_meta.json", json.dumps(res["meta"], indent=2, default=str))
