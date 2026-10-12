import numpy as np
import pandas as pd
import pytest

from nfldfs import build, config, dk_rules
from nfldfs.nfl_stats import team_week_totals

from tests.conftest import SYNTH_MODEL as MODEL, synthetic_inputs as _inputs


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
    assert res["field"].shape == (150, 9)
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
