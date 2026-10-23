"""Pool + Vegas lines + ESPN rates -> minutes, rate and a median / sd per player."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .dk import parse_salaries  # noqa: F401  (documents the Task 1 pool this consumes)

BASE_COLUMNS = ["dk_id", "name", "team", "opp", "game", "tip", "positions", "slots", "salary", "status",
                "dk_avg", "playable"]
POOL_COLUMNS = BASE_COLUMNS + ["minutes", "rate", "implied_total", "opp_implied", "line_missing", "median",
                               "sd", "floor", "ceiling"]
PRIOR_GAMES = 8.0
MAX_MINUTES = 40.0
VEGAS_CLIP = (0.85, 1.15)


def _blend(cur, last, w):
    """Weighted blend of two season values; a missing season gets zero weight."""
    cur, last, w = (np.asarray(x, dtype=float) for x in (cur, last, w))
    out = np.where(np.isnan(cur), last, np.where(np.isnan(last), cur, w * cur + (1 - w) * last))
    return out


def _redistribute(df: pd.DataFrame, minutes: np.ndarray) -> np.ndarray:
    """Share each Out player's minutes among playable teammates with an overlapping non-UTIL slot,
    proportional to their minutes, capped at MAX_MINUTES."""
    minutes = minutes.copy()
    slots = [set(s) - {"UTIL"} for s in df["slots"]]
    playable = df["playable"].to_numpy()
    team = df["team"].to_numpy()
    for i in np.where(~playable & ~np.isnan(minutes) & (minutes > 0))[0]:
        left = float(minutes[i])
        mates = [j for j in range(len(df)) if playable[j] and team[j] == team[i] and slots[j] & slots[i]
                 and minutes[j] > 0 and not np.isnan(minutes[j])]
        for _ in range(10):
            room = [j for j in mates if minutes[j] < MAX_MINUTES - 1e-9]
            if left <= 1e-9 or not room:
                break
            base = sum(minutes[j] for j in room)
            given = 0.0
            for j in room:
                add = min(left * minutes[j] / base, MAX_MINUTES - minutes[j])
                minutes[j] += add
                given += add
            left -= given
    return minutes


def project(pool: pd.DataFrame, lines: pd.DataFrame, matched: pd.DataFrame) -> pd.DataFrame:
    """`matched` is the output of stats.match_rates (pool + games/min/rate for last and current season)."""
    df = pool[BASE_COLUMNS].reset_index(drop=True).copy()
    m = matched.reset_index(drop=True)
    g_cur = m["games_cur"].fillna(0.0).to_numpy(dtype=float)
    w = g_cur / (g_cur + PRIOR_GAMES)
    minutes = _blend(m["min_cur"], m["min_last"], w)
    rate = _blend(m["rate_cur"], m["rate_last"], w)
    has_stats = ~np.isnan(rate)

    # Vegas: league-average implied total, per-team scaling
    lg = float(lines["implied_total"].mean()) if len(lines) else np.nan
    by_team = lines.drop_duplicates("team").set_index("team") if len(lines) else lines
    imp = df["team"].map(by_team["implied_total"]) if len(lines) else pd.Series(np.nan, index=df.index)
    opp_imp = df["team"].map(by_team["opp_implied"]) if len(lines) else pd.Series(np.nan, index=df.index)
    missing = imp.isna().to_numpy()
    df["implied_total"] = imp.fillna(lg).to_numpy(dtype=float)
    df["opp_implied"] = opp_imp.fillna(lg).to_numpy(dtype=float)
    df["line_missing"] = missing
    scale = np.clip(df["implied_total"].to_numpy() / lg, *VEGAS_CLIP) if lg == lg and lg > 0 else np.ones(len(df))

    playable = df["playable"].to_numpy(dtype=bool)
    minutes = _redistribute(df.assign(playable=playable), np.where(has_stats, minutes, np.nan))
    rate = rate * scale

    baseline = np.maximum(df["dk_avg"].to_numpy(dtype=float), df["salary"].to_numpy(dtype=float) / 1000 * 4.5)
    median = np.where(has_stats, np.nan_to_num(minutes) * np.nan_to_num(rate), baseline)
    median = np.where(playable, median, 0.0)
    df["minutes"] = np.where(has_stats & playable, np.nan_to_num(minutes), 0.0)
    df["rate"] = np.where(has_stats & playable, np.nan_to_num(rate), 0.0)
    df["median"] = median
    df["sd"] = 0.30 * median + 2.0
    df["floor"] = np.nan
    df["ceiling"] = np.nan
    return df[POOL_COLUMNS]
