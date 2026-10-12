import pandas as pd
import pytest

from nfldfs import nfl_stats


def _raw_stats():
    return pd.DataFrame({
        "player_id": ["00-1", "00-2", "00-3"], "player_display_name": ["Puka Nacua", "Matthew Stafford", "Some Kicker"],
        "position": ["WR", "QB", "K"], "recent_team": ["LA", "LA", "LA"], "season": [2026] * 3, "week": [5] * 3,
        "season_type": ["REG"] * 3, "attempts": [0, 35, 0], "passing_yards": [0, 310, 0], "passing_tds": [0, 2, 0],
        "interceptions": [0, 1, 0], "carries": [1, 2, 0], "rushing_yards": [5, 3, 0], "rushing_tds": [0, 0, 0],
        "targets": [9, 0, 0], "receptions": [7, 0, 0], "receiving_yards": [95, 0, 0], "receiving_tds": [1, 0, 0],
        "sack_fumbles_lost": [0, 1, 0], "rushing_fumbles_lost": [0, 0, 0],
        "passing_2pt_conversions": [0, 0, 0], "rushing_2pt_conversions": [0, 0, 0],
    })


def test_normalize_player_stats_handles_aliases_and_scores():
    ps = nfl_stats.normalize_player_stats(_raw_stats())
    assert list(ps.name) == ["Puka Nacua", "Matthew Stafford"]          # kicker dropped
    assert set(ps.team) == {"LAR"}
    by = ps.set_index("name")
    assert by.loc["Puka Nacua", "dk_pts"] == pytest.approx(23.0)
    assert by.loc["Matthew Stafford", "dk_pts"] == pytest.approx(21.7)
    assert by.loc["Matthew Stafford", "ints"] == 1 and by.loc["Matthew Stafford", "fumbles_lost"] == 1


def test_normalize_player_stats_errors_clearly_on_schema_change():
    with pytest.raises(KeyError, match="targets"):
        nfl_stats.normalize_player_stats(_raw_stats().drop(columns=["targets"]))


def test_normalize_player_stats_errors_when_all_fumble_columns_missing():
    raw = _raw_stats().drop(columns=["sack_fumbles_lost", "rushing_fumbles_lost"])
    with pytest.raises(KeyError, match="fumbles_lost"):
        nfl_stats.normalize_player_stats(raw)


def test_team_week_totals_sums_players():
    tw = nfl_stats.team_week_totals(nfl_stats.normalize_player_stats(_raw_stats()))
    row = tw.iloc[0]
    assert (row.team, row.pass_att, row.pass_yds, row.targets, row.carries, row.rush_yds) == ("LAR", 35, 310, 9, 3, 8)


def test_normalize_schedules_uses_nflverse_spread_convention():
    raw = pd.DataFrame({"season": [2026], "week": [5], "game_type": ["REG"], "home_team": ["LA"],
                        "away_team": ["ARI"], "home_score": [27], "away_score": [20],
                        "total_line": [47.0], "spread_line": [3.0]})
    s = nfl_stats.normalize_schedules(raw).set_index("team")
    assert s.loc["LAR", "implied_total"] == pytest.approx(25.0) and s.loc["LAR", "exp_margin"] == 3.0
    assert s.loc["ARI", "implied_total"] == pytest.approx(22.0) and s.loc["ARI", "points"] == 20
    assert bool(s.loc["LAR", "is_home"]) and s.loc["ARI", "opp"] == "LAR"
