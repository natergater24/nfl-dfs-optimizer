"""DraftKings NBA Classic: today's slates from the lobby, and the official salary CSV."""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd
import requests

from .rules import eligible_slots

LOBBY_URL = "https://www.draftkings.com/lobby/getcontests?sport=NBA"
CSV_URL = ("https://www.draftkings.com/lineup/getavailableplayerscsv"
           "?contestTypeId=70&draftGroupId={draft_group_id}")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
CLASSIC_CONTEST_TYPE_ID = 70
REQUIRED_COLUMNS = ["Position", "Name", "ID", "Salary", "Game Info", "TeamAbbrev", "AvgPointsPerGame", "Status"]
_STATUS_ALIASES = {"OUT": "O"}


def fetch_lobby(session=None) -> dict:
    s = session or requests.Session()
    r = s.get(LOBBY_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        raise RuntimeError("DraftKings returned something other than the contest lobby (it may be blocking "
                           "automated requests).") from None


def classic_slates(lobby: dict, day: dt.date) -> list[dict]:
    """Classic draft groups starting on `day` (Eastern), earliest first."""
    out = []
    for g in lobby.get("DraftGroups", []):
        if g.get("ContestTypeId") != CLASSIC_CONTEST_TYPE_ID:
            continue
        start = dt.datetime.fromisoformat(g["StartDateEst"][:19])
        if start.date() != day:
            continue
        suffix = (g.get("ContestStartTimeSuffix") or "").strip().strip("()").strip()
        out.append({"draft_group_id": int(g["DraftGroupId"]), "name": suffix or "Main",
                    "start": start.isoformat(), "games": int(g["GameCount"])})
    out.sort(key=lambda s: (s["start"], s["draft_group_id"]))
    return out


def fetch_salary_csv(dg: int, session=None) -> str:
    s = session or requests.Session()
    r = s.get(CSV_URL.format(draft_group_id=int(dg)), headers=HEADERS, timeout=30)
    r.raise_for_status()
    text = r.text.lstrip("﻿")
    if not text.startswith("Position"):
        raise RuntimeError("DraftKings returned something other than the salary CSV (it may be blocking "
                           "automated downloads).")
    return text


def parse_salaries(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text.lstrip("﻿")), keep_default_na=False, dtype=str)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"DraftKings salary file is missing columns: {missing}")
    g = df["Game Info"].str.extract(r"^(?P<away>[A-Z]+)@(?P<home>[A-Z]+) (?P<date>\d+/\d+/\d+) (?P<time>\d+:\d+[AP]M)")
    bad = g["away"].isna()
    if bad.any():
        raise ValueError(f"Unreadable 'Game Info' for: {df.loc[bad, 'Name'].tolist()[:5]}")
    team = df["TeamAbbrev"].str.strip()
    away_team = team == g["away"]
    status = df["Status"].str.strip().str.upper().replace(_STATUS_ALIASES)
    positions = df["Position"].str.strip()
    tip = pd.to_datetime(g["date"] + " " + g["time"], format="%m/%d/%Y %I:%M%p").dt.strftime("%Y-%m-%dT%H:%M:%S")
    return pd.DataFrame({
        "dk_id": df["ID"].astype("int64"),
        "name": df["Name"].str.strip(),
        "team": team,
        "opp": g["home"].where(away_team, g["away"]),
        "game": g["away"] + "@" + g["home"],
        "tip": tip,
        "positions": positions,
        "slots": positions.map(eligible_slots),
        "salary": df["Salary"].astype(int),
        "status": status,
        "dk_avg": pd.to_numeric(df["AvgPointsPerGame"], errors="coerce").fillna(0.0),
        "playable": status != "O",
    })
