"""Monte Carlo simulation of every slate game → DraftKings points per player per simulation.

Correlation comes from shared draws: a game-level pace factor (shootout vs slog) and a
team-level factor scale both offenses; a team's passing yards and TDs are split among its
pass-catchers, so a QB's big game is his receivers' big game."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .dk_rules import dst_points, offense_points
from .injuries import apply_play_prob

GAME_SIGMA = 0.18
TEAM_SIGMA = 0.20
PASS_YDS_CV = 0.20
RUSH_YDS_CV = 0.28
SHARE_CONCENTRATION = 35.0           # Dirichlet concentration: lower = more week-to-week role noise
TARGET_FRACTION_TO_POOL = 0.93       # some targets go to players outside the DK pool
TD_WEIGHT = {"QB": 0.6, "RB": 1.0, "WR": 1.0, "TE": 1.15}
FUMBLES_LOST_RATE = {"QB": 0.10, "RB": 0.05, "WR": 0.03, "TE": 0.03}
FG_PER_GAME = 1.6
SACKS_PER_GAME = 2.4
FUMBLE_RECOVERIES_PER_GAME = 0.6
DEF_TD_RATE = 0.07
SAFETY_RATE = 0.02
BLOCKED_KICK_RATE = 0.04
_STATS = ("pass_yds", "pass_td", "ints", "rush_yds", "rush_td", "receptions", "rec_yds", "rec_td")


def _factor(rng, sigma, n):
    return rng.lognormal(-sigma ** 2 / 2, sigma, n)   # mean 1


def _simulate_team(rng, e: pd.Series, game_factor: np.ndarray, n: int) -> dict:
    f = game_factor * _factor(rng, TEAM_SIGMA, n)
    pass_td = rng.poisson(e["exp_pass_td"] * f)
    rush_td = rng.poisson(e["exp_rush_td"] * f)
    fg = rng.poisson(FG_PER_GAME * np.sqrt(f))
    return {
        "pass_yds": np.maximum(0.0, rng.normal(e["exp_pass_yds"] * f, PASS_YDS_CV * e["exp_pass_yds"])),
        "rush_yds": np.maximum(0.0, rng.normal(e["exp_rush_yds"] * f, RUSH_YDS_CV * e["exp_rush_yds"])),
        "pass_td": pass_td, "rush_td": rush_td,
        "ints": rng.poisson(max(float(e["exp_ints"]), 0.01), n),
        "targets": e["exp_pass_att"] * f * TARGET_FRACTION_TO_POOL,
        "points": 7 * (pass_td + rush_td) + 3 * fg,
    }


def _draw_shares(rng, shares: np.ndarray, n: int):
    shares = np.clip(shares, 1e-4, None)
    rest = max(1e-3, 1.0 - shares.sum())
    draw = rng.dirichlet(np.append(shares, rest) * SHARE_CONCENTRATION, size=n)
    return draw[:, :-1], draw[:, -1]


def _allocate_tds(rng, team_tds, draw, rest, weights):
    """Give each team TD to exactly one player (or the outside-the-pool bucket): one multinomial per sim."""
    w = draw * weights
    p = np.concatenate([w, rest[:, None]], axis=1)
    p = p / p.sum(axis=1, keepdims=True)
    return rng.multinomial(team_tds, p)[:, :-1]


def _live(pool: pd.DataFrame) -> pd.Series:
    """DraftKings-playable and, on injury-aware pools, recommendable (lean-out is treated like Doubtful)."""
    live = pool.playable.astype(bool)
    if "recommendable" in pool.columns:
        live = live & pool.recommendable.astype(bool)
    return live


def starting_qbs(pool: pd.DataFrame) -> dict:
    qbs = pool[(pool.position == "QB") & _live(pool)]      # a lean-out QB1 hands the start to QB2
    return {team: int(g.salary.idxmax()) for team, g in qbs.groupby("team")}


def simulate(pool: pd.DataFrame, team_exp: pd.DataFrame, n_sims: int, seed: int, *, sit: bool = True) -> np.ndarray:
    """Points per sim (rows) per pool player (columns). With a play_prob column, a questionable player
    scores 0 in a seeded (1 - play_prob) share of sims (sit=False returns the when-he-plays draws)."""
    if not isinstance(pool.index, pd.RangeIndex) or pool.index.start != 0:
        raise ValueError("simulate() needs a pool with a 0-based RangeIndex (call reset_index first)")
    missing = sorted((set(pool.team) | set(pool.opp)) - set(team_exp.index))
    if missing:
        raise KeyError(f"No team expectations for: {', '.join(missing)}")
    rng = np.random.default_rng(seed)
    n = n_sims
    team_game = {}
    for r in pool[["team", "opp", "game_id"]].drop_duplicates().itertuples(index=False):
        team_game[r.team] = team_game[r.opp] = r.game_id
    game_f = {g: _factor(rng, GAME_SIGMA, n) for g in sorted(set(team_game.values()))}
    teams = {t: _simulate_team(rng, team_exp.loc[t], game_f[team_game[t]], n) for t in sorted(team_game)}
    qbs = starting_qbs(pool)
    out = np.zeros((n, len(pool)), dtype=np.float32)
    live_all = _live(pool)

    for team, rows in pool.groupby("team").groups.items():
        o = pool.loc[rows]
        o = o[o.position != "DST"]
        if o.empty:
            continue
        oidx = o.index.to_numpy()
        pos = o.position.to_numpy()
        live = live_all.loc[o.index].to_numpy()
        s = teams[team]
        st = {k: np.zeros((n, len(o))) for k in _STATS}

        rmask = np.isin(pos, ["RB", "WR", "TE"]) & (o.tgt_share.to_numpy() > 0) & live
        if rmask.any():
            sh = o.tgt_share.to_numpy()[rmask]
            draw, rest = _draw_shares(rng, sh, n)
            ypt = o.ypt.to_numpy()[rmask]
            ypt_rel = ypt / max(np.sum(sh * ypt) / sh.sum(), 1e-9)
            tgts = np.round(s["targets"][:, None] * draw).astype(np.int64)
            st["receptions"][:, rmask] = rng.binomial(tgts, o.catch_rate.to_numpy()[rmask])
            yds = s["pass_yds"][:, None] * draw * ypt_rel
            scale = np.minimum(1.0, s["pass_yds"] / np.maximum(yds.sum(axis=1), 1e-9))
            st["rec_yds"][:, rmask] = yds * scale[:, None]
            st["rec_td"][:, rmask] = _allocate_tds(rng, s["pass_td"], draw, rest,
                                                   np.array([TD_WEIGHT[p] for p in pos[rmask]]))

        cmask = (o.carry_share.to_numpy() > 0) & live
        if cmask.any():
            sh = o.carry_share.to_numpy()[cmask]
            draw, rest = _draw_shares(rng, sh, n)
            ypc = o.ypc.to_numpy()[cmask]
            ypc_rel = ypc / max(np.sum(sh * ypc) / sh.sum(), 1e-9)
            st["rush_yds"][:, cmask] = s["rush_yds"][:, None] * draw * ypc_rel
            st["rush_td"][:, cmask] = _allocate_tds(rng, s["rush_td"], draw, rest,
                                                    np.array([TD_WEIGHT[p] for p in pos[cmask]]))

        has_role = rmask | cmask
        qb = qbs.get(team)
        if qb is not None:
            j = int(np.where(oidx == qb)[0][0])
            st["pass_yds"][:, j], st["pass_td"][:, j], st["ints"][:, j] = s["pass_yds"], s["pass_td"], s["ints"]
            has_role[j] = True

        fumbles = rng.poisson(np.array([FUMBLES_LOST_RATE[p] for p in pos]), size=(n, len(o)))
        fumbles[:, ~has_role] = 0          # players with no touches can't fumble
        pts = offense_points(**st, fumbles_lost=fumbles)
        pts[:, ~live] = 0.0
        out[:, oidx] = pts

    for i in np.where((pool.position == "DST").to_numpy())[0]:
        opp = teams[pool.at[i, "opp"]]
        pts = dst_points(points_allowed=opp["points"], sacks=rng.poisson(SACKS_PER_GAME, n), ints=opp["ints"],
                         fumble_recoveries=rng.poisson(FUMBLE_RECOVERIES_PER_GAME, n),
                         def_tds=rng.binomial(1, DEF_TD_RATE, n), safeties=rng.binomial(1, SAFETY_RATE, n),
                         blocked_kicks=rng.binomial(1, BLOCKED_KICK_RATE, n))
        out[:, i] = pts if live_all.iat[i] else 0.0
    return apply_play_prob(out, pool, seed) if sit else out


def summarize(sims: np.ndarray, pool: pd.DataFrame) -> pd.DataFrame:
    q = np.percentile(sims, [20, 50, 85], axis=0)
    boom = (sims >= 3 * pool.salary.to_numpy() / 1000).mean(axis=0)
    return pd.DataFrame({"mean": sims.mean(axis=0), "floor": q[0], "median": q[1], "ceiling": q[2],
                         "boom_rate": boom}, index=pool.index)
