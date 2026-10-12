import numpy as np
import pandas as pd
import pytest

from nfldfs import build, config, dk_rules
from nfldfs.nfl_stats import team_week_totals
from tests.conftest import make_pool

MODEL = {"n_games": 999, "coef": {
    "pass_att": [20, 0.5, 0], "pass_yds": [100, 5, 0], "pass_td": [0, 0.07, 0], "ints": [0.8, 0, 0],
    "carries": [15, 0.4, 0.3], "rush_yds": [60, 2.5, 1], "rush_td": [0, 0.04, 0]}}


def _inputs():
    full = make_pool()
    pool_base = full[["dk_id", "name", "position", "salary", "team", "opp", "game_id", "is_home",
                      "kickoff", "dk_avg", "status", "playable"]].copy()
    rows = []
    for r in full[full.position != "DST"].itertuples(index=False):
        for wk in range(1, 7):
            t, c = round(r.tgt_share * 36), round(r.carry_share * 26)
            qb1 = r.name.endswith("QB1")
            rows.append(dict(player_id=f"P{r.dk_id}", name=r.name, position=r.position, team=r.team,
                             season=2026, week=wk, pass_att=34 if qb1 else 0, pass_yds=240.0 if qb1 else 0.0,
                             pass_td=2 if qb1 else 0, ints=1 if qb1 else 0, carries=c, rush_yds=c * r.ypc,
                             rush_td=0, targets=t, receptions=round(t * r.catch_rate), rec_yds=t * r.ypt,
                             rec_td=0, fumbles_lost=0, two_pt=0, dk_pts=0.0))
    pw = pd.DataFrame(rows)
    games = pd.DataFrame({"game_id": ["AAA@BBB", "CCC@DDD", "XXX@YYY"], "home": ["BBB", "DDD", "YYY"],
                          "away": ["AAA", "CCC", "XXX"], "total": [45.0, 47.0, 40.0],
                          "home_spread": [-3.0, 2.0, 0.0], "n_books": 3, "commence_time": "2026-10-18T17:00:00Z"})
    return pool_base, pw, team_week_totals(pw), games


def test_missing_vegas_lines_names_teams():
    pool_base, pw, tw, games = _inputs()
    with pytest.raises(ValueError, match="CCC, DDD"):
        build.assemble_team_expectations(pool_base, games[games.game_id != "CCC@DDD"], MODEL)


def test_assemble_attaches_implied_totals_for_slate_games_only():
    pool_base, pw, tw, games = _inputs()
    pool, team_exp = build.assemble_team_expectations(pool_base, games, MODEL)
    assert sorted(team_exp.index) == ["AAA", "BBB", "CCC", "DDD"]
    bbb = pool[pool.team == "BBB"].iloc[0]
    assert bbb.implied_total == pytest.approx(24.0) and bbb.opp_implied == pytest.approx(21.0)


def test_build_slate_end_to_end():
    pool_base, pw, tw, games = _inputs()
    pool_base.loc[pool_base["name"] == "AAA WR1", ["status", "playable"]] = ["OUT", False]
    res = build.build_slate(pool_base, pw, tw, MODEL, games, n_sims=300, seed=1, n_candidates=3, field_size=150)
    assert res["match_rate"] == pytest.approx(1.0) and res["unmatched"] == []
    p = res["pool"]
    assert {"median", "floor", "ceiling", "boom_rate", "own_pct", "tier", "matched"} <= set(p.columns)
    assert res["sims"].shape == (300, len(p))
    out_wr = p[p["name"] == "AAA WR1"].iloc[0]
    assert out_wr.own_pct == 0 and out_wr["median"] == 0
    lus = res["lineups"]
    assert set(lus.contest_key) == set(config.CONTEST_TYPES)
    assert "AAA WR1" not in set(lus["name"])
    for _, g in lus[lus["rank"] == 0].groupby("contest_key"):
        assert dk_rules.validate_lineup(g) == []


def test_build_slate_adds_matchup_columns():
    pool_base, pw, tw, games = _inputs()
    res = build.build_slate(pool_base, pw, tw, MODEL, games, n_sims=200, seed=1, n_candidates=2, field_size=100)
    from nfldfs.matchups import MATCHUP_COLUMNS
    assert set(MATCHUP_COLUMNS) <= set(res["pool"].columns)
    offense = res["pool"][res["pool"].position != "DST"]
    assert (offense.mu_label == "Neutral").all()    # no schedule_rows given → neutral (DST rating is Vegas-based)
