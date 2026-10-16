"""Week-by-week history of every player the app projected: projection, matchup, ownership and actual result."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .status import atomic_write_parquet
from .teams import normalize_name

PW_COLUMNS = ["slate_date", "dk_id", "name", "position", "team", "opp", "salary", "median", "floor", "ceiling",
              "own_pct", "mu_label", "mu_color", "actual_pts", "actual_own"]
NUMERIC = ("salary", "median", "floor", "ceiling", "own_pct", "actual_pts", "actual_own")
TABLE_COLUMNS = ["Slate", "Matchup", "Salary", "Projected", "Actual", "+/−", "Own est.", "Own actual", "My entry",
                 "mu_color"]


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in PW_COLUMNS:
        if c == "dk_id":
            df[c] = df[c].astype("int64")
        elif c in NUMERIC:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
        else:
            df[c] = df[c].fillna("").astype(str)
    return df[PW_COLUMNS]


def empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="int64" if c == "dk_id" else "float64" if c in NUMERIC else "object")
                         for c in PW_COLUMNS})


def load(path) -> pd.DataFrame:
    path = Path(path)
    return _coerce(pd.read_parquet(path)) if path.exists() else empty()


def slate_rows(pool: pd.DataFrame, slate_date: str) -> pd.DataFrame:
    p = pool[pool["playable"]].copy()
    if "mu_label" not in p.columns:
        p["mu_label"] = "Neutral"
    if "mu_color" not in p.columns:
        p["mu_color"] = "#8a8a3d"
    p["slate_date"] = str(slate_date)
    p["actual_pts"] = np.nan
    p["actual_own"] = np.nan
    return _coerce(p.reset_index(drop=True))


def upsert_slate(path, rows: pd.DataFrame) -> pd.DataFrame:
    cur = load(path)
    if not len(rows):
        return cur
    date = rows["slate_date"].iloc[0]
    kept = cur[cur["slate_date"] == date][["dk_id", "actual_pts", "actual_own"]]
    fresh = rows.drop(columns=["actual_pts", "actual_own"]).merge(kept, on="dk_id", how="left")
    other = cur[cur["slate_date"] != date]
    parts = [d for d in (other, fresh) if len(d)]
    out = _coerce(pd.concat(parts, ignore_index=True) if parts else empty())
    atomic_write_parquet(out, path)
    return out


def set_actuals(path, slate_date: str, actuals: pd.DataFrame) -> int:
    cur = load(path)
    on_slate = cur["slate_date"] == str(slate_date)
    updated = 0
    for col in ("actual_pts", "actual_own"):
        if col not in actuals.columns:
            continue
        values = actuals.dropna(subset=[col]).drop_duplicates("dk_id").set_index("dk_id")[col]
        hit = on_slate & cur["dk_id"].isin(values.index)
        cur.loc[hit, col] = cur.loc[hit, "dk_id"].map(values)
        updated = max(updated, int(hit.sum()))
    atomic_write_parquet(_coerce(cur), path)
    return updated


def nflverse_actuals(rows: pd.DataFrame, stats_week: pd.DataFrame) -> pd.DataFrame:
    """DK points from nflverse for the slate's non-DST players (name+team+position, then name+position)."""
    stats = stats_week.assign(key=stats_week["name"].map(normalize_name))
    by_team = stats.drop_duplicates(["key", "team", "position"]).set_index(["key", "team", "position"])["dk_pts"]
    by_pos = stats.drop_duplicates(["key", "position"]).set_index(["key", "position"])["dk_pts"]
    out = []
    for r in rows[rows["position"] != "DST"].itertuples(index=False):
        key = normalize_name(r.name)
        pts = by_team.get((key, r.team, r.position), by_pos.get((key, r.position)))
        if pts is not None and not pd.isna(pts):
            out.append({"dk_id": int(r.dk_id), "actual_pts": float(pts)})
    return pd.DataFrame(out, columns=["dk_id", "actual_pts"])


def week_dates(sched_raw: pd.DataFrame) -> pd.DataFrame:
    s = sched_raw[sched_raw["game_type"] == "REG"]
    return (s[["season", "week", "gameday"]].assign(gameday=s["gameday"].astype(str))
            .drop_duplicates().reset_index(drop=True))


def week_for(week_dates_df: pd.DataFrame, slate_date: str):
    hit = week_dates_df[week_dates_df["gameday"] == str(slate_date)]
    return (int(hit["season"].iloc[0]), int(hit["week"].iloc[0])) if len(hit) else None


def _entry_label(e) -> str:
    name = e.get("contest_name") or "Contest"
    won, fee = e.get("winnings"), e.get("entry_fee")
    if won is None or pd.isna(won):
        return f"{name} · 💲 winnings not entered"
    profit = float(won) - float(fee or 0)
    return f"{name} · {'✅' if won > 0 else '✗'} {'+' if profit >= 0 else '−'}${abs(profit):,.0f}"


def search(pw: pd.DataFrame, entries: pd.DataFrame, name: str, mine_only: bool = False):
    rows = pw[pw["name"].str.lower() == str(name).strip().lower()].sort_values("slate_date", ascending=False)
    played = {}
    for e in (entries.to_dict("records") if entries is not None and len(entries) else []):
        for pid in str(e.get("players") or "").split(","):
            if pid:
                played.setdefault((str(e["slate_date"]), int(pid)), []).append(_entry_label(e))
    table = pd.DataFrame([{
        "Slate": r.slate_date, "Matchup": f"vs {r.opp} · {r.mu_label}", "Salary": r.salary, "Projected": r.median,
        "Actual": r.actual_pts, "+/−": (r.actual_pts - r.median) if not pd.isna(r.actual_pts) else np.nan,
        "Own est.": r.own_pct, "Own actual": r.actual_own,
        "My entry": "; ".join(played.get((r.slate_date, int(r.dk_id)), [])) or "—", "mu_color": r.mu_color}
        for r in rows.itertuples(index=False)], columns=TABLE_COLUMNS)
    summary = {"slates": int(len(rows)),
               "avg_projected": float(rows["median"].mean()) if len(rows) else None,
               "avg_actual": float(rows["actual_pts"].mean()) if rows["actual_pts"].notna().any() else None,
               "times_played": sum(len(played.get((r.slate_date, int(r.dk_id)), [])) for r in rows.itertuples(index=False))}
    for col in ("Salary", "Projected", "Actual", "+/−", "Own est.", "Own actual"):
        table[col] = pd.to_numeric(table[col], errors="coerce").astype(float)
    if mine_only:
        table = table[table["My entry"] != "—"].reset_index(drop=True)
    return summary, table
