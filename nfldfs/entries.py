"""Nathan's own DraftKings Classic entries: find them in a contest-standings export, link each to the app
lineup it came from, and keep money and results.

Standings files list every user in the contest. Only rows whose EntryName is Nathan's username are kept, and the
username itself is never stored or returned."""
from __future__ import annotations

import datetime as dt
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CONTEST_TYPES
from .status import atomic_write_parquet
from .teams import normalize_name

ENTRY_COLUMNS = ["entry_id", "contest_id", "slate_date", "contest_name", "contest_type", "entry_fee", "winnings",
                 "place", "field_size", "points", "players", "projected", "lineup_source", "typed_fields"]
NUMERIC = ("entry_fee", "winnings", "place", "field_size", "points", "projected")
EDITABLE = ("entry_fee", "winnings", "contest_type", "contest_name")
ENTRY_SOURCE_COLUMNS = ("EntryId", "EntryName", "Rank", "Points", "Lineup")
SLOT_POSITIONS = {"QB": ("QB",), "RB": ("RB",), "WR": ("WR",), "TE": ("TE",), "FLEX": ("RB", "WR", "TE"),
                  "DST": ("DST",)}
TYPE_KEYWORDS = (("head-to-head", "h2h"), ("h2h", "h2h"), ("50/50", "fifty_fifty"), ("double up", "double_up"),
                 ("triple up", "multiplier_3x"), ("quintuple", "multiplier_5x"), ("10x", "multiplier_10x"),
                 ("millionaire", "large_tournament"), ("single entry", "single_entry"),
                 ("3 entry max", "single_entry"), ("3-max", "single_entry"))
LARGE_FIELD = 20_000
_SLOT = re.compile(r"(?:^|\s)(QB|RB|WR|TE|FLEX|DST)\s+")
_CONTEST_ID = re.compile(r"contest-standings-(\d+)")


def empty_entries() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="float64" if c in NUMERIC else "object") for c in ENTRY_COLUMNS})


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ENTRY_COLUMNS:
        if c not in df.columns:
            df[c] = float("nan") if c in NUMERIC else ""
        if c in NUMERIC:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
        else:
            df[c] = df[c].fillna("").astype(str)
    return df[ENTRY_COLUMNS]


def load_entries(path) -> pd.DataFrame:
    path = Path(path)
    return _coerce(pd.read_parquet(path)) if path.exists() else empty_entries()


def contest_id_from(path) -> str:
    m = _CONTEST_ID.search(Path(path).name)
    return m.group(1) if m else ""


def guess_contest_type(name: str, field_size=None) -> str:
    n = (name or "").lower()
    for keyword, key in TYPE_KEYWORDS:
        if keyword in n:
            return key
    if field_size is not None and not pd.isna(field_size):
        if int(field_size) == 2:
            return "h2h"
        if int(field_size) >= LARGE_FIELD:
            return "large_tournament"
    return "tournament" if n else ""


def parse_lineup(text) -> list[tuple[str, str]]:
    parts = _SLOT.split(" " + str(text or "").strip())
    it = iter(parts[1:])
    return [(slot, name.strip()) for slot, name in zip(it, it)]


def read_my_entries(text: str, username: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    missing = [c for c in ENTRY_SOURCE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"This contest standings file is missing columns {missing}")
    rows = df[df["EntryId"].str.strip() != ""]
    base = rows["EntryName"].str.split(" (", n=1, regex=False).str[0].str.strip().str.lower()
    mine = rows[base == username.strip().lower()]
    return pd.DataFrame({"entry_id": mine["EntryId"].str.strip().to_numpy(),
                         "place": pd.to_numeric(mine["Rank"], errors="coerce").to_numpy(),
                         "points": pd.to_numeric(mine["Points"], errors="coerce").to_numpy(),
                         "lineup": mine["Lineup"].to_numpy(),
                         "field_size": np.full(len(mine), float(len(rows)))})


def match_lineup_ids(pairs, snapshot: pd.DataFrame) -> list:
    keys = snapshot["name"].map(normalize_name)
    ids = []
    for slot, name in pairs:
        hit = snapshot[(keys == normalize_name(name)) & snapshot["position"].isin(SLOT_POSITIONS.get(slot, ()))]
        ids.append(int(hit["dk_id"].iloc[0]) if len(hit) else None)
    return ids


def lineup_source(ids, slate_lineups, my_builds=None, prefer: str = "") -> str:
    if not ids or any(i is None for i in ids):
        return "Not from the app"
    target = frozenset(int(i) for i in ids)
    if slate_lineups is not None and len(slate_lineups):
        groups = list(slate_lineups.groupby(["contest_key", "rank"], sort=False))
        groups.sort(key=lambda g: (g[0][0] != prefer, int(g[0][1])))
        for (key, rank), g in groups:
            if frozenset(int(x) for x in g["dk_id"]) == target:
                label = CONTEST_TYPES.get(key, {}).get("label", key)
                return f"Recommended {label}" if int(rank) == 0 else f"Alternate #{int(rank) + 1} · {label}"
    if my_builds is not None and len(my_builds):
        for players in my_builds["players"]:
            if frozenset(int(x) for x in str(players).split(",") if x) == target:
                return "My Lineup build"
    return "Not from the app"


def build_entry_rows(mine: pd.DataFrame, snapshot: pd.DataFrame, slate_lineups, my_builds, slate_date: str,
                     contest_id: str, contest: dict | None = None) -> pd.DataFrame:
    contest = contest or {}
    name = str(contest.get("contest_name") or "")
    fee = contest.get("entry_fee")
    medians = snapshot.set_index("dk_id")["median"]
    rows = []
    for r in mine.itertuples(index=False):
        ids = match_lineup_ids(parse_lineup(r.lineup), snapshot)
        complete = len(ids) == 9 and all(i is not None for i in ids)
        ctype = guess_contest_type(name, r.field_size)
        rows.append({
            "entry_id": str(r.entry_id), "contest_id": str(contest_id), "slate_date": str(slate_date),
            "contest_name": name, "contest_type": ctype,
            "entry_fee": float(fee) if fee is not None and not pd.isna(fee) else np.nan, "winnings": np.nan,
            "place": float(r.place), "field_size": float(r.field_size), "points": float(r.points),
            "players": ",".join(str(i) for i in ids if i is not None),
            "projected": float(medians.reindex(ids).sum()) if complete else np.nan,
            "lineup_source": lineup_source(ids, slate_lineups, my_builds, prefer=ctype),
            "typed_fields": ""})
    return _coerce(pd.DataFrame(rows, columns=ENTRY_COLUMNS)) if rows else empty_entries()


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or v == ""


def upsert_entries(path, new: pd.DataFrame) -> pd.DataFrame:
    """Add new entries; update existing ones (by entry_id). Typed values are never replaced by an import, and
    a blank imported value never erases anything."""
    rows = load_entries(path).to_dict("records")
    index = {str(r["entry_id"]): i for i, r in enumerate(rows)}
    for rec in _coerce(new).to_dict("records"):
        i = index.get(str(rec["entry_id"]))
        if i is None:
            rows.append(rec)
            index[str(rec["entry_id"])] = len(rows) - 1
            continue
        typed = set(filter(None, str(rows[i].get("typed_fields") or "").split(",")))
        for c in ENTRY_COLUMNS:
            if c in ("entry_id", "typed_fields") or c in typed or _blank(rec.get(c)):
                continue
            rows[i][c] = rec[c]
    out = _coerce(pd.DataFrame(rows, columns=ENTRY_COLUMNS)) if rows else empty_entries()
    atomic_write_parquet(out, path)
    return out


def update_entry(path, entry_id: str, **fields) -> pd.DataFrame:
    bad = set(fields) - set(EDITABLE)
    if bad:
        raise ValueError(f"These fields can't be edited: {sorted(bad)}")
    cur = load_entries(path)
    match = cur.index[cur["entry_id"] == str(entry_id)]
    if not len(match):
        raise KeyError(f"No entry {entry_id}")
    i = match[0]
    typed = set(filter(None, cur.at[i, "typed_fields"].split(",")))
    for k, v in fields.items():
        cur.at[i, k] = v
        typed.add(k)
    cur.at[i, "typed_fields"] = ",".join(sorted(typed))
    cur = _coerce(cur)
    atomic_write_parquet(cur, path)
    return cur


def add_manual_entry(path, *, slate_date, contest_name, contest_type, entry_fee, winnings, players="",
                     projected=np.nan, lineup_source="Not from the app") -> pd.DataFrame:
    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S%f")
    row = {"entry_id": f"manual-{stamp}", "contest_id": "", "slate_date": str(slate_date),
           "contest_name": contest_name, "contest_type": contest_type, "entry_fee": entry_fee, "winnings": winnings,
           "place": np.nan, "field_size": np.nan, "points": np.nan, "players": players, "projected": projected,
           "lineup_source": lineup_source, "typed_fields": "contest_name,contest_type,entry_fee,winnings"}
    return upsert_entries(path, pd.DataFrame([row], columns=ENTRY_COLUMNS))


def summary(entries: pd.DataFrame) -> dict:
    e = _coerce(entries) if len(entries) else empty_entries()
    done = e[e["winnings"].notna()]
    fees, won = float(done["entry_fee"].fillna(0).sum()), float(done["winnings"].sum())
    cashed = int((done["winnings"] > 0).sum())
    scored = e[e["points"].notna() & e["projected"].notna()]
    return {"entries": int(len(e)), "settled": int(len(done)), "cashed": cashed,
            "cash_rate": cashed / len(done) if len(done) else None, "fees": fees, "winnings": won,
            "profit": won - fees, "roi": (won - fees) / fees if fees else None,
            "avg_points": float(e["points"].mean()) if e["points"].notna().any() else None,
            "avg_vs_projected": float((scored["points"] - scored["projected"]).mean()) if len(scored) else None,
            "waiting": int(len(e) - len(done))}


def type_label(key: str) -> str:
    return CONTEST_TYPES.get(key, {}).get("label") or ("Type not set" if not key else key)


def summary_by_type(entries: pd.DataFrame) -> list[dict]:
    if not len(entries):
        return []
    e = _coerce(entries)
    return [{"contest_type": key, "label": type_label(key), **summary(g)}
            for key, g in e.groupby("contest_type", sort=False)]
