"""Nathan's own DraftKings Classic entries: find them in a contest-standings export, link each to the app
lineup it came from, and keep money and results.

Standings files list every user in the contest. Only rows whose EntryName is Nathan's username are kept, and the
username itself is never stored or returned."""
from __future__ import annotations

import datetime as dt
import fnmatch
import io
import os
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
ENTRY_HISTORY_COLUMNS = ["Sport", "Game_Type", "Entry_Key", "Entry", "Contest_Key", "Contest_Date_EST", "Place",
                         "Points", "Winnings_Non_Ticket", "Winnings_Ticket", "Contest_Entries", "Entry_Fee",
                         "Prize_Pool", "Places_Paid"]
ENTRY_HISTORY_GLOB = "draftkings-contest-entry-history*.csv"
ENTRY_HISTORY_REQUIRED = ENTRY_HISTORY_COLUMNS[:12]
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
        # The archive holds every build of the slate (built_at); older archives hold one build without it.
        lus = slate_lineups if "built_at" in slate_lineups.columns else slate_lineups.assign(built_at="")
        groups = list(lus.assign(built_at=lus["built_at"].fillna("").astype(str))
                      .groupby(["built_at", "contest_key", "rank"], sort=False))
        groups.sort(key=lambda g: int(g[0][2]))
        groups.sort(key=lambda g: g[0][0], reverse=True)          # latest build first
        groups.sort(key=lambda g: g[0][1] != prefer)              # the entry's own contest type first
        for (_, key, rank), g in groups:
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


def _header_text(source) -> str:
    """The first line of a CSV given as text or as a path ('' if it can't be read as text)."""
    if isinstance(source, str) and ("\n" in source or "," in source):
        return source.split("\n", 1)[0]
    try:
        with open(source, "rb") as fh:
            head = fh.read(4096)
    except (OSError, ValueError):
        return ""
    if head.startswith(b"PK"):
        return ""
    return head.decode("utf-8-sig", errors="replace").split("\n", 1)[0]


def find_entry_history(downloads) -> list[Path]:
    """Entry-history downloads waiting in the Downloads folder (the name repeats, so imported files are moved
    away). Raises PermissionError instead of looking empty."""
    downloads = Path(downloads)
    found = [downloads / n for n in os.listdir(downloads) if fnmatch.fnmatch(n, ENTRY_HISTORY_GLOB)]
    return sorted(found, key=lambda p: p.stat().st_mtime)


def is_entry_history(text_or_path) -> bool:
    header = _header_text(text_or_path)
    return "Entry_Key" in header and "Winnings_Non_Ticket" in header


def _money(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(r"[$,\s]", "", regex=True), errors="coerce")


def read_entry_history(path) -> tuple[pd.DataFrame, int]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in ENTRY_HISTORY_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"This doesn't look like a DraftKings entry-history file (missing columns: {missing})")
    keep = (df["Sport"].str.strip() == "NFL") & (df["Game_Type"].str.strip() == "Classic")
    skipped = int((~keep).sum())
    df = df[keep]
    field = pd.to_numeric(df["Contest_Entries"].str.replace(",", ""), errors="coerce")
    names = df["Entry"].str.strip()
    won = _money(df["Winnings_Non_Ticket"]).fillna(0) + _money(df["Winnings_Ticket"]).fillna(0)
    has_win = _money(df["Winnings_Non_Ticket"]).notna() | _money(df["Winnings_Ticket"]).notna()
    rows = pd.DataFrame({
        "entry_id": df["Entry_Key"].str.strip().to_numpy(),
        "contest_id": df["Contest_Key"].str.strip().to_numpy(),
        "slate_date": df["Contest_Date_EST"].str.strip().str[:10].to_numpy(),
        "contest_name": names.to_numpy(),
        "contest_type": [guess_contest_type(n, f) for n, f in zip(names, field)],
        "entry_fee": _money(df["Entry_Fee"]).to_numpy(),
        "winnings": won.where(has_win).to_numpy(),
        "place": pd.to_numeric(df["Place"].str.replace(",", ""), errors="coerce").to_numpy(),
        "field_size": field.to_numpy(),
        "points": pd.to_numeric(df["Points"], errors="coerce").to_numpy(),
        "players": "", "projected": np.nan, "lineup_source": "No standings imported", "typed_fields": ""})
    return _coerce(rows), skipped


def merge_entry_history(path, rows: pd.DataFrame) -> pd.DataFrame:
    """Upsert entry-history rows by entry_id. DraftKings' own fee and winnings beat anything typed; typed name and
    type are kept; lineup fields (players, projected, lineup_source) are never touched."""
    stored = load_entries(path).to_dict("records")
    index = {str(r["entry_id"]): i for i, r in enumerate(stored)}
    for rec in _coerce(rows).to_dict("records"):
        i = index.get(str(rec["entry_id"]))
        if i is None:
            stored.append(rec)
            index[str(rec["entry_id"])] = len(stored) - 1
            continue
        cur = stored[i]
        typed = set(filter(None, str(cur.get("typed_fields") or "").split(",")))
        for c in ("entry_fee", "winnings"):
            if not _blank(rec.get(c)):
                cur[c] = rec[c]
                typed.discard(c)
        for c in ("place", "points", "field_size", "contest_id"):
            if not _blank(rec.get(c)):
                cur[c] = rec[c]
        for c in ("contest_name", "contest_type"):
            if c not in typed and _blank(cur.get(c)) and not _blank(rec.get(c)):
                cur[c] = rec[c]
        cur["typed_fields"] = ",".join(sorted(typed))
    out = _coerce(pd.DataFrame(stored, columns=ENTRY_COLUMNS)) if stored else empty_entries()
    atomic_write_parquet(out, path)
    return out


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
