"""Team abbreviations and player-name normalization shared by every data source."""
from __future__ import annotations

import re
import unicodedata

# nflverse abbreviations that differ from DraftKings'. Everything else matches.
NFLVERSE_TO_DK = {"LA": "LAR", "WSH": "WAS"}

ODDS_API_NAMES = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def to_dk_team(abbr) -> str:
    a = str(abbr).strip().upper()
    return NFLVERSE_TO_DK.get(a, a)


def normalize_name(name) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = s.lower().replace(".", "").replace("'", "").replace("-", " ")
    s = _SUFFIX.sub("", s)
    return re.sub(r"\s+", " ", s).strip()
