"""The Odds API (basketball_nba) -> consensus game lines -> per-team implied totals."""
from __future__ import annotations

import statistics
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .config import ODDS_MAX_AGE_MIN

ODDS_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
ET = ZoneInfo("America/New_York")

# Odds API full team name -> DraftKings abbreviation
TEAM_ABBR = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET", "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM", "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHO", "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR", "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}
COLUMNS = ["team", "opp", "total", "spread", "implied_total", "opp_implied"]


def fetch_odds(api_key: str, session=None) -> tuple[list[dict], str | None]:
    """One request (costs 2 quota units: spreads + totals, US region)."""
    s = session or requests.Session()
    try:
        r = s.get(ODDS_URL, params={"apiKey": api_key, "regions": "us", "markets": "spreads,totals",
                                    "oddsFormat": "american"}, timeout=30)
        r.raise_for_status()
        return r.json(), r.headers.get("x-requests-remaining")
    except requests.HTTPError as e:
        # requests' messages embed the full URL (with apiKey=...); never let that reach logs or run_status.json
        status = getattr(e.response, "status_code", "error")
        raise RuntimeError(f"The Odds API request failed (HTTP {status}): the monthly quota may be used up or "
                           "ODDS_API_KEY may be invalid.") from None
    except requests.RequestException:
        raise RuntimeError("Could not reach The Odds API (network error). Try again later.") from None


def team_lines(games: list[dict], day: date) -> pd.DataFrame:
    """Two rows (one per team) for each game whose Eastern-time date is `day`.

    total = median over books; spread = that team's median spread (negative = favorite);
    implied = total/2 - spread/2.
    """
    rows = []
    for ev in games:
        try:
            tip = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).astimezone(ET)
        except (KeyError, ValueError):
            continue
        home, away = TEAM_ABBR.get(ev.get("home_team")), TEAM_ABBR.get(ev.get("away_team"))
        if tip.date() != day or not home or not away:
            continue
        totals, spreads = [], []
        for book in ev.get("bookmakers", []):
            for m in book.get("markets", []):
                if m["key"] == "totals":
                    over = next((o for o in m["outcomes"] if o["name"] == "Over"), None)
                    if over is not None:
                        totals.append(float(over["point"]))
                elif m["key"] == "spreads":
                    h = next((o for o in m["outcomes"] if o["name"] == ev["home_team"]), None)
                    if h is not None:
                        spreads.append(float(h["point"]))
        if not totals or not spreads:
            continue
        total, hs = statistics.median(totals), statistics.median(spreads)
        home_imp, away_imp = total / 2 - hs / 2, total / 2 + hs / 2
        rows.append({"team": home, "opp": away, "total": total, "spread": hs,
                     "implied_total": home_imp, "opp_implied": away_imp})
        rows.append({"team": away, "opp": home, "total": total, "spread": -hs,
                     "implied_total": away_imp, "opp_implied": home_imp})
    return pd.DataFrame(rows, columns=COLUMNS)


def lines_fresh(path, now: datetime, max_age_min: float = ODDS_MAX_AGE_MIN) -> bool:
    """True when the lines file exists and was written less than `max_age_min` minutes before `now`."""
    p = Path(path)
    if not p.exists():
        return False
    return (now.timestamp() - p.stat().st_mtime) / 60 < max_age_min
