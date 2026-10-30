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


def _plain_base():
    """No injury columns; CCC WR1 (Q, blurb "ruled out") shown as unplayable, AAA RB1 Doubtful."""
    pool_base, pw, tw, games = _inputs()
    pool_base.loc[pool_base["name"] == "CCC WR1", "playable"] = False
    pool_base.loc[pool_base["name"] == "AAA RB1", ["status", "playable"]] = ["D", False]
    return pool_base, pw, tw, games


def _build(base, pw, tw, games):
    return build.build_slate(base, pw, tw, MODEL, games, n_sims=300, seed=1, n_candidates=3, field_size=150)


@pytest.fixture(scope="module")
def injured_build():
    """The untagged build's most-used rank-0 player turns Q (unclear news); CCC WR1 is Q with "ruled out"."""
    from nfldfs import injuries
    base, pw, tw, games = _plain_base()
    plain = _build(base, pw, tw, games)
    rec = plain["lineups"][plain["lineups"]["rank"] == 0]
    fav = rec["name"].value_counts().index[0]
    tagged = base.copy()
    tagged["lean"] = ""
    tagged.loc[tagged["name"] == "CCC WR1", ["status", "lean", "playable"]] = ["Q", "out", True]
    tagged.loc[tagged["name"] == fav, "status"] = "Q"
    return fav, plain, _build(injuries.classify(tagged), pw, tw, games)


def test_build_slate_carries_injury_columns_and_backups(tmp_path, injured_build):
    import pandas as pd
    fav, plain, res = injured_build
    p = res["pool"]
    assert {"inj_tag", "inj_class", "lean", "recommendable", "play_prob"} <= set(p.columns)
    assert p.set_index("name").loc[fav, "play_prob"] == config.Q_PLAY_PROB
    assert not {"CCC WR1", "AAA RB1"} & set(res["lineups"]["name"])
    bk = res["injury_backups"]
    assert len(bk) > 0
    assert list(bk.columns) == ["contest_key"] + build.lineups.BACKUP_COLUMNS
    # displayed projections stay the when-he-plays numbers (lean-out is projected like Doubtful)
    by, pl = p.set_index("name"), plain["pool"].set_index("name")
    assert by.loc[fav, "median"] == pytest.approx(pl.loc[fav, "median"])
    assert by.loc["CCC WR1", "median"] == 0 and by.loc["CCC WR1", "tgt_share"] == 0
    q = p.index[p["name"] == fav][0]
    assert 0.05 < (res["sims"][:, q] == 0).mean() < 0.3
    build.write_published(res, tmp_path, {"x": 1})
    pub = pd.read_parquet(tmp_path / "injury_backups.parquet")
    assert list(pub.columns) == list(bk.columns) and len(pub) == len(bk) and pub.contest_key.notna().all()
    assert "inj_tag" in pd.read_parquet(tmp_path / "player_pool.parquet").columns


def test_build_slate_backups_cover_rank0_lineups_with_tagged_players(injured_build):
    fav, _, res = injured_build
    lus, bk = res["lineups"], res["injury_backups"]
    q = int(res["pool"].set_index("name").loc[fav, "dk_id"])
    keys_with_q = set(lus[(lus["rank"] == 0) & (lus.dk_id == q)].contest_key)
    assert keys_with_q                                                  # the test is not vacuous
    assert set(bk.loc[bk.tagged_dk_id == q, "contest_key"]) == keys_with_q
    assert len(bk) == len(keys_with_q) and set(bk.kind) <= {"1:1", "two-player", "none"}
    ids_in = {int(i) for ids in bk.in_dk_ids for i in ids}
    healthy = set(res["pool"].loc[res["pool"].inj_class == "healthy", "dk_id"].astype(int))
    assert ids_in <= healthy


def test_build_slate_survives_backup_failure(monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("backups broke")
    monkeypatch.setattr(build, "rank0_backups", boom)
    pool_base, pw, tw, games = _inputs()
    with caplog.at_level("ERROR", logger="nfldfs.build"):
        res = build.build_slate(pool_base, pw, tw, MODEL, games, n_sims=200, seed=1, n_candidates=2,
                                field_size=100)
    bk = res["injury_backups"]
    assert len(bk) == 0 and list(bk.columns) == ["contest_key", *build.lineups.BACKUP_COLUMNS]
    assert len(res["lineups"]) and "injury backups failed" in caplog.text
