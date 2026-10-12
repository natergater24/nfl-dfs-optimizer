import numpy as np
import pandas as pd
import pytest

from nfldfs import shares


def _weeks(n=6, player_targets=10, team_targets=40):
    pw = pd.DataFrame({"player_id": "P1", "name": "Kenneth Walker", "position": "WR", "team": "KC",
                       "season": 2026, "week": range(1, n + 1), "targets": player_targets, "receptions": 6,
                       "rec_yds": 80.0, "carries": 0, "rush_yds": 0.0})
    tw = pd.DataFrame({"season": 2026, "week": range(1, n + 1), "team": "KC",
                       "targets": team_targets, "carries": 25})
    return pw, tw


def test_compute_shares_recency_weighted_and_shrunk():
    pw, tw = _weeks()
    s = shares.compute_shares(pw, tw).iloc[0]
    n_eff = sum(0.5 ** (age / 3.0) for age in range(6))
    expected = (6 * 0.25 + 0.5 * shares.POSITION_PRIORS["WR"]["tgt_share"]) / (6 + 0.5)
    assert s.tgt_share == pytest.approx(expected, rel=1e-6)
    assert s.games == 6 and s.n_eff == pytest.approx(n_eff)
    assert s.catch_rate == pytest.approx((36 + 10 * 0.64) / (60 + 10))


def test_compute_shares_uses_only_last_n_games():
    pw, tw = _weeks(n=10)
    pw.loc[pw.week <= 4, "targets"] = 0          # old weeks outside the window must not count
    s = shares.compute_shares(pw, tw, n_games=6).iloc[0]
    assert s.games == 6 and s.tgt_share > 0.2


def _pool(rows):
    base = dict(position="WR", team="KC", playable=True)
    return pd.DataFrame([{**base, **r} for r in rows])


def test_suffix_name_matches():
    pw, tw = _weeks()
    out = shares.attach_shares(_pool([{"name": "Kenneth Walker III"}]), shares.compute_shares(pw, tw))
    assert bool(out.matched.iloc[0]) and out.tgt_share.iloc[0] > 0.2


def test_unmatched_player_gets_fallback_shares():
    pw, tw = _weeks()
    out = shares.attach_shares(_pool([{"name": "Brand New Rookie"}, {"name": "Chiefs", "position": "DST"}]),
                               shares.compute_shares(pw, tw))
    rookie, dst = out.iloc[0], out.iloc[1]
    assert not bool(rookie.matched)
    assert rookie.tgt_share == shares.UNKNOWN_PLAYER_SHARE["WR"]["tgt_share"]
    assert rookie.ypt == shares.EFFICIENCY_PRIORS["ypt"]["WR"]
    assert bool(dst.matched) and dst.tgt_share == 0.0 and dst.carry_share == 0.0


def test_redistribute_moves_out_wr_targets_to_teammates():
    pool = _pool([{"name": "A", "tgt_share": 0.3, "carry_share": 0.0, "playable": False},
                  {"name": "B", "tgt_share": 0.2, "carry_share": 0.0},
                  {"name": "C", "tgt_share": 0.1, "carry_share": 0.0}])
    out = shares.redistribute(pool).set_index("name")
    assert out.loc["A", "tgt_share"] == 0.0
    assert out.loc["B", "tgt_share"] == pytest.approx(0.4)
    assert out.loc["C", "tgt_share"] == pytest.approx(0.2)


def test_redistribute_moves_out_qb_carries_to_backup():
    pool = _pool([{"name": "Starter", "position": "QB", "tgt_share": 0.0, "carry_share": 0.12, "playable": False},
                  {"name": "Backup", "position": "QB", "tgt_share": 0.0, "carry_share": 0.0}])
    out = shares.redistribute(pool).set_index("name")
    assert out.loc["Backup", "carry_share"] == pytest.approx(0.12) and out.loc["Starter", "carry_share"] == 0.0


def test_redistribute_caps_team_total():
    pool = _pool([{"name": n, "tgt_share": 0.4, "carry_share": 0.0} for n in "XYZ"])
    out = shares.redistribute(pool)
    assert out.tgt_share.sum() == pytest.approx(shares.MAX_TEAM_SHARE)


def test_starter_share_survives_team_cap():
    rows, trows = [], []
    for wk in range(1, 7):
        rows.append(dict(player_id="S", name="Starter", position="RB", team="KC", season=2026, week=wk,
                         targets=0, receptions=0, rec_yds=0.0, carries=17, rush_yds=70.0))
        trows.append(dict(season=2026, week=wk, team="KC", targets=35, carries=26))
    for i in range(3):
        rows.append(dict(player_id=f"B{i}", name=f"Backup{i}", position="RB", team="KC", season=2026, week=6,
                         targets=0, receptions=0, rec_yds=0.0, carries=1, rush_yds=4.0))
    pw, tw = pd.DataFrame(rows), pd.DataFrame(trows)
    sh = shares.compute_shares(pw, tw)
    pool = pd.DataFrame([dict(name=n, position="RB", team="KC", playable=True)
                         for n in ["Starter", "Backup0", "Backup1", "Backup2"]])
    out = shares.redistribute(shares.attach_shares(pool, sh))
    assert out.loc[out.name == "Starter", "carry_share"].iloc[0] >= 0.55
    assert out.carry_share.sum() <= shares.MAX_TEAM_SHARE + 1e-9


def test_shares_only_count_games_with_current_team():
    rows, trows = [], []
    for wk in range(1, 10):
        team = "WAS" if wk <= 6 else "ATL"
        rows.append(dict(player_id="R1", name="Brian Robinson", position="RB", team=team, season=2026, week=wk,
                         targets=0, receptions=0, rec_yds=0.0, carries=15 if wk <= 6 else 3, rush_yds=50.0))
        for t in ("WAS", "ATL"):
            if (t == team):
                trows.append(dict(season=2026, week=wk, team=t, targets=30, carries=25))
    pw, tw = pd.DataFrame(rows), pd.DataFrame(trows)
    sh = shares.compute_shares(pw, tw)
    by = sh.set_index("team")
    assert by.loc["ATL", "carry_share"] < 0.3 and by.loc["WAS", "carry_share"] > 0.5
    assert sh.iloc[0].team == "ATL"
    out = shares.attach_shares(_pool([{"name": "Brian Robinson", "position": "RB", "team": "ATL"}]), sh)
    assert out.carry_share.iloc[0] == pytest.approx(by.loc["ATL", "carry_share"])
    out2 = shares.attach_shares(_pool([{"name": "Brian Robinson", "position": "RB", "team": "XXX"}]), sh)
    assert out2.carry_share.iloc[0] == pytest.approx(by.loc["ATL", "carry_share"])


def _cap_pool(rows):
    return _pool([{"carry_share": 0.0, **r} for r in rows])


def test_cap_trims_low_evidence_players_first():
    pool = _cap_pool([{"name": "S", "tgt_share": 0.60, "games": 6},
                      {"name": "L1", "tgt_share": 0.30, "games": 1},
                      {"name": "L2", "tgt_share": 0.30, "games": 1},
                      {"name": "U", "tgt_share": 0.10, "games": 0}])
    out = shares.redistribute(pool).set_index("name")
    assert out.loc["S", "tgt_share"] == pytest.approx(0.60)
    assert out.tgt_share.sum() == pytest.approx(shares.MAX_TEAM_SHARE)


def test_cap_falls_back_to_scaling_when_low_evidence_exhausted():
    pool = _cap_pool([{"name": "S", "tgt_share": 0.9, "games": 6},
                      {"name": "L", "tgt_share": 0.4, "games": 1}])
    out = shares.redistribute(pool).set_index("name")
    scale = shares.MAX_TEAM_SHARE / 1.0     # low-evidence floored at 0.1, total 1.0, then scaled
    assert out.loc["L", "tgt_share"] == pytest.approx(0.1 * scale)
    assert out.loc["S", "tgt_share"] == pytest.approx(0.9 * scale)
    assert out.tgt_share.sum() == pytest.approx(shares.MAX_TEAM_SHARE)


def test_attach_shares_adds_games_column():
    pw, tw = _weeks()
    out = shares.attach_shares(_pool([{"name": "Kenneth Walker"}, {"name": "Nobody New"},
                                      {"name": "Chiefs", "position": "DST"}]), shares.compute_shares(pw, tw))
    assert list(out.games) == [6, 0, 0]
