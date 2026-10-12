"""Per-player usage shares (targets, carries) and efficiency, matched onto the DraftKings pool."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .teams import normalize_name

SHARE_COLUMNS = ("tgt_share", "carry_share", "catch_rate", "ypt", "ypc")
# Replacement-level (backup) priors: the share a depth player is assumed to have before evidence.
POSITION_PRIORS = {
    "QB": {"tgt_share": 0.0, "carry_share": 0.03},
    "RB": {"tgt_share": 0.03, "carry_share": 0.08},
    "WR": {"tgt_share": 0.05, "carry_share": 0.0},
    "TE": {"tgt_share": 0.04, "carry_share": 0.0},
}
# Players DraftKings lists that have no nflverse history (rookies, call-ups): small, conservative roles.
UNKNOWN_PLAYER_SHARE = {
    "QB": {"tgt_share": 0.0, "carry_share": 0.02},
    "RB": {"tgt_share": 0.02, "carry_share": 0.05},
    "WR": {"tgt_share": 0.03, "carry_share": 0.0},
    "TE": {"tgt_share": 0.02, "carry_share": 0.0},
}
EFFICIENCY_PRIORS = {
    "catch_rate": {"QB": 0.0, "RB": 0.78, "WR": 0.64, "TE": 0.70},
    "ypt": {"QB": 0.0, "RB": 6.0, "WR": 8.3, "TE": 7.2},
    "ypc": {"QB": 5.0, "RB": 4.3, "WR": 7.0, "TE": 4.0},
}
MAX_TEAM_SHARE = 0.97
LOW_EVIDENCE_GAMES = 3      # players with fewer games with their team are trimmed first by the team cap
LOW_EVIDENCE_FLOOR = 0.25   # ...but never below this fraction of their current share
# A non-playable player's share is handed to teammates only if he played the team's latest game(s): older
# absences are already reflected in the teammates' own recent shares (moving them again double counts).
RECENT_ABSENCE_GAMES = 1
NO_HISTORY_GAMES_SINCE = 99   # sentinel for players with no team history (unmatched, DST)


def compute_shares(player_weeks: pd.DataFrame, team_weeks: pd.DataFrame, *, n_games: int = 6,
                   half_life: float = 3.0, k: float = 0.5) -> pd.DataFrame:
    tw = team_weeks[["season", "week", "team", "targets", "carries"]].rename(
        columns={"targets": "team_targets", "carries": "team_carries"})
    df = player_weeks.merge(tw, on=["season", "week", "team"], how="left").fillna(
        {"team_targets": 0, "team_carries": 0})
    df = df.sort_values(["player_id", "season", "week"])
    df["age"] = df.groupby(["player_id", "team"]).cumcount(ascending=False)
    df = df[df.age < n_games].copy()
    df["w"] = 0.5 ** (df.age / half_life)
    for c in ("targets", "team_targets", "carries", "team_carries"):
        df[f"w_{c}"] = df.w * df[c]
    df["_t"] = df.season * 100 + df.week
    g = df.groupby(["player_id", "team"]).agg(
        name=("name", "last"), position=("position", "last"), last_t=("_t", "max"),
        games=("w", "size"), n_eff=("w", "sum"),
        w_targets=("w_targets", "sum"), w_team_targets=("w_team_targets", "sum"),
        w_carries=("w_carries", "sum"), w_team_carries=("w_team_carries", "sum"),
        targets=("targets", "sum"), receptions=("receptions", "sum"), rec_yds=("rec_yds", "sum"),
        carries=("carries", "sum"), rush_yds=("rush_yds", "sum"),
    ).reset_index()
    g = g.sort_values(["player_id", "last_t"], ascending=[True, False], kind="stable").reset_index(drop=True)
    tw_t = (team_weeks.season * 100 + team_weeks.week).groupby(team_weeks.team).apply(
        lambda t: np.sort(t.unique()))
    g["team_games_since"] = [
        int(len(tw_t[t]) - np.searchsorted(tw_t[t], lt, side="right")) if t in tw_t.index else 0
        for t, lt in zip(g.team, g.last_t)]
    prior = lambda key: g.position.map(lambda p: POSITION_PRIORS[p][key])
    eff = lambda key: g.position.map(EFFICIENCY_PRIORS[key])
    obs_t = np.where(g.w_team_targets > 0, g.w_targets / g.w_team_targets.where(g.w_team_targets > 0, 1), 0.0)
    obs_c = np.where(g.w_team_carries > 0, g.w_carries / g.w_team_carries.where(g.w_team_carries > 0, 1), 0.0)
    g["tgt_share"] = (g.games * obs_t + k * prior("tgt_share")) / (g.games + k)
    g["carry_share"] = (g.games * obs_c + k * prior("carry_share")) / (g.games + k)
    g["catch_rate"] = (g.receptions + 10 * eff("catch_rate")) / (g.targets + 10)
    g["ypt"] = (g.rec_yds + 20 * eff("ypt")) / (g.targets + 20)
    g["ypc"] = (g.rush_yds + 20 * eff("ypc")) / (g.carries + 20)
    return g[["player_id", "name", "position", "team", "games", "n_eff", "team_games_since", *SHARE_COLUMNS]]


def attach_shares(pool: pd.DataFrame, shares: pd.DataFrame) -> pd.DataFrame:
    """Match on (normalized name, team, position), then (normalized name, position)."""
    by_team, by_pos = {}, {}
    for r in shares.itertuples(index=False):
        key = normalize_name(r.name)
        vals = {c: getattr(r, c) for c in (*SHARE_COLUMNS, "games", "team_games_since")}
        by_team.setdefault((key, r.team, r.position), vals)
        by_pos.setdefault((key, r.position), vals)
    rows = []
    for r in pool.itertuples(index=False):
        if r.position == "DST":
            rows.append({**{c: 0.0 for c in SHARE_COLUMNS}, "games": 0, "team_games_since": NO_HISTORY_GAMES_SINCE, "matched": True})
            continue
        key = normalize_name(r.name)
        vals = by_team.get((key, r.team, r.position)) or by_pos.get((key, r.position))
        if vals is None:
            vals = {**UNKNOWN_PLAYER_SHARE[r.position],
                    **{c: EFFICIENCY_PRIORS[c][r.position] for c in ("catch_rate", "ypt", "ypc")}, "games": 0,
                    "team_games_since": NO_HISTORY_GAMES_SINCE}
            rows.append({**vals, "matched": False})
        else:
            rows.append({**vals, "matched": True})
    extra = pd.DataFrame(rows, index=pool.index)
    return pd.concat([pool.drop(columns=[c for c in (*SHARE_COLUMNS, "games", "team_games_since", "matched") if c in pool.columns]), extra],
                     axis=1)


def redistribute(pool: pd.DataFrame) -> pd.DataFrame:
    pool = pool.copy()
    for _, idx in pool.groupby("team").groups.items():
        sub = pool.loc[idx]
        for col in ("tgt_share", "carry_share"):
            for pos in ("QB", "RB", "WR", "TE"):
                m_pos = sub.position == pos
                out = m_pos & ~sub.playable
                movable = out
                if "team_games_since" in sub.columns:
                    movable = out & (sub.team_games_since <= RECENT_ABSENCE_GAMES)
                lost = float(sub.loc[movable, col].sum())
                recv = m_pos & sub.playable
                if lost > 0 and recv.any():
                    base = sub.loc[recv, col]
                    w = base / base.sum() if base.sum() > 0 else pd.Series(1.0 / len(base), index=base.index)
                    pool.loc[base.index, col] = base + lost * w
                pool.loc[sub.index[out.to_numpy()], col] = 0.0
            total = float(pool.loc[idx, col].sum())
            if total > MAX_TEAM_SHARE and "games" in pool.columns:
                excess = total - MAX_TEAM_SHARE
                low = (pool.loc[idx, "playable"] & (pool.loc[idx, "games"] < LOW_EVIDENCE_GAMES)).to_numpy()
                low_idx = pd.Index(idx)[low]
                low_sum = float(pool.loc[low_idx, col].sum())
                if low_sum > 0:
                    take = min(excess, low_sum * (1 - LOW_EVIDENCE_FLOOR))
                    pool.loc[low_idx, col] = pool.loc[low_idx, col] * (1 - take / low_sum)
                total = float(pool.loc[idx, col].sum())
            if total > MAX_TEAM_SHARE:
                pool.loc[idx, col] = pool.loc[idx, col] * (MAX_TEAM_SHARE / total)
    return pool
