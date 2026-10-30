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


def _injured_base():
    from nfldfs import injuries
    pool_base, pw, tw, games = _inputs()
    pool_base["lean"] = ""
    m = pool_base["name"] == "CCC WR1"
    pool_base.loc[m, ["status", "lean"]] = ["Q", "out"]              # blurb: "ruled out"
    pool_base.loc[pool_base["name"] == "DDD WR1", "status"] = "Q"     # unclear
    pool_base.loc[pool_base["name"] == "AAA RB1", ["status", "playable"]] = ["D", False]
    return injuries.classify(pool_base), pw, tw, games


def test_build_slate_carries_injury_columns_and_backups(tmp_path):
    base, pw, tw, games = _injured_base()
    res = build.build_slate(base, pw, tw, MODEL, games, n_sims=300, seed=1, n_candidates=3, field_size=150)
    p = res["pool"]
    assert {"inj_tag", "inj_class", "lean", "recommendable", "play_prob"} <= set(p.columns)
    assert p.set_index("name").loc["DDD WR1", "play_prob"] == config.Q_PLAY_PROB
    assert not {"CCC WR1", "AAA RB1"} & set(res["lineups"]["name"])
    bk = res["injury_backups"]
    assert list(bk.columns) == ["contest_key"] + build.lineups.BACKUP_COLUMNS
    # displayed projections stay the when-he-plays numbers
    inj_cols = ["lean", "inj_tag", "inj_class", "recommendable", "play_prob"]
    plain = build.build_slate(base.drop(columns=inj_cols), pw, tw, MODEL, games, n_sims=300, seed=1,
                              n_candidates=3, field_size=150)["pool"].set_index("name")
    assert p.set_index("name").loc["DDD WR1", "median"] == pytest.approx(plain.loc["DDD WR1", "median"])
    q = p.index[p["name"] == "DDD WR1"][0]
    assert (res["sims"][:, q] == 0).mean() > 0.05
    build.write_published(res, tmp_path, {"x": 1})
    import pandas as pd
    assert list(pd.read_parquet(tmp_path / "injury_backups.parquet").columns) == list(bk.columns)
    assert "inj_tag" in pd.read_parquet(tmp_path / "player_pool.parquet").columns


def test_build_slate_backups_cover_rank0_lineups_with_tagged_players():
    base, pw, tw, games = _injured_base()
    base.loc[base["name"] == "DDD WR1", "play_prob"] = config.Q_PLAY_PROB
    res = build.build_slate(base, pw, tw, MODEL, games, n_sims=300, seed=1, n_candidates=3, field_size=150)
    lus, bk = res["lineups"], res["injury_backups"]
    q = int(res["pool"].set_index("name").loc["DDD WR1", "dk_id"])
    keys_with_q = set(lus[(lus["rank"] == 0) & (lus.dk_id == q)].contest_key)
    assert set(bk.loc[bk.tagged_dk_id == q, "contest_key"]) == keys_with_q
