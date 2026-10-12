"""Load the engine's published files for the app (local Mac or Streamlit Cloud)."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

import numpy as np
import pandas as pd

from nfldfs import config

REQUIRED_FILES = ("player_pool.parquet", "lineups.parquet", "swaps.parquet", "sims.npy", "field.npy",
                  "build_meta.json")
OPTIONAL_FILES = ("run_status.json", "results_status.json", "report_card.json")
MATCHUP_DEFAULTS = {"mu_label": "Neutral", "mu_color": "#8a8a3d", "mu_text": ""}


def published_dir() -> Path:
    return Path(os.environ.get("NFLDFS_PUBLISHED", str(config.PUBLISHED)))


def is_hosted() -> bool:
    forced = os.environ.get("NFLDFS_FORCE_HOSTED")
    if forced is not None:
        return forced == "1"
    return shutil.which("caffeinate") is None      # macOS-only binary; absent on Streamlit Cloud (MLB pattern)


def missing_files(pub: Path) -> list[str]:
    return [f for f in REQUIRED_FILES if not (Path(pub) / f).exists()]


def stamp(pub: Path) -> tuple:
    pub = Path(pub)
    return tuple((f, (pub / f).stat().st_mtime if (pub / f).exists() else 0.0)
                 for f in (*REQUIRED_FILES, *OPTIONAL_FILES))


def _json(p: Path) -> dict:
    return json.loads(p.read_text()) if p.exists() else {}


@dataclass
class AppData:
    pool: pd.DataFrame
    lineups: pd.DataFrame
    swaps: pd.DataFrame
    sims: np.ndarray
    field: np.ndarray
    meta: dict
    run_status: dict
    results_status: dict
    report_card: dict
    row_of: dict = dc_field(default_factory=dict)

    def __post_init__(self):
        self.row_of = {int(d): i for i, d in enumerate(self.pool["dk_id"])}


def load(pub: Path) -> AppData:
    pub = Path(pub)
    pool = pd.read_parquet(pub / "player_pool.parquet")
    for col, default in MATCHUP_DEFAULTS.items():          # builds made before matchups existed
        if col not in pool.columns:
            pool[col] = default
    lineups = pd.read_parquet(pub / "lineups.parquet").merge(
        pool[["dk_id", *MATCHUP_DEFAULTS]], on="dk_id", how="left")
    return AppData(pool=pool, lineups=lineups, swaps=pd.read_parquet(pub / "swaps.parquet"),
                   sims=np.load(pub / "sims.npy").astype(np.float32),
                   field=np.load(pub / "field.npy").astype(np.int64),
                   meta=_json(pub / "build_meta.json"), run_status=_json(pub / "run_status.json"),
                   results_status=_json(pub / "results_status.json"),
                   report_card=_json(pub / "report_card.json"))


def minutes_since(iso: str | None, now: dt.datetime | None = None) -> float | None:
    if not iso:
        return None
    then = dt.datetime.fromisoformat(str(iso))
    if now is None:
        now = dt.datetime.now(then.tzinfo) if then.tzinfo else dt.datetime.now()
    return (now - then).total_seconds() / 60
