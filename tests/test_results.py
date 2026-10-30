import datetime as dt
import os
import zipfile

import numpy as np
import pandas as pd
import pytest

from nfldfs import results

CSV = ("Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS\n"
       "1,111,secretuser (1/3),0,150.5,QB AAA QB1 ...,,AAA QB1,QB,40.00%,25.1\n"
       "2,112,otheruser,0,140.1,QB BBB QB1 ...,,AAA WR1,WR,12.50%,18.3\n"
       ",,,,,,,BBB DST1,DST,5.25%,7\n")


def _zip(path, csv=CSV):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("contest-standings-999.csv", csv)
    return path


def _snapshot():
    from tests.conftest import make_pool
    p = make_pool()
    p["median"], p["floor"], p["ceiling"], p["own_pct"] = 10.0, 5.0, 20.0, 8.0
    p.loc[p["name"] == "AAA QB1", ["median", "own_pct"]] = [20.0, 30.0]
    p.loc[p["name"] == "AAA WR4", "playable"] = False
    return p


def test_read_standings_zip_and_privacy(tmp_path):
    s = results.read_standings(_zip(tmp_path / "contest-standings-999.zip"))
    assert list(s.columns) == ["name", "roster_position", "actual_own", "actual_pts"]
    assert s.set_index("name").loc["AAA QB1", "actual_own"] == 40.0
    assert s.set_index("name").loc["BBB DST1", "actual_pts"] == 7.0
    assert "secretuser" not in s.to_csv()


def test_read_standings_rejects_other_files(tmp_path):
    (tmp_path / "x.csv").write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="contest standings"):
        results.read_standings(tmp_path / "x.csv")


def test_find_new_standings_skips_done(tmp_path):
    dl, done = tmp_path / "Downloads", tmp_path / "done"
    dl.mkdir(); done.mkdir()
    _zip(dl / "contest-standings-1.zip"); _zip(dl / "contest-standings-2.zip"); (dl / "other.zip").write_text("x")
    _zip(done / "contest-standings-1.zip")
    assert [p.name for p in results.find_new_standings(dl, done)] == ["contest-standings-2.zip"]


def test_find_new_standings_surfaces_permission_errors(tmp_path, monkeypatch):
    def deny(path):
        raise PermissionError("Operation not permitted")
    monkeypatch.setattr(os, "listdir", deny)
    with pytest.raises(PermissionError):
        results.find_new_standings(tmp_path, tmp_path / "done")


def test_latest_snapshot_uses_file_date(tmp_path):
    for name in ("2026-10-11_100.parquet", "2026-10-18_154941.parquet", "2026-10-25_160000.parquet"):
        (tmp_path / name).write_bytes(b"")
    assert results.latest_slate_snapshot(tmp_path, dt.date(2026, 10, 19)).name == "2026-10-18_154941.parquet"
    assert results.latest_slate_snapshot(tmp_path, dt.date(2026, 10, 10)) is None
    assert results.snapshot_key(tmp_path / "2026-10-18_154941.parquet") == ("2026-10-18", "154941")


def test_match_to_slate_includes_undrafted_as_zero(tmp_path):
    s = results.read_standings(_zip(tmp_path / "c.zip"))
    rows = results.match_to_slate(s, _snapshot(), "2026-10-18", "154941")
    assert list(rows.columns) == results.HISTORY_COLUMNS
    by = rows.set_index("name")
    assert by.loc["AAA QB1", "actual_own"] == 40.0 and by.loc["AAA QB1", "actual_pts"] == 25.1
    assert by.loc["AAA RB1", "actual_own"] == 0.0 and np.isnan(by.loc["AAA RB1", "actual_pts"])
    assert "AAA WR4" not in by.index                          # unplayable players are left out
    assert (rows.slate_date == "2026-10-18").all()


def test_append_history_dedups_and_report_card(tmp_path):
    s = results.read_standings(_zip(tmp_path / "c.zip"))
    rows = results.match_to_slate(s, _snapshot(), "2026-10-18", "154941")
    path = tmp_path / "history" / "results.parquet"
    results.append_history(path, rows)
    hist = results.append_history(path, rows)                 # same slate twice → no duplicates
    assert len(hist) == len(rows)
    card = results.report_card(hist)
    assert card["weeks"] == 1 and card["latest_slate"] == "2026-10-18"
    lat = card["latest"]
    assert lat["scored"] == 3
    # AAA QB1: |25.1-20|=5.1, AAA WR1: |18.3-10|=8.3, BBB DST1: |7-10|=3 → mean 5.47
    assert lat["proj_mae"] == pytest.approx(5.47, abs=0.01)
    assert 0 <= lat["in_range_pct"] <= 100 and lat["own_mae"] >= 0
    assert results.report_card(pd.DataFrame(columns=results.HISTORY_COLUMNS)) == {"weeks": 0}


def test_match_share_counts_standings_players_on_the_slate(tmp_path):
    s = results.read_standings(_zip(tmp_path / "c.zip"))
    assert results.match_share(s, _snapshot()) == 1.0
    other = CSV + ",,,,,,,Joe Burrow,QB,10.00%,20\n,,,,,,,Ja'Marr Chase,WR,9.00%,15\n"
    s2 = results.read_standings(_zip(tmp_path / "d.zip", other))
    assert results.match_share(s2, _snapshot()) == pytest.approx(3 / 5)
    assert results.MIN_STANDINGS_MATCH == 0.80


def test_match_to_slate_leaves_out_lean_out_players(tmp_path):
    # AAA WR1 is Q with news leaning out (median 0 in the build): he scored 18.3, which is no projection miss
    s = results.read_standings(_zip(tmp_path / "c.zip"))
    snap = _snapshot()
    snap["recommendable"] = snap["playable"]
    snap.loc[snap["name"] == "AAA WR1", ["recommendable", "median"]] = [False, 0.0]
    rows = results.match_to_slate(s, snap, "2026-10-18", "154941")
    assert "AAA WR1" not in set(rows["name"]) and "AAA QB1" in set(rows["name"])
    assert results.report_card(rows)["latest"]["scored"] == 2
