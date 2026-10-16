"""DraftKings salaries: find the Sunday main slate in the lobby, download its official CSV, parse it."""
from __future__ import annotations

import datetime as dt
import io

import numpy as np
import pandas as pd
import requests

from .teams import to_dk_team

LOBBY_URL = "https://www.draftkings.com/lobby/getcontests?sport=NFL"
CSV_URL = ("https://www.draftkings.com/lineup/getavailableplayerscsv"
           "?contestTypeId={contest_type_id}&draftGroupId={draft_group_id}")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
CLASSIC_GAME_TYPE_ID = 1
PLAYABLE_STATUSES = {"", "Q", "P"}
REQUIRED_COLUMNS = ["Position", "Name", "ID", "Salary", "Game Info", "TeamAbbrev", "AvgPointsPerGame", "Status"]


def find_main_slate(lobby: dict, today: dt.date) -> dict:
    """Earliest upcoming Sunday 1:00 PM ET Classic draft group with the most games."""
    rows = []
    for g in lobby.get("DraftGroups", []):
        if g.get("GameTypeId") != CLASSIC_GAME_TYPE_ID:
            continue
        start = dt.datetime.fromisoformat(g["StartDateEst"][:19])
        if start.date() < today or start.weekday() != 6 or (start.hour, start.minute) != (13, 0):
            continue
        rows.append(((start.date(), -int(g.get("GameCount", 0)), g.get("DraftGroupTag") != "Featured"), g, start))
    if not rows:
        raise LookupError("No Sunday 1:00 PM Classic main slate found in the DraftKings lobby")
    rows.sort(key=lambda r: r[0])
    _, g, start = rows[0]
    return {"draft_group_id": int(g["DraftGroupId"]), "contest_type_id": int(g["ContestTypeId"]),
            "start": start.isoformat(), "game_count": int(g["GameCount"])}


def fetch_lobby(session=None) -> dict:
    s = session or requests.Session()
    r = s.get(LOBBY_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        raise RuntimeError("DraftKings returned something other than the contest lobby (it may be blocking "
                           "automated requests). Download DKSalaries.csv from any main-slate contest "
                           "and run with --salary-csv PATH.") from None


def fetch_salary_csv(slate: dict, session=None) -> str:
    s = session or requests.Session()
    r = s.get(CSV_URL.format(**slate), headers=HEADERS, timeout=30)
    r.raise_for_status()
    text = r.text.lstrip("﻿")
    if not text.startswith("Position"):
        raise RuntimeError("DraftKings returned something other than the salary CSV (it may be blocking "
                           "automated downloads). Download DKSalaries.csv from any main-slate contest "
                           "and run with --salary-csv PATH.")
    return text


def parse_salary_csv(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text.lstrip("﻿")), keep_default_na=False, dtype=str)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"DraftKings salary file is missing columns: {missing}")
    game = df["Game Info"].str.extract(r"^(?P<away>[A-Z]+)@(?P<home>[A-Z]+) (?P<date>\S+) (?P<time>\S+)")
    bad = game["away"].isna()
    if bad.any():
        raise ValueError(f"Unreadable 'Game Info' for: {df.loc[bad, 'Name'].tolist()[:5]}")
    out = pd.DataFrame({
        "dk_id": df["ID"].astype("int64"),
        "name": df["Name"].str.strip(),
        "position": df["Position"].str.strip(),
        "salary": df["Salary"].astype(int),
        "team": df["TeamAbbrev"].map(to_dk_team),
    })
    away, home = game["away"].map(to_dk_team), game["home"].map(to_dk_team)
    out["is_home"] = out["team"] == home
    out["opp"] = np.where(out["is_home"], away, home)
    out["game_id"] = away + "@" + home
    out["kickoff"] = pd.to_datetime(game["date"] + " " + game["time"], format="%m/%d/%Y %I:%M%p")
    out["dk_avg"] = pd.to_numeric(df["AvgPointsPerGame"], errors="coerce").fillna(0.0)
    out["status"] = df["Status"].str.strip().str.upper()
    out["playable"] = out["status"].isin(PLAYABLE_STATUSES)
    return out[["dk_id", "name", "position", "salary", "team", "opp", "game_id",
                "is_home", "kickoff", "dk_avg", "status", "playable"]]


CONTEST_COLUMNS = ["contest_id", "contest_name", "entry_fee", "max_entries"]


def lobby_contests(lobby: dict, draft_group_id) -> pd.DataFrame:
    """Contests on one draft group, from the lobby JSON (names and entry fees for the results tracker)."""
    rows = [{"contest_id": str(c["id"]), "contest_name": str(c.get("n", "")),
             "entry_fee": float(c.get("a") or 0), "max_entries": int(c.get("m") or 0)}
            for c in lobby.get("Contests", []) if str(c.get("dg")) == str(draft_group_id)]
    return pd.DataFrame(rows, columns=CONTEST_COLUMNS)
