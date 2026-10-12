"""Import DraftKings contest-standings exports → actual ownership/points → history + report card.

Standings files contain other users' names; only the per-player block is read and nothing user-specific
is kept."""
from __future__ import annotations

import datetime as dt
import fnmatch
import io
import os
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .status import atomic_write_parquet
from .teams import normalize_name

STANDINGS_GLOB = "contest-standings-*.zip"
REQUIRED_COLUMNS = ("Player", "%Drafted", "FPTS")
HISTORY_COLUMNS = ["slate_date", "draft_group_id", "dk_id", "name", "position", "team", "salary", "median",
                   "floor", "ceiling", "own_pct", "implied_total", "opp_implied", "actual_own", "actual_pts"]
_SNAPSHOT = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\w+)\.parquet$")


def find_new_standings(downloads, done_dir) -> list[Path]:
    downloads, done_dir = Path(downloads), Path(done_dir)
    names = os.listdir(downloads)                     # raises PermissionError instead of looking empty
    done = set(os.listdir(done_dir)) if done_dir.exists() else set()
    found = [downloads / n for n in names if fnmatch.fnmatch(n, STANDINGS_GLOB) and n not in done]
    return sorted(found, key=lambda p: p.stat().st_mtime)


def read_standings(path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            members = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not members:
                raise ValueError(f"{path.name} has no CSV inside — is it a DraftKings contest standings export?")
            text = z.read(members[0]).decode("utf-8-sig")
    else:
        text = path.read_text(encoding="utf-8-sig")
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"This doesn't look like a DraftKings contest standings export "
                         f"(missing columns: {missing})")
    df = df[df["Player"].str.strip() != ""]
    out = pd.DataFrame({
        "name": df["Player"].str.strip(),
        "roster_position": (df["Roster Position"].str.strip() if "Roster Position" in df.columns else ""),
        "actual_own": pd.to_numeric(df["%Drafted"].str.replace("%", "", regex=False), errors="coerce"),
        "actual_pts": pd.to_numeric(df["FPTS"], errors="coerce"),
    })
    return out.drop_duplicates("name").reset_index(drop=True)


def snapshot_key(path) -> tuple[str, str]:
    m = _SNAPSHOT.match(Path(path).name)
    if not m:
        raise ValueError(f"Not a slate snapshot file name: {Path(path).name}")
    return m.group(1), m.group(2)


def latest_slate_snapshot(slates_dir, as_of: dt.date) -> Path | None:
    best = None
    for p in Path(slates_dir).glob("*.parquet"):
        m = _SNAPSHOT.match(p.name)
        if m and dt.date.fromisoformat(m.group(1)) <= as_of and (best is None or m.group(1) > best[0]):
            best = (m.group(1), p)
    return best[1] if best else None


def match_to_slate(standings: pd.DataFrame, snapshot: pd.DataFrame, slate_date: str,
                   draft_group_id) -> pd.DataFrame:
    actual = standings.assign(k=standings["name"].map(normalize_name)).drop_duplicates("k").set_index("k")
    snap = snapshot[snapshot["playable"]].copy() if "playable" in snapshot.columns else snapshot.copy()
    k = snap["name"].map(normalize_name)
    snap["actual_own"] = k.map(actual["actual_own"]).fillna(0.0)
    snap["actual_pts"] = k.map(actual["actual_pts"])
    snap["slate_date"] = slate_date
    snap["draft_group_id"] = str(draft_group_id)
    return snap[HISTORY_COLUMNS].reset_index(drop=True)


def append_history(history_path, rows: pd.DataFrame) -> pd.DataFrame:
    history_path = Path(history_path)
    hist = pd.concat([pd.read_parquet(history_path), rows], ignore_index=True) if history_path.exists() \
        else rows.copy()
    hist = hist.drop_duplicates(["slate_date", "dk_id"], keep="last").reset_index(drop=True)
    atomic_write_parquet(hist, history_path)
    return hist


def _card(df: pd.DataFrame) -> dict:
    out = {"players": int(len(df))}
    pts = df.dropna(subset=["actual_pts"])
    out["scored"] = int(len(pts))
    if len(pts):
        err = pts["actual_pts"] - pts["median"]
        out["proj_mae"] = round(float(err.abs().mean()), 2)
        out["proj_bias"] = round(float(err.mean()), 2)
        inside = (pts["actual_pts"] >= pts["floor"]) & (pts["actual_pts"] <= pts["ceiling"])
        out["in_range_pct"] = round(float(inside.mean() * 100), 1)
    own = df.dropna(subset=["actual_own"])
    if len(own):
        out["own_mae"] = round(float((own["actual_own"] - own["own_pct"]).abs().mean()), 2)
        corr = float(own["actual_own"].corr(own["own_pct"])) if len(own) > 2 else float("nan")
        out["own_corr"] = None if np.isnan(corr) else round(corr, 3)
    return out


def report_card(history: pd.DataFrame) -> dict:
    if history.empty:
        return {"weeks": 0}
    latest = str(history["slate_date"].max())
    return {"weeks": int(history["slate_date"].nunique()), "latest_slate": latest,
            "latest": _card(history[history["slate_date"] == latest]), "season": _card(history)}
