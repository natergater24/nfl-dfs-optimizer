import pandas as pd
import pytest

from nfldfs import matchups


def _weeks():
    """Two offenses: AAA always faces soft defense XXX (30 WR pts), BBB faces tough YYY (10 WR pts)."""
    rows, sched = [], []
    for wk in range(1, 7):
        for off, dfn, pts in (("AAA", "XXX", 30.0), ("BBB", "YYY", 10.0)):
            rows.append(dict(season=2026, week=wk, team=off, position="WR", dk_pts=pts))
            sched += [dict(season=2026, week=wk, team=off, opp=dfn), dict(season=2026, week=wk, team=dfn, opp=off)]
    return pd.DataFrame(rows), pd.DataFrame(sched)


def test_defense_vs_position_ratio_and_rank():
    pw, s = _weeks()
    d = matchups.defense_vs_position(pw, s).set_index("defense")
    assert d.loc["XXX", "allowed"] == 30 and d.loc["YYY", "allowed"] == 10
    assert d.loc["XXX", "ratio"] == pytest.approx(1.5) and d.loc["YYY", "ratio"] == pytest.approx(0.5)
    assert d.loc["XXX", "rank"] == 1 and d.loc["YYY", "rank"] == 2


def test_only_last_n_games_count():
    pw, s = _weeks()
    pw.loc[(pw.team == "AAA") & (pw.week == 1), "dk_pts"] = 1000.0
    d = matchups.defense_vs_position(pw, s, n_games=5).set_index("defense")
    assert d.loc["XXX", "allowed"] == 30


def test_color_gradient_and_labels():
    red, green = matchups.matchup_color(0.5), matchups.matchup_color(1.5)
    assert len(red) == 7 and red.startswith("#")
    assert int(red[1:3], 16) > int(red[3:5], 16)          # red channel dominates
    assert int(green[3:5], 16) > int(green[1:3], 16)      # green channel dominates
    assert [matchups.matchup_label(x) for x in (1.2, 1.05, 1.0, 0.9, 0.7)] == \
        ["Great", "Good", "Neutral", "Tough", "Very tough"]


def test_attach_matchups_offense_dst_and_missing():
    pw, s = _weeks()
    d = matchups.defense_vs_position(pw, s)
    pool = pd.DataFrame([
        dict(name="W1", position="WR", team="AAA", opp="XXX", implied_total=24.0, opp_implied=20.0),
        dict(name="W2", position="WR", team="BBB", opp="YYY", implied_total=20.0, opp_implied=24.0),
        dict(name="T1", position="TE", team="BBB", opp="YYY", implied_total=20.0, opp_implied=24.0),
        dict(name="D1", position="DST", team="XXX", opp="AAA", implied_total=20.0, opp_implied=24.0),
        dict(name="D2", position="DST", team="YYY", opp="BBB", implied_total=24.0, opp_implied=18.0)])
    out = matchups.attach_matchups(pool, d)
    assert list(out["name"]) == ["W1", "W2", "T1", "D1", "D2"]               # row order preserved
    out = out.set_index("name")
    assert out.loc["W1", "mu_label"] == "Great" and out.loc["W2", "mu_label"] == "Very tough"
    assert "1st-easiest of 2" in out.loc["W1", "mu_text"]
    assert out.loc["T1", "mu_ratio"] == 1.0 and out.loc["T1", "mu_label"] == "Neutral"
    assert "not enough games" in out.loc["T1", "mu_text"]
    offense_avg = (24 + 20 + 20) / 3
    assert out.loc["D2", "mu_ratio"] == pytest.approx(offense_avg / 18, rel=1e-3)
    assert out.loc["D2", "mu_ratio"] > out.loc["D1", "mu_ratio"]
    assert "Vegas total is 18.0" in out.loc["D2", "mu_text"]


def test_attach_matchups_with_no_ratings_is_neutral():
    empty = pd.DataFrame(columns=["defense", "position", "allowed", "ratio", "rank"])
    pool = pd.DataFrame([dict(name="W1", position="WR", team="AAA", opp="XXX", implied_total=24.0, opp_implied=20.0)])
    out = matchups.attach_matchups(pool, empty)
    assert out.loc[0, "mu_label"] == "Neutral" and out.loc[0, "mu_ratio"] == 1.0
