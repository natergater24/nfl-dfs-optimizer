import math

import numpy as np
import pandas as pd
import pytest

from nfldfs import player_history as ph
from tests.conftest import make_pool


def _pool():
    p = make_pool()
    p["median"], p["floor"], p["ceiling"], p["own_pct"] = 10.0, 5.0, 20.0, 8.0
    p["mu_label"], p["mu_color"] = "Good", "#2a7"
    p.loc[p["name"] == "AAA WR6", "playable"] = False
    return p


def test_slate_rows_and_upsert_keeps_actuals(tmp_path):
    path = tmp_path / "pw.parquet"
    rows = ph.slate_rows(_pool(), "2026-10-18")
    assert list(rows.columns) == ph.PW_COLUMNS and "AAA WR6" not in set(rows["name"])
    ph.upsert_slate(path, rows)
    qb = int(rows.loc[rows["name"] == "AAA QB1", "dk_id"].iloc[0])
    assert ph.set_actuals(path, "2026-10-18", pd.DataFrame({"dk_id": [qb], "actual_pts": [25.1]})) == 1
    again = rows.copy()
    again["median"] = 11.0                                     # a rebuild of the same slate
    out = ph.upsert_slate(path, again)
    r = out[(out.slate_date == "2026-10-18") & (out.dk_id == qb)].iloc[0]
    assert r["median"] == 11.0 and r["actual_pts"] == 25.1 and len(out) == len(rows)
    ph.upsert_slate(path, ph.slate_rows(_pool(), "2026-10-11"))
    assert ph.load(path)["slate_date"].nunique() == 2


def test_set_actuals_own_only_keeps_points(tmp_path):
    path = tmp_path / "pw.parquet"
    rows = ph.slate_rows(_pool(), "2026-10-18")
    ph.upsert_slate(path, rows)
    qb = int(rows.loc[rows["name"] == "AAA QB1", "dk_id"].iloc[0])
    ph.set_actuals(path, "2026-10-18", pd.DataFrame({"dk_id": [qb], "actual_pts": [25.1]}))
    ph.set_actuals(path, "2026-10-18", pd.DataFrame({"dk_id": [qb], "actual_own": [40.0], "actual_pts": [np.nan]}))
    r = ph.load(path).set_index("dk_id").loc[qb]
    assert r["actual_pts"] == 25.1 and r["actual_own"] == 40.0


def test_nflverse_actuals_matches_offense_only():
    rows = ph.slate_rows(_pool(), "2026-10-18")
    stats = pd.DataFrame({"name": ["AAA QB1", "AAA WR1", "Not On Slate"], "team": ["AAA", "AAA", "AAA"],
                          "position": ["QB", "WR", "WR"], "season": 2026, "week": 7, "dk_pts": [22.0, 15.5, 3.0]})
    a = ph.nflverse_actuals(rows, stats).merge(rows[["dk_id", "name"]], on="dk_id").set_index("name")
    assert a.loc["AAA QB1", "actual_pts"] == 22.0 and a.loc["AAA WR1", "actual_pts"] == 15.5
    assert len(a) == 2


def test_week_dates_and_lookup():
    sched = pd.DataFrame({"season": [2026, 2026, 2026], "week": [7, 7, 8], "game_type": ["REG"] * 3,
                          "gameday": ["2026-10-15", "2026-10-18", "2026-10-25"]})
    wd = ph.week_dates(sched)
    assert ph.week_for(wd, "2026-10-18") == (2026, 7) and ph.week_for(wd, "2026-12-01") is None


def test_search_with_entries():
    pw = pd.concat([ph.slate_rows(_pool(), "2026-10-11"), ph.slate_rows(_pool(), "2026-10-18")], ignore_index=True)
    qb = int(pw.loc[pw["name"] == "AAA QB1", "dk_id"].iloc[0])
    pw.loc[(pw.dk_id == qb) & (pw.slate_date == "2026-10-18"), "actual_pts"] = 30.0
    entries = pd.DataFrame({"entry_id": ["1"], "slate_date": ["2026-10-18"], "contest_name": ["NFL $25 Double Up"],
                            "players": [str(qb)], "entry_fee": [25.0], "winnings": [50.0]})
    summary, table = ph.search(pw, entries, "aaa qb1")
    assert summary["slates"] == 2 and summary["times_played"] == 1
    assert summary["avg_projected"] == 10.0 and summary["avg_actual"] == 30.0
    assert list(table["Slate"]) == ["2026-10-18", "2026-10-11"]
    assert table.iloc[0]["My entry"] == "NFL $25 Double Up · ✅ +$25" and table.iloc[1]["My entry"] == "—"
    _, mine = ph.search(pw, entries, "AAA QB1", mine_only=True)
    assert len(mine) == 1
    s, t = ph.search(pw, entries, "Nobody")
    assert s["slates"] == 0 and t.empty


def test_search_two_entries_same_slate_and_float_columns():
    pw = ph.slate_rows(_pool(), "2026-10-18")
    qb = int(pw.loc[pw["name"] == "AAA QB1", "dk_id"].iloc[0])
    entries = pd.DataFrame({"entry_id": ["1", "2"], "slate_date": ["2026-10-18"] * 2,
                            "contest_name": ["A", "B"], "players": [str(qb)] * 2,
                            "entry_fee": [25.0, 5.0], "winnings": [50.0, 0.0]})
    summary, table = ph.search(pw, entries, "AAA QB1")
    assert summary["times_played"] == 2
    assert table.iloc[0]["My entry"] == "A \u00b7 \u2705 +$25; B \u00b7 \u2717 \u2212$5"
    assert str(table["Actual"].dtype) == "float64"


def test_slate_rows_leave_out_lean_out_questionable_players():
    # a Q player whose news leans out is simulated as sitting (median 0): no honest projection to grade
    p = _pool()
    p["recommendable"] = True
    out_name, q_name = p["name"].iloc[0], p["name"].iloc[1]
    p.loc[p["name"] == out_name, ["recommendable", "median"]] = [False, 0.0]
    rows = ph.slate_rows(p, "2026-10-25")
    assert out_name not in set(rows["name"]) and q_name in set(rows["name"])
    assert (rows["median"] > 0).all()
    assert len(ph.slate_rows(p.drop(columns=["recommendable"]), "2026-10-25")) == len(rows) + 1  # old pools
