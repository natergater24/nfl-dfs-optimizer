"""Load the NBA engine's published files (data/published/nba) for the app and regenerate the simulations."""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from nbadfs.build import sims_fingerprint
from nbadfs.simulate import simulate
from nfldfs import config
from nfldfs.sim_eval import lineup_scores
from nfldfs_app.ui import EASTERN, to_eastern

LINEUP_INFO = ["name", "team", "opp", "game", "positions", "slots", "salary", "median", "floor", "ceiling",
               "own_pct", "tier", "playable", "status"]
LINEUP_INJURY = ["inj_tag", "inj_class", "lean", "body_part", "news_headline", "news_story", "news_published"]


def published_dir() -> Path:
    env = os.environ.get("NFLDFS_PUBLISHED")
    return Path(env) / "nba" if env else config.PUBLISHED / "nba"


def _json(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def load_slates(nba_dir: Path) -> list[dict] | None:
    """Today's slates from slates.json; None when nothing was ever published, [] on an off day."""
    return _json(Path(nba_dir) / "slates.json")


def load_run_status(nba_dir: Path) -> dict:
    return _json(Path(nba_dir) / "run_status.json") or {}


def default_slate(slates: list[dict], now_et: dt.datetime) -> int:
    """Index of the first published slate that hasn't started yet, else the last published one (0 if none)."""
    if now_et.tzinfo is None:
        now_et = now_et.replace(tzinfo=EASTERN)
    published = [i for i, s in enumerate(slates) if s.get("published")]
    for i in published:
        start = to_eastern(slates[i].get("start"))
        if start is not None and start > now_et:
            return i
    return published[-1] if published else 0


def slate_label(s: dict) -> str:
    start = to_eastern(s.get("start"))
    when = f"{start.hour % 12 or 12}:{start:%M} {'AM' if start.hour < 12 else 'PM'} ET" if start else "time TBD"
    return f"{s.get('name', 'Slate')} · {when} · {s.get('games', '?')} games"


@dataclass
class SlateData:
    dg: int
    pool: pd.DataFrame
    lineups: pd.DataFrame
    swaps: pd.DataFrame
    field: np.ndarray
    meta: dict
    row_of: dict = dc_field(default_factory=dict)
    backups: pd.DataFrame = dc_field(default_factory=pd.DataFrame)     # injury_backups.parquet (empty for old builds)

    def __post_init__(self):
        self.row_of = {int(d): i for i, d in enumerate(self.pool["dk_id"])}


def slate_stamp(nba_dir: Path, dg) -> tuple:
    folder = Path(nba_dir) / str(dg)
    return tuple((f.name, f.stat().st_mtime) for f in sorted(folder.glob("*")) if f.is_file())


def load_slate(nba_dir: Path, dg) -> SlateData:
    """One slate's published files. The pool is read as-is: its row order is the order the build simulated."""
    folder = Path(nba_dir) / str(dg)
    pool = pd.read_parquet(folder / "pool.parquet")
    pool["slots"] = [list(s) for s in pool["slots"]]
    extra = [c for c in LINEUP_INJURY if c in pool.columns]          # builds made before injury tags have none
    lineups = pd.read_parquet(folder / "lineups.parquet").merge(pool[["dk_id", *LINEUP_INFO, *extra]], on="dk_id",
                                                                how="left")
    bk = folder / "injury_backups.parquet"
    return SlateData(dg=int(dg), pool=pool, lineups=lineups, swaps=pd.read_parquet(folder / "swaps.parquet"),
                     field=np.load(folder / "field.npy").astype(np.int64),
                     meta=_json(folder / "build_meta.json") or {},
                     backups=pd.read_parquet(bk) if bk.exists() else pd.DataFrame())


@st.cache_resource(show_spinner=False, max_entries=4)
def _sims(dg: int, built_at: str, n_sims: int, seed: int, _pool: pd.DataFrame) -> np.ndarray:
    return simulate(_pool, n_sims, seed)


def sims_for(slate: SlateData) -> np.ndarray:
    """The build's simulations, regenerated from the published pool + seed (cached per slate build)."""
    m = slate.meta
    return _sims(slate.dg, str(m.get("built_at_utc", "")), int(m["n_sims"]), int(m["seed"]), slate.pool)


def sims_mismatch(slate: SlateData) -> bool:
    """True when the regenerated sims differ from the Mac's build (different numpy). Old builds w/o a fingerprint: False."""
    want = slate.meta.get("sims_fingerprint")
    return bool(want) and sims_fingerprint(sims_for(slate)) != want


@st.cache_resource(show_spinner=False, max_entries=4)
def _field_scores(dg: int, built_at: str, n_sims: int, seed: int, _sims_arr, _field) -> np.ndarray:
    return lineup_scores(_sims_arr, _field)


def field_scores_for(slate: SlateData) -> np.ndarray:
    m = slate.meta
    return _field_scores(slate.dg, str(m.get("built_at_utc", "")), int(m["n_sims"]), int(m["seed"]),
                         sims_for(slate), slate.field)
