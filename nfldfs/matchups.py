"""Matchup ratings: DraftKings points each defense allowed to each position (display-only in v1)."""
from __future__ import annotations

import colorsys

import numpy as np
import pandas as pd

N_GAMES = 6
RATIO_LO, RATIO_HI = 0.70, 1.30          # ratios beyond these get the full red / green
LABEL_CUTOFFS = ((1.12, "Great"), (1.03, "Good"), (0.97, "Neutral"), (0.88, "Tough"))
WORST_LABEL = "Very tough"
MATCHUP_COLUMNS = ["mu_ratio", "mu_label", "mu_color", "mu_text"]


def defense_vs_position(player_weeks: pd.DataFrame, schedule_rows: pd.DataFrame,
                        n_games: int = N_GAMES) -> pd.DataFrame:
    sched = schedule_rows[["season", "week", "team", "opp"]].drop_duplicates()
    pw = player_weeks.merge(sched, on=["season", "week", "team"], how="inner")
    g = pw.groupby(["opp", "season", "week", "position"], as_index=False)["dk_pts"].sum()
    g = g.sort_values(["season", "week"], kind="stable")
    g["age"] = g.groupby(["opp", "position"]).cumcount(ascending=False)
    g = g[g.age < n_games].groupby(["opp", "position"], as_index=False)["dk_pts"].mean()
    g["ratio"] = g["dk_pts"] / g.groupby("position")["dk_pts"].transform("mean")
    g["rank"] = g.groupby("position")["dk_pts"].rank(ascending=False, method="min").astype(int)
    g = g.rename(columns={"opp": "defense", "dk_pts": "allowed"})
    return g[["defense", "position", "allowed", "ratio", "rank"]]


def matchup_color(ratio: float) -> str:
    """Red (tough) → amber → green (soft)."""
    t = float(np.clip((ratio - RATIO_LO) / (RATIO_HI - RATIO_LO), 0.0, 1.0))
    r, g, b = colorsys.hls_to_rgb(t * 130 / 360, 0.38, 0.62)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def matchup_label(ratio: float) -> str:
    for cutoff, label in LABEL_CUTOFFS:
        if ratio >= cutoff:
            return label
    return WORST_LABEL


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def attach_matchups(pool: pd.DataFrame, dvp: pd.DataFrame) -> pd.DataFrame:
    p = pool.drop(columns=[c for c in MATCHUP_COLUMNS if c in pool.columns]).reset_index(drop=True)
    m = p[["opp", "position"]].merge(dvp, left_on=["opp", "position"], right_on=["defense", "position"],
                                      how="left")
    ratio = m["ratio"].to_numpy(dtype=float).copy()
    rank = m["rank"].to_numpy(dtype=float)
    allowed = m["allowed"].to_numpy(dtype=float)
    n_def = int(dvp["defense"].nunique()) or 32
    dst = (p["position"] == "DST").to_numpy()
    if dst.any():
        base = p.loc[~dst, "implied_total"] if (~dst).any() else p.loc[dst, "opp_implied"]
        ratio[dst] = float(base.mean()) / p.loc[dst, "opp_implied"].to_numpy(dtype=float)
    ratio = np.where(np.isnan(ratio), 1.0, ratio)
    texts = []
    for i, r in enumerate(p.itertuples(index=False)):
        if dst[i]:
            texts.append(f"vs {r.opp}: opponent's Vegas total is {r.opp_implied:.1f} pts")
        elif np.isnan(allowed[i]):
            texts.append(f"vs {r.opp}: not enough games to rate this matchup")
        else:
            texts.append(f"vs {r.opp}: allows {allowed[i]:.1f} DK pts/game to {r.position}s — "
                         f"{_ordinal(int(rank[i]))}-easiest of {n_def}")
    p["mu_ratio"] = ratio.round(3)
    p["mu_label"] = [matchup_label(x) for x in ratio]
    p["mu_color"] = [matchup_color(x) for x in ratio]
    p["mu_text"] = texts
    return p
