"""nflverse (via nflreadpy) → normalized weekly player stats, team-week totals, schedule lines."""
from __future__ import annotations

import pandas as pd

from .dk_rules import offense_points
from .teams import to_dk_team

# nflverse has renamed columns across releases; the first name present wins.
_ALIASES = {
    "player_id": ["player_id"], "name": ["player_display_name", "player_name"], "position": ["position"],
    "team": ["team", "recent_team"], "season": ["season"], "week": ["week"],
    "pass_att": ["attempts"], "pass_yds": ["passing_yards"], "pass_td": ["passing_tds"],
    "ints": ["passing_interceptions", "interceptions"],
    "carries": ["carries"], "rush_yds": ["rushing_yards"], "rush_td": ["rushing_tds"],
    "targets": ["targets"], "receptions": ["receptions"], "rec_yds": ["receiving_yards"], "rec_td": ["receiving_tds"],
}
_SUMMED = {
    "fumbles_lost": ["sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"],
    "two_pt": ["passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions"],
}
_TEXT = ("player_id", "name", "position", "team")
KEEP_POSITIONS = ("QB", "RB", "WR", "TE")
TEAM_WEEK_COLUMNS = ["pass_att", "pass_yds", "pass_td", "ints", "targets", "carries", "rush_yds", "rush_td"]


def _first(raw: pd.DataFrame, out_name: str, names: list[str]) -> pd.Series:
    for n in names:
        if n in raw.columns:
            return raw[n]
    raise KeyError(f"nflverse player stats have none of {names} (needed for '{out_name}'); "
                   f"available columns: {sorted(raw.columns)}")


def normalize_player_stats(raw: pd.DataFrame) -> pd.DataFrame:
    if "season_type" in raw.columns:
        raw = raw[raw["season_type"] == "REG"]
    raw = raw.reset_index(drop=True)
    out = pd.DataFrame({k: _first(raw, k, v) for k, v in _ALIASES.items()})
    for k, cols in _SUMMED.items():
        present = [c for c in cols if c in raw.columns]
        if not present:
            raise KeyError(f"nflverse player stats have none of {cols} (needed for '{k}'); "
                           f"available columns: {sorted(raw.columns)}")
        out[k] = raw[present].fillna(0).sum(axis=1)
    num = [c for c in out.columns if c not in _TEXT]
    out[num] = out[num].apply(pd.to_numeric, errors="coerce").fillna(0)
    out["position"] = out["position"].replace({"FB": "RB"})
    out = out[out["position"].isin(KEEP_POSITIONS)].copy()
    out["team"] = out["team"].map(to_dk_team)
    out["dk_pts"] = offense_points(out.pass_yds, out.pass_td, out.ints, out.rush_yds, out.rush_td,
                                   out.receptions, out.rec_yds, out.rec_td, out.fumbles_lost, out.two_pt)
    return out.reset_index(drop=True)


def team_week_totals(player_weeks: pd.DataFrame) -> pd.DataFrame:
    return (player_weeks.groupby(["season", "week", "team"], as_index=False)[TEAM_WEEK_COLUMNS].sum())


def normalize_schedules(raw: pd.DataFrame) -> pd.DataFrame:
    """nflverse spread_line is positive when the HOME team is favored."""
    g = raw[(raw["game_type"] == "REG") & raw["total_line"].notna() & raw["spread_line"].notna()
            & raw["home_score"].notna()].copy()
    home, away = g["home_team"].map(to_dk_team), g["away_team"].map(to_dk_team)
    h = pd.DataFrame({"season": g.season, "week": g.week, "team": home, "opp": away, "is_home": True,
                      "implied_total": (g.total_line + g.spread_line) / 2, "exp_margin": g.spread_line,
                      "points": g.home_score})
    a = pd.DataFrame({"season": g.season, "week": g.week, "team": away, "opp": home, "is_home": False,
                      "implied_total": (g.total_line - g.spread_line) / 2, "exp_margin": -g.spread_line,
                      "points": g.away_score})
    return pd.concat([h, a], ignore_index=True)


def load_raw(seasons: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    import nflreadpy as nfl  # imported lazily: network + heavy dependency
    stats = nfl.load_player_stats(seasons, summary_level="week").to_pandas()
    sched = nfl.load_schedules(seasons).to_pandas()
    return stats, sched
