"""Vegas implied total + expected margin → expected team passing/rushing volume and TDs."""
from __future__ import annotations

import numpy as np
import pandas as pd

TEAM_STATS = ("pass_att", "pass_yds", "pass_td", "ints", "carries", "rush_yds", "rush_td")
MIN_TRAINING_GAMES = 50


def build_training_frame(team_weeks: pd.DataFrame, schedule_rows: pd.DataFrame) -> pd.DataFrame:
    return team_weeks.merge(schedule_rows[["season", "week", "team", "implied_total", "exp_margin"]],
                            on=["season", "week", "team"], how="inner")


def fit_team_model(frame: pd.DataFrame) -> dict:
    if len(frame) < MIN_TRAINING_GAMES:
        raise ValueError(f"need at least {MIN_TRAINING_GAMES} team-games with Vegas lines to fit, got {len(frame)}")
    X = np.column_stack([np.ones(len(frame)), frame.implied_total, frame.exp_margin])
    coef = {s: np.linalg.lstsq(X, frame[s].to_numpy(float), rcond=None)[0].round(6).tolist() for s in TEAM_STATS}
    return {"coef": coef, "n_games": int(len(frame))}


def expected_team_stats(implied: pd.DataFrame, model: dict) -> pd.DataFrame:
    out = pd.DataFrame({"team": implied.team.to_numpy()})
    for s in TEAM_STATS:
        a, b, c = model["coef"][s]
        out[f"exp_{s}"] = np.clip(a + b * implied.implied_total.to_numpy() + c * implied.exp_margin.to_numpy(),
                                  0.01, None)
    return out
