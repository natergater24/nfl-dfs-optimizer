"""The Odds API → consensus game lines → implied team totals."""
from __future__ import annotations

import statistics

import pandas as pd
import requests

from .teams import ODDS_API_NAMES

ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"


def fetch_odds(api_key: str, session=None) -> tuple[list[dict], str | None]:
    """One request (costs 2 quota units: spreads + totals, US region)."""
    s = session or requests.Session()
    r = s.get(ODDS_URL, params={"apiKey": api_key, "regions": "us", "markets": "spreads,totals",
                                "oddsFormat": "american"}, timeout=30)
    r.raise_for_status()
    return r.json(), r.headers.get("x-requests-remaining")


def parse_odds(events: list[dict]) -> pd.DataFrame:
    rows = []
    for ev in events:
        home, away = ODDS_API_NAMES.get(ev.get("home_team")), ODDS_API_NAMES.get(ev.get("away_team"))
        if not home or not away:
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
        rows.append({"game_id": f"{away}@{home}", "home": home, "away": away,
                     "total": statistics.median(totals), "home_spread": statistics.median(spreads),
                     "n_books": min(len(totals), len(spreads)), "commence_time": ev.get("commence_time")})
    cols = ["game_id", "home", "away", "total", "home_spread", "n_books", "commence_time"]
    return pd.DataFrame(rows, columns=cols).sort_values("commence_time").reset_index(drop=True)


def implied_totals(games: pd.DataFrame) -> pd.DataFrame:
    """Home implied = (total - home_spread)/2; away = (total + home_spread)/2."""
    home = pd.DataFrame({"team": games.home, "opp": games.away, "game_id": games.game_id,
                         "implied_total": (games.total - games.home_spread) / 2,
                         "exp_margin": -games.home_spread})
    away = pd.DataFrame({"team": games.away, "opp": games.home, "game_id": games.game_id,
                         "implied_total": (games.total + games.home_spread) / 2,
                         "exp_margin": games.home_spread})
    return pd.concat([home, away], ignore_index=True)
