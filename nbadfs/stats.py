"""ESPN season stats (sportsdataverse release) -> per-player minutes and DK points per minute."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

from nfldfs.status import atomic_write_bytes
from nfldfs.teams import normalize_name

from .rules import dk_points

BASE_URL = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_player_season_stats"
MAX_AGE_H = 20
THREES = "avgThreePointFieldGoalsMade-avgThreePointFieldGoalsAttempted"
RATE_COLS = ["games", "minutes", "dk_per_min"]
_AVG = {"pts": "avgPoints", "reb": "avgRebounds", "ast": "avgAssists", "stl": "avgSteals",
        "blk": "avgBlocks", "tov": "avgTurnovers"}


def download_season(year: int, dest_dir, session=None) -> Path:
    """Fetch player_season_stats_{year}.parquet (year = season end year); reuse a copy under 20 h old."""
    dest = Path(dest_dir) / f"player_season_stats_{year}.parquet"
    if dest.exists() and time.time() - dest.stat().st_mtime < MAX_AGE_H * 3600:
        return dest
    s = session or requests.Session()
    r = s.get(f"{BASE_URL}/player_season_stats_{year}.parquet", timeout=60)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(dest, r.content)
    return dest


def _made(display) -> float:
    """"2.3-6.1" -> 2.3 (made of made-attempted)."""
    try:
        return float(str(display).split("-")[0])
    except ValueError:
        return 0.0


def player_rates(season_long: pd.DataFrame) -> pd.DataFrame:
    """One row per player: name_key, games, minutes (per game), dk_per_min (DK points per game / minutes).

    Uses the per-game `averages` stats; DD/TD bonuses are not applied at the average level.
    """
    df = season_long[season_long["category"] == "averages"]
    val = df.pivot_table(index=["athlete_id", "athlete_display_name"], columns="stat_name", values="value",
                         aggfunc="first")
    three = df[df["stat_name"] == THREES].drop_duplicates(["athlete_id", "athlete_display_name"]) \
        .set_index(["athlete_id", "athlete_display_name"])["display_value"].map(_made)
    val = val.reindex(columns=["gamesPlayed", "avgMinutes", *_AVG.values()]).fillna(0.0)
    fg3m = three.reindex(val.index).fillna(0.0)
    avg = {k: val[c].to_numpy() for k, c in _AVG.items()}
    # DK bonuses (double/triple-double) would be wrong on averages: score the average line with them stripped.
    pts = dk_points(avg["pts"], fg3m.to_numpy(), avg["reb"], avg["ast"], avg["stl"], avg["blk"], avg["tov"])
    tens = sum((avg[k] >= 10).astype(int) for k in ("pts", "reb", "ast", "stl", "blk"))
    pts = pts - (tens >= 3) * 3.0 - ((tens == 2) * 1.5)
    minutes = val["avgMinutes"].to_numpy()
    per_min = pts / minutes.clip(min=1e-9)
    out = pd.DataFrame({"name_key": [normalize_name(n) for n in val.index.get_level_values(1)],
                        "games": val["gamesPlayed"].to_numpy(), "minutes": minutes,
                        "dk_per_min": (per_min * (minutes > 0)).round(6)})
    return out.drop_duplicates("name_key", keep="first").reset_index(drop=True)


def match_rates(pool: pd.DataFrame, last: pd.DataFrame, current: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Add games/min/rate for last and current season by normalized name; also the share of playable
    players found in either season."""
    out = pool.copy()
    out["name_key"] = out["name"].map(normalize_name)
    for suffix, rates in (("last", last), ("cur", current)):
        r = rates.set_index("name_key")
        out[f"games_{suffix}"] = out["name_key"].map(r["games"])
        out[f"min_{suffix}"] = out["name_key"].map(r["minutes"])
        out[f"rate_{suffix}"] = out["name_key"].map(r["dk_per_min"])
    play = out[out["playable"]] if "playable" in out else out
    hit = play["rate_last"].notna() | play["rate_cur"].notna()
    return out, float(hit.mean()) if len(play) else 0.0
