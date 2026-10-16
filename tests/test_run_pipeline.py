import datetime as dt
import json
import os
import zipfile
from types import SimpleNamespace

import pandas as pd
import pytest

import run_pipeline
from nfldfs import config
from tests.conftest import make_pool


@pytest.fixture(autouse=True)
def _private_lock_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path / "data")     # never touch the real data/.pipeline.lock


def _hold_lock():
    import fcntl
    config.DATA.mkdir(parents=True, exist_ok=True)
    f = open(config.DATA / ".pipeline.lock", "w")
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return f


def test_every_stage_step_exists():
    for steps in run_pipeline.STAGES.values():
        for s in steps:
            assert s in run_pipeline.STEP_FUNCS


def test_failure_stops_run_and_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PUBLISHED", tmp_path / "published")
    monkeypatch.setattr(config, "LOGS", tmp_path / "logs")
    calls = []

    def ok(today, args):
        calls.append("ok")
        return "fine"

    def boom(today, args):
        raise RuntimeError("DraftKings returned HTML")

    monkeypatch.setattr(run_pipeline, "STAGES", {"test": ["a", "b", "c"]})
    monkeypatch.setattr(run_pipeline, "STEP_FUNCS", {"a": ok, "b": boom, "c": ok})
    assert run_pipeline.main(["--stage", "test", "--today", "2026-10-15"]) == 1
    assert calls == ["ok"]
    status = json.loads((tmp_path / "published" / "run_status.json").read_text())
    assert status["ok"] is False and [s["name"] for s in status["steps"]] == ["a", "b"]
    assert status["steps"][0]["message"] == "fine" and "HTML" in status["steps"][1]["message"]


def _fake_stats(tmp_path, monkeypatch, mtime):
    import datetime as dt
    import os

    import pandas as pd
    monkeypatch.setattr(config, "PROCESSED", tmp_path)
    pd.DataFrame({"season": [2026, 2026], "week": [4, 5]}).to_parquet(tmp_path / "player_weeks.parquet")
    for f in ("team_weeks.parquet", "team_model.json", "schedule_rows.parquet"):
        (tmp_path / f).write_text("x")
    ts = dt.datetime.combine(mtime, dt.time(12, 0)).timestamp()
    for f in ("player_weeks.parquet", "team_weeks.parquet", "team_model.json", "schedule_rows.parquet"):
        os.utime(tmp_path / f, (ts, ts))
    ran = []
    monkeypatch.setattr(run_pipeline, "step_stats", lambda today, args: ran.append(1) or "rebuilt")
    return ran


def test_stats_if_missing_skips_when_fresh_and_states_week(tmp_path, monkeypatch):
    import datetime as dt
    ran = _fake_stats(tmp_path, monkeypatch, dt.date(2026, 10, 13))    # Tuesday refresh
    msg = run_pipeline.step_stats_if_missing(dt.date(2026, 10, 15), None)   # Thursday
    assert ran == [] and msg == "skipped: stats current through 2026 week 5"


def test_stats_if_missing_reruns_when_older_than_last_tuesday(tmp_path, monkeypatch):
    import datetime as dt
    ran = _fake_stats(tmp_path, monkeypatch, dt.date(2026, 10, 12))    # Monday, before Tuesday 10/13
    assert run_pipeline.step_stats_if_missing(dt.date(2026, 10, 15), None) == "rebuilt" and ran == [1]


def test_stats_if_missing_reruns_when_files_missing(tmp_path, monkeypatch):
    import datetime as dt
    ran = _fake_stats(tmp_path, monkeypatch, dt.date(2026, 10, 13))
    (tmp_path / "team_model.json").unlink()
    run_pipeline.step_stats_if_missing(dt.date(2026, 10, 15), None)
    assert ran == [1]


def _paths(tmp_path, monkeypatch):
    for name in ("PUBLISHED", "PROCESSED", "RAW", "HISTORY", "LOGS"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    monkeypatch.setattr(config, "SLATES", tmp_path / "processed" / "slates")
    monkeypatch.setattr(config, "DOWNLOADS", tmp_path / "Downloads")
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "processed").mkdir()


def _odds(tmp_path, hours_ago):
    fetched = (dt.datetime.now() - dt.timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    (tmp_path / "processed" / "odds_meta.json").write_text(json.dumps({"fetched_at": fetched}))
    (tmp_path / "processed" / "vegas_games.parquet").write_bytes(b"x")


def test_vegas_if_stale_skips_recent_lines(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch); _odds(tmp_path, 1)
    monkeypatch.setattr(run_pipeline, "step_vegas", lambda t, a: pytest.fail("should not refetch"))
    assert run_pipeline.step_vegas_if_stale(dt.date(2026, 10, 18), SimpleNamespace()).startswith("skipped")


def test_vegas_if_stale_refetches_old_lines(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch); _odds(tmp_path, 5)
    monkeypatch.setattr(run_pipeline, "step_vegas", lambda t, a: "fetched")
    assert run_pipeline.step_vegas_if_stale(dt.date(2026, 10, 18), SimpleNamespace()) == "fetched"


def test_vegas_falls_back_to_recent_lines(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch); _odds(tmp_path, 10)
    monkeypatch.setattr(config, "odds_api_key", lambda: "k")
    def boom(key):
        raise RuntimeError("The Odds API request failed (HTTP 429)")
    monkeypatch.setattr(run_pipeline.vegas, "fetch_odds", boom)
    msg = run_pipeline.step_vegas(dt.date(2026, 10, 18), SimpleNamespace())
    assert msg.startswith("WARNING") and "Reusing lines" in msg
    _odds(tmp_path, 60)
    with pytest.raises(RuntimeError):
        run_pipeline.step_vegas(dt.date(2026, 10, 18), SimpleNamespace())


def test_results_stage_writes_its_own_status(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    (tmp_path / "Downloads" / "contest-standings-1.zip").write_bytes(b"PK")
    monkeypatch.setitem(run_pipeline.STEP_FUNCS, "results", lambda t, a: "imported 1 file(s)")
    monkeypatch.setitem(run_pipeline.STEP_FUNCS, "publish", lambda t, a: "skipped: test")
    assert run_pipeline.main(["--stage", "results", "--today", "2026-10-19"]) == 0
    status = json.loads((tmp_path / "published" / "results_status.json").read_text())
    assert status["steps"][0]["message"] == "imported 1 file(s)"
    assert not (tmp_path / "published" / "run_status.json").exists()


def test_results_stage_without_new_file_touches_nothing(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    (tmp_path / "published").mkdir()
    prev = b'{"stage": "results", "ok": true, "steps": [{"name": "results", "ok": true, "message": "imported 1"}]}'
    (tmp_path / "published" / "results_status.json").write_bytes(prev)
    monkeypatch.setitem(run_pipeline.STEP_FUNCS, "publish", lambda t, a: pytest.fail("must not publish"))
    assert run_pipeline.main(["--stage", "results", "--today", "2026-10-19"]) == 0
    assert (tmp_path / "published" / "results_status.json").read_bytes() == prev


def _snapshot_file(tmp_path, date="2026-10-18"):
    p = make_pool()
    p["median"], p["floor"], p["ceiling"], p["own_pct"] = 10.0, 5.0, 20.0, 8.0
    (tmp_path / "processed" / "slates").mkdir(parents=True, exist_ok=True)
    p.to_parquet(tmp_path / "processed" / "slates" / f"{date}_154941.parquet", index=False)


def _standings_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("contest-standings-1.csv",
                   "Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS\n"
                   "1,1,someone,0,100,x,,AAA QB1,QB,30.00%,22.0\n")
    return path


def test_step_results_imports_moves_and_reports(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch); _snapshot_file(tmp_path)
    z = _standings_zip(tmp_path / "Downloads" / "contest-standings-1.zip")
    monday = dt.datetime(2026, 10, 19, 9, 0).timestamp()
    os.utime(z, (monday, monday))                                 # file date drives slate matching
    msg = run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert "2026-10-18" in msg
    assert not z.exists() and (tmp_path / "raw" / "standings" / z.name).exists()
    hist = pd.read_parquet(tmp_path / "history" / "results.parquet")
    assert "EntryName" not in hist.columns and "someone" not in hist.to_csv()
    assert json.loads((tmp_path / "published" / "report_card.json").read_text())["weeks"] == 1


def test_step_results_matches_by_download_date(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    _snapshot_file(tmp_path, "2026-10-18"); _snapshot_file(tmp_path, "2026-10-25")
    z = _standings_zip(tmp_path / "Downloads" / "contest-standings-1.zip")
    monday = dt.datetime(2026, 10, 19, 9, 0).timestamp()
    os.utime(z, (monday, monday))                                 # downloaded the Monday after 10/18
    msg = run_pipeline.step_results(dt.date(2026, 10, 27), SimpleNamespace(results_file=None))
    assert "2026-10-18" in msg                                    # not the 10/25 slate


def _wrong_contest_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("contest-standings-9.csv",
                   "Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS\n"
                   "1,1,someone,0,100,x,,AAA QB1,QB,30.00%,22.0\n"
                   + "".join(f",,,,,,,Other Player{i},WR,5.00%,9.0\n" for i in range(9)))
    return path


def _monday(*paths):
    ts = dt.datetime(2026, 10, 19, 9, 0).timestamp()
    for p in paths:
        os.utime(p, (ts, ts))


def test_step_results_skips_wrong_contest_file(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch); _snapshot_file(tmp_path)
    z = _wrong_contest_zip(tmp_path / "Downloads" / "contest-standings-9.zip")
    _monday(z)
    with pytest.raises(RuntimeError, match="wrong contest"):
        run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert not z.exists() and (tmp_path / "raw" / "standings" / "skipped" / z.name).exists()
    assert not (tmp_path / "history" / "results.parquet").exists()


def test_step_results_bad_file_does_not_block_good_one(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch); _snapshot_file(tmp_path)
    bad = tmp_path / "Downloads" / "contest-standings-0.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("notes.txt", "not a csv")
    good = _standings_zip(tmp_path / "Downloads" / "contest-standings-1.zip")
    _monday(bad, good)
    with pytest.raises(RuntimeError) as e:
        run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert "contest-standings-0.zip" in str(e.value) and "imported 1 file" in str(e.value)
    assert (tmp_path / "raw" / "standings" / good.name).exists()
    assert (tmp_path / "raw" / "standings" / "skipped" / bad.name).exists()
    assert len(pd.read_parquet(tmp_path / "history" / "results.parquet"))
    assert json.loads((tmp_path / "published" / "report_card.json").read_text())["weeks"] == 1


def _stage_with_publish(tmp_path, monkeypatch, a_fn):
    monkeypatch.setattr(config, "PUBLISHED", tmp_path / "published")
    monkeypatch.setattr(config, "LOGS", tmp_path / "logs")
    seen = []

    def fake_publish(today, args):
        seen.append(json.loads((tmp_path / "published" / "run_status.json").read_text()))
        return "published to GitHub"

    monkeypatch.setattr(run_pipeline, "STAGES", {"test": ["a", "publish"]})
    monkeypatch.setattr(run_pipeline, "STEP_FUNCS", {"a": a_fn, "publish": fake_publish})
    return seen


def test_publish_runs_after_failure_with_final_status(tmp_path, monkeypatch):
    def boom(t, a):
        raise RuntimeError("nope")
    seen = _stage_with_publish(tmp_path, monkeypatch, boom)
    assert run_pipeline.main(["--stage", "test", "--today", "2026-10-15"]) == 1
    assert len(seen) == 1 and seen[0]["ok"] is False and seen[0]["finished"]


def test_publish_runs_after_status_finish_on_success(tmp_path, monkeypatch):
    seen = _stage_with_publish(tmp_path, monkeypatch, lambda t, a: "fine")
    assert run_pipeline.main(["--stage", "test", "--today", "2026-10-15"]) == 0
    assert len(seen) == 1 and seen[0]["ok"] is True and seen[0]["finished"]


def test_results_stage_returns_quietly_while_another_run_holds_the_lock(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    (tmp_path / "Downloads" / "contest-standings-1.zip").write_bytes(b"PK")
    monkeypatch.setitem(run_pipeline.STEP_FUNCS, "results", lambda t, a: pytest.fail("must not run"))
    monkeypatch.setitem(run_pipeline.STEP_FUNCS, "publish", lambda t, a: pytest.fail("must not publish"))
    held = _hold_lock()
    try:
        assert run_pipeline.main(["--stage", "results", "--today", "2026-10-19"]) == 0
    finally:
        held.close()
    assert not (tmp_path / "published" / "results_status.json").exists()


def test_other_stages_wait_for_the_lock_then_fail(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_pipeline, "LOCK_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(run_pipeline, "LOCK_POLL_SECONDS", 0.05)
    monkeypatch.setattr(run_pipeline, "STAGES", {"test": ["a"]})
    monkeypatch.setattr(run_pipeline, "STEP_FUNCS", {"a": lambda t, a: pytest.fail("must not run")})
    held = _hold_lock()
    try:
        assert run_pipeline.main(["--stage", "test", "--today", "2026-10-15"]) == 1
    finally:
        held.close()


def test_lock_is_released_after_a_run(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_pipeline, "STAGES", {"test": ["a"]})
    monkeypatch.setattr(run_pipeline, "STEP_FUNCS", {"a": lambda t, a: "fine"})
    assert run_pipeline.main(["--stage", "test", "--today", "2026-10-15"]) == 0
    _hold_lock().close()                                          # would raise BlockingIOError if still held


def _standings_zip_with_me(path):
    lineup = ("DST BBB DST1 FLEX AAA RB2 QB AAA QB1 RB AAA RB1 RB BBB RB1 TE AAA TE1 "
              "WR AAA WR1 WR AAA WR2 WR BBB WR1")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("contest-standings-555.csv",
                   "Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS\n"
                   f"1,1,someoneelse,0,150,{lineup},,AAA QB1,QB,30.00%,22.0\n"
                   f"2,2,natergater24,0,140,{lineup},,AAA WR1,WR,12.00%,18.0\n")
    return path


def test_results_import_creates_entries_without_usernames(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    _snapshot_file(tmp_path)
    monkeypatch.setattr(config, "dk_username", lambda: "natergater24")
    pd.DataFrame([{"contest_id": "555", "contest_name": "NFL GIANT $25 Double Up", "entry_fee": 25.0,
                   "max_entries": 2758}]).to_parquet(tmp_path / "processed" / "contests.parquet", index=False)
    z = _standings_zip_with_me(tmp_path / "Downloads" / "contest-standings-555.zip")
    _monday(z)
    msg = run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert "1 of your entries" in msg
    e = pd.read_parquet(tmp_path / "history" / "entries.parquet")
    assert len(e) == 1 and e.iloc[0]["contest_type"] == "double_up" and e.iloc[0]["entry_fee"] == 25.0
    for folder in ("history", "published"):
        for f in (tmp_path / folder).rglob("*"):
            if f.is_file():
                blob = f.read_bytes().lower()
                assert b"natergater24" not in blob and b"someoneelse" not in blob, f


def test_results_import_without_username_says_how_to_enable(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    _snapshot_file(tmp_path)
    monkeypatch.setattr(config, "dk_username", lambda: None)
    z = _standings_zip_with_me(tmp_path / "Downloads" / "contest-standings-555.zip")
    _monday(z)
    msg = run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert "DK_USERNAME" in msg and not (tmp_path / "history" / "entries.parquet").exists()


def test_fill_nflverse_actuals(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    from nfldfs import player_history as ph
    pool = make_pool()
    pool["median"], pool["floor"], pool["ceiling"], pool["own_pct"] = 10.0, 5.0, 20.0, 8.0
    ph.upsert_slate(tmp_path / "history" / "player_weeks.parquet", ph.slate_rows(pool, "2026-10-18"))
    stats = pd.DataFrame({"name": ["AAA QB1"], "team": ["AAA"], "position": ["QB"], "season": [2026], "week": [7],
                          "dk_pts": [21.5]})
    wd = pd.DataFrame({"season": [2026], "week": [7], "gameday": ["2026-10-18"]})
    assert run_pipeline.fill_nflverse_actuals(stats, wd) == 1
    pw = ph.load(tmp_path / "history" / "player_weeks.parquet")
    assert pw.loc[pw["name"] == "AAA QB1", "actual_pts"].iloc[0] == 21.5


def test_salaries_step_saves_lobby_contests(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    from pathlib import Path as _P
    csv_text = (_P(__file__).parent / "fixtures" / "dk_salaries_sample.csv").read_bytes().decode("utf-8")
    lobby = {"DraftGroups": [{"DraftGroupId": 154941, "ContestTypeId": 21, "GameTypeId": 1, "GameCount": 10,
                              "StartDateEst": "2026-10-18T13:00:00.0000000", "DraftGroupTag": "Featured"}],
             "Contests": [{"id": 777, "n": "NFL $5 Double Up", "a": 5, "m": 100, "dg": 154941}]}
    monkeypatch.setattr(run_pipeline.dk_salaries, "fetch_lobby", lambda: lobby)
    monkeypatch.setattr(run_pipeline.dk_salaries, "fetch_salary_csv", lambda slate: csv_text)
    run_pipeline.step_salaries(dt.date(2026, 10, 12), SimpleNamespace(salary_csv=None))
    c = pd.read_parquet(tmp_path / "processed" / "contests.parquet")
    assert c.to_dict("records") == [{"contest_id": "777", "contest_name": "NFL $5 Double Up", "entry_fee": 5.0,
                                     "max_entries": 100}]


def test_tuesday_publishes_after_stats():
    steps = run_pipeline.STAGES["tuesday"]
    assert "publish" in steps and steps.index("publish") > steps.index("stats")


def _boom(*a, **k):
    raise RuntimeError("disk full")


def test_salaries_step_warns_when_saving_contests_fails(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    from pathlib import Path as _P
    csv_text = (_P(__file__).parent / "fixtures" / "dk_salaries_sample.csv").read_bytes().decode("utf-8")
    lobby = {"DraftGroups": [{"DraftGroupId": 154941, "ContestTypeId": 21, "GameTypeId": 1, "GameCount": 10,
                              "StartDateEst": "2026-10-18T13:00:00.0000000", "DraftGroupTag": "Featured"}],
             "Contests": []}
    monkeypatch.setattr(run_pipeline.dk_salaries, "fetch_lobby", lambda: lobby)
    monkeypatch.setattr(run_pipeline.dk_salaries, "fetch_salary_csv", lambda slate: csv_text)
    monkeypatch.setattr(run_pipeline, "_save_contests", _boom)
    msg = run_pipeline.step_salaries(dt.date(2026, 10, 12), SimpleNamespace(salary_csv=None))
    assert "; WARNING: saving the contest list failed (RuntimeError)" in msg
    assert (tmp_path / "processed" / "pool_base.parquet").exists()


def test_save_contests_skips_empty(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    empty = pd.DataFrame(columns=["contest_id", "contest_name", "entry_fee", "max_entries"])
    run_pipeline._save_contests(empty)
    assert not (tmp_path / "processed" / "contests.parquet").exists()
    one = pd.DataFrame([{"contest_id": "1", "contest_name": "x", "entry_fee": 5.0, "max_entries": 10}])
    run_pipeline._save_contests(one)
    run_pipeline._save_contests(empty)
    run_pipeline._save_contests(one.assign(entry_fee=6.0))
    assert pd.read_parquet(tmp_path / "processed" / "contests.parquet").to_dict("records") == \
        [{"contest_id": "1", "contest_name": "x", "entry_fee": 6.0, "max_entries": 10}]


def _fake_build(tmp_path, monkeypatch, lineups):
    _paths(tmp_path, monkeypatch)
    P = tmp_path / "processed"
    pool = make_pool()
    pool["median"], pool["floor"], pool["ceiling"], pool["own_pct"] = 10.0, 5.0, 20.0, 8.0
    pool.to_parquet(P / "pool_base.parquet", index=False)
    for f in ("player_weeks", "team_weeks", "vegas_games"):
        pd.DataFrame({"x": [1]}).to_parquet(P / f"{f}.parquet", index=False)
    (P / "team_model.json").write_text("{}")
    (P / "slate.json").write_text(json.dumps({"draft_group_id": 154941}))
    res = {"pool": pool, "lineups": lineups, "match_rate": 1.0, "unmatched": []}
    monkeypatch.setattr(run_pipeline.build, "build_slate", lambda *a, **k: res)
    published = []
    monkeypatch.setattr(run_pipeline, "write_published", lambda r, out, meta: published.append(meta))
    return published


def _lineup_rows(ids, key="h2h", rank=0):
    return pd.DataFrame({"contest_key": [key] * len(ids), "rank": [rank] * len(ids), "dk_id": ids})


@pytest.mark.parametrize("target,attr,what", [
    (run_pipeline.player_history, "upsert_slate", "saving player history"),
    (run_pipeline, "_archive_lineups", "archiving lineups")])
def test_build_step_warns_when_history_bookkeeping_fails(tmp_path, monkeypatch, target, attr, what):
    published = _fake_build(tmp_path, monkeypatch, _lineup_rows(list(range(1001, 1010))))
    monkeypatch.setattr(target, attr, _boom)
    msg = run_pipeline.step_build(dt.date(2026, 10, 15), SimpleNamespace())
    assert f"; WARNING: {what} failed (RuntimeError)" in msg and published


def test_build_archives_every_build_so_earlier_lineups_still_match(tmp_path, monkeypatch):
    from nfldfs import entries
    first, second = list(range(1001, 1010)), list(range(1002, 1011))
    times = iter(["2026-10-15T08:00:00", "2026-10-18T09:00:00", "2026-10-18T11:45:00"])
    _fake_build(tmp_path, monkeypatch, _lineup_rows(first))
    monkeypatch.setattr(run_pipeline, "_now", lambda: next(times))
    run_pipeline.step_build(dt.date(2026, 10, 15), SimpleNamespace())
    res2 = {"pool": pd.read_parquet(tmp_path / "processed" / "pool_base.parquet"), "lineups": _lineup_rows(second),
            "match_rate": 1.0, "unmatched": []}
    monkeypatch.setattr(run_pipeline.build, "build_slate", lambda *a, **k: res2)
    run_pipeline.step_build(dt.date(2026, 10, 18), SimpleNamespace())
    run_pipeline.step_build(dt.date(2026, 10, 18), SimpleNamespace())           # identical rebuild adds nothing
    lus = pd.read_parquet(tmp_path / "processed" / "slate_lineups" / "2026-10-18_154941.parquet")
    assert "built_at" in lus.columns and len(lus) == 18
    assert entries.lineup_source(first, lus, prefer="h2h") == "Recommended Head-to-Head"
    assert entries.lineup_source(second, lus, prefer="h2h") == "Recommended Head-to-Head"


def test_stats_step_warns_when_actuals_fill_fails(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    pw = pd.DataFrame({"season": [2026], "week": [6]})
    monkeypatch.setattr(run_pipeline.nfl_stats, "load_raw", lambda seasons: (pw, pd.DataFrame({"x": [1]})))
    monkeypatch.setattr(run_pipeline.nfl_stats, "normalize_player_stats", lambda raw: pw)
    monkeypatch.setattr(run_pipeline.nfl_stats, "team_week_totals", lambda p: pw)
    monkeypatch.setattr(run_pipeline.nfl_stats, "normalize_schedules", lambda s: pw)
    monkeypatch.setattr(run_pipeline.team_env, "build_training_frame", lambda tw, s: None)
    monkeypatch.setattr(run_pipeline.team_env, "fit_team_model", lambda f: {"n_games": 1})
    monkeypatch.setattr(run_pipeline.player_history, "week_dates", lambda s: pw)
    monkeypatch.setattr(run_pipeline, "fill_nflverse_actuals", _boom)
    msg = run_pipeline.step_stats(dt.date(2026, 10, 13), SimpleNamespace())
    assert msg.startswith("1 player-weeks") and "; WARNING: filling actual points failed (RuntimeError)" in msg
    assert (tmp_path / "processed" / "team_model.json").exists()


def test_results_entries_failure_still_imports_file(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    _snapshot_file(tmp_path)
    monkeypatch.setattr(config, "dk_username", lambda: "natergater24")
    def bad(text, user):
        raise ValueError("odd columns")
    monkeypatch.setattr(run_pipeline.entries, "read_my_entries", bad)
    z = _standings_zip_with_me(tmp_path / "Downloads" / "contest-standings-555.zip")
    _monday(z)
    msg = run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert "imported 1 file(s)" in msg and "entries not read (ValueError)" in msg
    assert not z.exists() and (tmp_path / "raw" / "standings" / z.name).exists()
    assert "odd columns" not in msg


def test_results_set_actuals_failure_is_a_warning(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    _snapshot_file(tmp_path)
    monkeypatch.setattr(config, "dk_username", lambda: None)
    monkeypatch.setattr(run_pipeline.player_history, "set_actuals", _boom)
    z = _standings_zip(tmp_path / "Downloads" / "contest-standings-1.zip")
    _monday(z)
    msg = run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert "imported 1 file(s)" in msg and "WARNING: actual points not saved to player history (RuntimeError)" in msg
    assert (tmp_path / "raw" / "standings" / z.name).exists()
