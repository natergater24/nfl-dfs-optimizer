from pathlib import Path

import pandas as pd
import pytest

from nbadfs import stats

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _long(name, **vals):
    base = {"gamesPlayed": ("10", 10.0), "avgMinutes": ("30.0", 30.0), "avgPoints": ("20.0", 20.0),
            "avgRebounds": ("10.0", 10.0), "avgAssists": ("5.0", 5.0), "avgSteals": ("1.0", 1.0),
            "avgBlocks": ("0.5", 0.5), "avgTurnovers": ("2.0", 2.0),
            "avgThreePointFieldGoalsMade-avgThreePointFieldGoalsAttempted": ("2.3-6.1", float("nan"))}
    base.update(vals)
    return pd.DataFrame([{"season": 2027, "athlete_id": 1, "athlete_display_name": name, "category": "averages",
                          "stat_name": k, "display_value": d, "value": v} for k, (d, v) in base.items()])


def test_player_rates():
    # 20 + 0.5*2.3 + 1.25*10 + 1.5*5 + 2*1 + 2*0.5 - 0.5*2 = 43.15 (no double-double bonus at the average level)
    r = stats.player_rates(_long("Luka Dončić")).iloc[0]
    assert r["name_key"] == "luka doncic" and r["games"] == 10 and r["minutes"] == 30.0
    assert r["dk_per_min"] == pytest.approx(43.15 / 30, abs=5e-4)


def test_player_rates_ignores_totals_rows_and_zero_minutes():
    df = pd.concat([_long("A B"), _long("A B").assign(category="totals", value=999.0)], ignore_index=True)
    assert len(stats.player_rates(df)) == 1
    z = _long("Z Z", avgMinutes=("0.0", 0.0))
    assert stats.player_rates(z).iloc[0]["dk_per_min"] == 0.0


def _pool():
    return pd.DataFrame({
        "name": ["Luka Doncic", "Jaren Jackson Jr.", "Coby White", "Nobody Here", "Bam Adebayo"],
        "playable": [True, True, True, True, False]})


def test_stats_match_accents_and_suffixes():
    sample = pd.read_parquet(FIX / "nba_espn_season_sample.parquet")
    last = stats.player_rates(sample[sample.season == 2026])
    cur = stats.player_rates(sample[sample.season == 2027])
    out, rate = stats.match_rates(_pool(), last, cur)
    o = out.set_index("name")
    assert o.loc["Luka Doncic", "games_last"] > 0 and o.loc["Luka Doncic", "games_cur"] > 0
    assert o.loc["Jaren Jackson Jr.", "rate_cur"] > 0 and o.loc["Jaren Jackson Jr.", "min_last"] > 0
    assert pd.isna(o.loc["Nobody Here", "rate_cur"]) and pd.isna(o.loc["Nobody Here", "rate_last"])
    assert pd.isna(o.loc["Coby White", "rate_cur"]) and o.loc["Coby White", "rate_last"] > 0   # only last season
    assert rate == pytest.approx(3 / 4)   # 3 of 4 playable players matched in either season
    assert {"games_last", "min_last", "rate_last", "games_cur", "min_cur", "rate_cur"} <= set(out.columns)


class _R:
    content = b"parquet-bytes"

    def raise_for_status(self):
        pass


class _S:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return _R()


def test_download_season_caches(tmp_path):
    import os
    s = _S()
    p = stats.download_season(2027, tmp_path, s)
    assert p.name == "player_season_stats_2027.parquet" and p.read_bytes() == b"parquet-bytes"
    assert "espn_nba_player_season_stats" in s.urls[0] and s.urls[0].endswith("player_season_stats_2027.parquet")
    stats.download_season(2027, tmp_path, s)
    assert len(s.urls) == 1                       # fresh: cached
    old = p.stat().st_mtime - 21 * 3600
    os.utime(p, (old, old))
    stats.download_season(2027, tmp_path, s)
    assert len(s.urls) == 2                       # >20 h old: re-downloaded
