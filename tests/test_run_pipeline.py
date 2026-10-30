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


class _Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeInjurySession:
    """Sleeper + ESPN stand-in. sleeper: {name: (team, espn_id)}; news: {espn_id: text}."""
    def __init__(self, sleeper=None, news=None, fail=False):
        self.sleeper, self.news, self.fail, self.urls = sleeper or {}, news or {}, fail, []

    def get(self, url, timeout=None):
        self.urls.append(url)
        if self.fail:
            raise ConnectionError("down")
        if "sleeper" in url:
            return _Resp({str(i): {"full_name": n, "team": t, "espn_id": e}
                          for i, (n, (t, e)) in enumerate(self.sleeper.items())})
        eid = url.split("/athletes/")[1].split("/")[0]
        if eid not in self.news:
            return _Resp({}, 404)
        published = dt.datetime.now(dt.timezone.utc).isoformat()
        return _Resp({"rotowire": {"headline": self.news[eid], "story": "", "published": published}})


@pytest.fixture(autouse=True)
def _no_network_injury_news(monkeypatch):
    monkeypatch.setattr(run_pipeline, "_injury_session", lambda: FakeInjurySession())
    monkeypatch.setattr(run_pipeline, "_news_sleep", lambda s: None)


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


# ---- entry-history import -------------------------------------------------------------------------------------
EH_HEADER = ('"Sport","Game_Type","Entry_Key","Entry","Contest_Key","Contest_Date_EST","Place","Points",'
             '"Winnings_Non_Ticket","Winnings_Ticket","Contest_Entries","Entry_Fee","Prize_Pool","Places_Paid"\n')
EH_ROW = ('"NFL","Classic",5295086450,"NFL GIANT $25 Double Up [Single Entry]",196672055,"2026-10-18 13:00:00",'
          '430,141.98,"$50.00","$0.00",2758,"$25.00","$60,000.00",1200\n')
EH_NBA = '"NBA","Classic",1,"x",2,"2026-10-18 19:00:00",5,1.0,"$0.00","$0.00",100,"$5.00","$1.00",20\n'
EH_NAME = "draftkings-contest-entry-history.csv"


def _eh(path, *rows):
    path.write_text(EH_HEADER + "".join(rows or (EH_ROW,)))
    return path


def test_step_results_imports_entry_history_and_files_it(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)                                  # no slate snapshot, no DK_USERNAME needed
    monkeypatch.setattr(config, "dk_username", lambda: None)
    f = _eh(tmp_path / "Downloads" / EH_NAME, EH_ROW, EH_NBA)
    msg = run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert "entry history" in msg and "1 new" in msg and "1 non-Classic" in msg
    e = pd.read_parquet(tmp_path / "history" / "entries.parquet")
    assert len(e) == 1 and e.iloc[0]["winnings"] == 50.0
    assert not f.exists()
    kept = list((tmp_path / "raw" / "entry_history").glob("entry-history-*.csv"))
    assert len(kept) == 1
    _eh(tmp_path / "Downloads" / EH_NAME)                          # same name downloaded again
    msg2 = run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert "1 entries updated" in msg2
    assert len(list((tmp_path / "raw" / "entry_history").glob("entry-history-*.csv"))) == 2


def test_entry_history_and_standings_pair_gives_players_and_money(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch); _snapshot_file(tmp_path)
    monkeypatch.setattr(config, "dk_username", lambda: "natergater24")
    z = _standings_zip_with_me(tmp_path / "Downloads" / "contest-standings-555.zip")
    row = EH_ROW.replace("5295086450", "2").replace("196672055", "555")
    h = _eh(tmp_path / "Downloads" / EH_NAME, row)
    _monday(z, h)
    msg = run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert "entry history" in msg and "imported 1 file" in msg
    e = pd.read_parquet(tmp_path / "history" / "entries.parquet")
    assert len(e) == 1 and e.iloc[0]["players"] != "" and e.iloc[0]["winnings"] == 50.0
    assert e.iloc[0]["entry_fee"] == 25.0 and e.iloc[0]["lineup_source"] != "No standings imported"


def test_new_results_waiting_with_only_entry_history(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    assert not run_pipeline._new_results_waiting()
    _eh(tmp_path / "Downloads" / "draftkings-contest-entry-history (1).csv")
    assert run_pipeline._new_results_waiting()


def test_step_results_nothing_waiting_message(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    msg = run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert msg == "skipped: no new contest-standings or entry-history file"


def test_results_file_routes_entry_history_by_content(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    f = _eh(tmp_path / "uploaded.csv")
    msg = run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=str(f)))
    assert "entry history" in msg and "1 new" in msg
    assert len(pd.read_parquet(tmp_path / "history" / "entries.parquet")) == 1
    assert not f.exists()


def test_broken_entry_history_is_set_aside_and_reported(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    bad = tmp_path / "Downloads" / EH_NAME
    bad.write_text('"Sport","Entry_Key","Winnings_Non_Ticket"\n"NFL",1,"$1.00"\n')
    with pytest.raises(RuntimeError, match="Game_Type"):
        run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert not bad.exists()
    assert len(list((tmp_path / "raw" / "entry_history" / "skipped").glob("*.csv"))) == 1
    assert not run_pipeline._new_results_waiting()


def test_entry_history_writes_no_username(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch); _snapshot_file(tmp_path)
    monkeypatch.setattr(config, "dk_username", lambda: "natergater24")
    z = _standings_zip_with_me(tmp_path / "Downloads" / "contest-standings-555.zip")
    h = _eh(tmp_path / "Downloads" / EH_NAME, EH_ROW.replace("5295086450", "2"))
    _monday(z, h)
    run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    for sub in ("history", "published"):
        for p in (tmp_path / sub).rglob("*"):
            if p.is_file():
                data = p.read_bytes().lower()
                assert b"natergater24" not in data, p


# ── NBA stage ──────────────────────────────────────────────────────────────────────────────────────────────
from pathlib import Path  # noqa: E402

import nbadfs.config as nba_config  # noqa: E402

FIXD = Path(__file__).resolve().parent / "fixtures"
NBA_DAY = "2026-10-23"


@pytest.fixture
def nba_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PUBLISHED", tmp_path / "published")
    monkeypatch.setattr(config, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(nba_config, "PUBLISHED_NBA", tmp_path / "published" / "nba")
    monkeypatch.setattr(nba_config, "PROCESSED_NBA", tmp_path / "processed" / "nba")
    monkeypatch.setattr(nba_config, "RAW_NBA", tmp_path / "raw" / "nba")
    monkeypatch.setattr(run_pipeline, "STEP_FUNCS", {**run_pipeline.STEP_FUNCS, "publish": lambda t, a: "skipped"})
    calls = {"odds": 0, "csv": 0}
    lobby = json.loads((FIXD / "nba_lobby_sample.json").read_text())
    monkeypatch.setattr(run_pipeline.nba_dk, "fetch_lobby", lambda: lobby)
    monkeypatch.setattr(run_pipeline.nba_dk, "fetch_salary_csv",
                        lambda dg: calls.__setitem__("csv", calls["csv"] + 1) or (FIXD / "nba_salaries_sample.csv").read_text())

    def odds(key):
        calls["odds"] += 1
        return json.loads((FIXD / "nba_odds_sample.json").read_text()), "480"
    monkeypatch.setattr(run_pipeline.nba_vegas, "fetch_odds", odds)
    monkeypatch.setattr(config, "odds_api_key", lambda: "k")
    monkeypatch.setattr(run_pipeline.nba_stats, "download_season", lambda y, d: None)
    sample = pd.read_parquet(FIXD / "nba_espn_season_sample.parquet")
    monkeypatch.setattr(run_pipeline, "_nba_rates", lambda y: run_pipeline.nba_stats.player_rates(sample[sample.season == y]))
    import nbadfs.build as nb
    real = nb.build_slate
    monkeypatch.setattr(nb, "build_slate", lambda *a, **k: real(*a, **{**k, "n_sims": 200, "field_size": 100, "n_candidates": 3}))
    return tmp_path, calls


def _one_slate(monkeypatch):
    lobby = json.loads((FIXD / "nba_lobby_sample.json").read_text())
    lobby["DraftGroups"] = [g for g in lobby["DraftGroups"] if g["DraftGroupId"] == 155547]
    monkeypatch.setattr(run_pipeline.nba_dk, "fetch_lobby", lambda: lobby)


def _status(tmp_path):
    return json.loads((tmp_path / "published" / "nba" / "run_status.json").read_text())


def test_nba_stage_noop_without_slates(nba_env, monkeypatch):
    tmp_path, calls = nba_env
    monkeypatch.setattr(run_pipeline.nba_dk, "fetch_lobby", lambda: {"DraftGroups": []})
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    assert calls == {"odds": 0, "csv": 0}
    assert json.loads((tmp_path / "published" / "nba" / "slates.json").read_text()) == []
    st = _status(tmp_path)
    assert st["ok"] is True and st["steps"][0]["message"] == "skipped: no NBA Classic slate today"
    assert all(s["message"].startswith("skipped") for s in st["steps"])


def test_nba_off_day_after_a_game_day_prunes_old_folder_and_empties_slates(nba_env, monkeypatch):
    tmp_path, calls = nba_env
    _one_slate(monkeypatch)
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    assert (tmp_path / "published" / "nba" / "155547" / "pool.parquet").exists()
    assert run_pipeline.main(["--stage", "nba", "--today", "2026-10-25"]) == 0   # no slates that day
    assert json.loads((tmp_path / "published" / "nba" / "slates.json").read_text()) == []
    assert not (tmp_path / "published" / "nba" / "155547").exists()              # stale folder pruned


def test_nba_status_file_separate(nba_env):
    tmp_path, _ = nba_env
    nfl = tmp_path / "published" / "run_status.json"
    nfl.parent.mkdir(parents=True)
    nfl.write_text('{"keep": "me"}')
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    assert nfl.read_text() == '{"keep": "me"}'
    assert _status(tmp_path)["stage"] == "nba"
    slates = json.loads((tmp_path / "published" / "nba" / "slates.json").read_text())
    assert [s["draft_group_id"] for s in slates] == [155547, 155553, 155557] and all(s["published"] for s in slates)
    assert (tmp_path / "published" / "nba" / "155553" / "lineups.parquet").exists()
    assert (tmp_path / "raw" / "nba" / NBA_DAY / "salaries_155547.csv").exists()


def test_one_slate_failure_does_not_stop_others(nba_env, monkeypatch):
    tmp_path, _ = nba_env
    import nbadfs.build as nb
    real = nb.build_slate
    n = {"i": 0}

    def flaky(*a, **k):
        n["i"] += 1
        if n["i"] == 2:
            raise ValueError("bad slate")
        return real(*a, **k)
    monkeypatch.setattr(nb, "build_slate", flaky)
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    msg = [s for s in _status(tmp_path)["steps"] if s["name"] == "nba_build"][0]["message"]
    slates = json.loads((tmp_path / "published" / "nba" / "slates.json").read_text())
    assert [s["published"] for s in slates] == [True, False, True]
    assert f"; WARNING: {slates[1]['name']} not built (ValueError)" in msg
    assert (tmp_path / "published" / "nba" / "155557" / "pool.parquet").exists()


def test_nba_odds_skip_when_fresh(nba_env, monkeypatch):
    tmp_path, calls = nba_env
    _one_slate(monkeypatch)
    monkeypatch.setitem(run_pipeline.STEP_FUNCS, "nba_build", lambda t, a: "stub")
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    assert calls["odds"] == 1
    assert "480" in [s for s in _status(tmp_path)["steps"] if s["name"] == "nba_vegas_if_stale"][0]["message"]
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    assert calls["odds"] == 1
    odds = tmp_path / "processed" / "nba" / "odds.json"
    old = odds.stat().st_mtime - 61 * 60
    os.utime(odds, (old, old))
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    assert calls["odds"] == 2


def test_nba_season_years():
    assert run_pipeline.nba_season_years(dt.date(2026, 10, 23)) == (2027, 2026)
    assert run_pipeline.nba_season_years(dt.date(2027, 3, 1)) == (2027, 2026)
    assert run_pipeline.nba_season_years(dt.date(2027, 7, 1)) == (2028, 2027)


def test_salary_download_failure_skips_only_that_slate(nba_env, monkeypatch):
    tmp_path, calls = nba_env
    real = run_pipeline.nba_dk.fetch_salary_csv

    def flaky(dg):
        if dg == 155553:
            raise RuntimeError("blocked")
        return real(dg)
    monkeypatch.setattr(run_pipeline.nba_dk, "fetch_salary_csv", flaky)
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    steps = {s["name"]: s["message"] for s in _status(tmp_path)["steps"]}
    assert "salaries not downloaded (RuntimeError)" in steps["nba_salaries"]
    slates = json.loads((tmp_path / "published" / "nba" / "slates.json").read_text())
    assert [s["published"] for s in slates] == [True, False, True]
    assert steps["nba_build"].startswith("2 of 3")


def test_all_salary_downloads_failing_fails_the_step(nba_env, monkeypatch):
    tmp_path, _ = nba_env

    def boom(dg):
        raise RuntimeError("blocked")
    monkeypatch.setattr(run_pipeline.nba_dk, "fetch_salary_csv", boom)
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 1
    assert _status(tmp_path)["ok"] is False


def test_odds_failure_does_not_stop_the_stage(nba_env, monkeypatch):
    tmp_path, _ = nba_env
    _one_slate(monkeypatch)

    def boom(key):
        raise RuntimeError("quota")
    monkeypatch.setattr(run_pipeline.nba_vegas, "fetch_odds", boom)
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    steps = {s["name"]: s["message"] for s in _status(tmp_path)["steps"]}
    assert "WARNING: NBA lines not refreshed (RuntimeError)" in steps["nba_vegas_if_stale"]
    assert steps["nba_build"].startswith("1 of 1")


def test_nba_prunes_stale_slate_folders_only(nba_env, monkeypatch):
    tmp_path, _ = nba_env
    nba = tmp_path / "published" / "nba"
    (nba / "99999").mkdir(parents=True)
    (nba / "99999" / "pool.parquet").write_text("x")
    (nba / "notes.txt").write_text("keep")
    (nba / "archive").mkdir()
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    assert not (nba / "99999").exists()
    assert (nba / "155547" / "pool.parquet").exists() and (nba / "notes.txt").exists() and (nba / "archive").exists()


def test_nba_publish_skipped_on_repeat_no_slate_day_only(nba_env, monkeypatch):
    tmp_path, _ = nba_env
    published = []
    monkeypatch.setitem(run_pipeline.STEP_FUNCS, "publish", run_pipeline.step_publish)
    monkeypatch.setattr(run_pipeline.publish, "publish", lambda *a, **k: published.append(1) or "committed")
    empty = lambda: {"DraftGroups": []}                                          # noqa: E731
    real = run_pipeline.nba_dk.fetch_lobby
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0        # slates exist -> publish
    assert len(published) == 1
    monkeypatch.setattr(run_pipeline.nba_dk, "fetch_lobby", empty)
    assert run_pipeline.main(["--stage", "nba", "--today", "2026-10-25"]) == 0   # slates -> [] : tell the phone
    assert len(published) == 2
    assert run_pipeline.main(["--stage", "nba", "--today", "2026-10-26"]) == 0   # [] -> [] : nothing new
    assert len(published) == 2
    assert _status(tmp_path)["publish"] == "skipped: nothing new to publish"
    monkeypatch.setattr(run_pipeline.nba_dk, "fetch_lobby", real)
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0        # slates return -> publish
    assert len(published) == 3


def test_failed_rerun_keeps_todays_earlier_build_published(nba_env, monkeypatch):
    tmp_path, _ = nba_env
    _one_slate(monkeypatch)
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    nba = tmp_path / "published" / "nba"
    slates = lambda: json.loads((nba / "slates.json").read_text())               # noqa: E731
    import nbadfs.build as nb
    monkeypatch.setattr(nb, "build_slate", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0        # evening build fails
    assert slates()[0]["published"] is True                                      # afternoon build still served
    msg = [s for s in _status(tmp_path)["steps"] if s["name"] == "nba_build"][0]["message"]
    assert "WARNING" in msg and "not built" in msg
    assert (nba / "155547" / "pool.parquet").exists()
    # an older day's build does not count
    meta = nba / "155547" / "build_meta.json"
    meta.write_text(json.dumps({**json.loads(meta.read_text()), "slate_date": "2026-10-22"}))
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    assert slates()[0]["published"] is False


def test_partial_salary_failure_keeps_todays_earlier_build_published(nba_env, monkeypatch):
    tmp_path, _ = nba_env
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0        # all three slates built
    nba = tmp_path / "published" / "nba"
    text = (FIXD / "nba_salaries_sample.csv").read_text()

    def flaky(dg):
        if dg == 155547:
            raise OSError("down")
        return text
    monkeypatch.setattr(run_pipeline.nba_dk, "fetch_salary_csv", flaky)
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    slates = json.loads((nba / "slates.json").read_text())
    assert [s["published"] for s in slates] == [True, True, True]
    assert "WARNING: " in [s for s in _status(tmp_path)["steps"] if s["name"] == "nba_salaries"][0]["message"]


def _real_build_inputs(tmp_path, monkeypatch, statuses):
    from tests.conftest import SYNTH_MODEL, synthetic_inputs
    _paths(tmp_path, monkeypatch)
    for name, v in (("N_SIMS", 300), ("N_CANDIDATES", 3), ("FIELD_SIZE", 150)):
        monkeypatch.setattr(config, name, v)
    P = tmp_path / "processed"
    pool_base, pw, tw, games = synthetic_inputs()
    for name, st in statuses.items():
        pool_base.loc[pool_base["name"] == name, "status"] = st
    pool_base.to_parquet(P / "pool_base.parquet", index=False)
    pw.to_parquet(P / "player_weeks.parquet", index=False)
    tw.to_parquet(P / "team_weeks.parquet", index=False)
    games.to_parquet(P / "vegas_games.parquet", index=False)
    (P / "team_model.json").write_text(json.dumps(SYNTH_MODEL))
    (P / "slate.json").write_text(json.dumps({"draft_group_id": 154941}))
    return pool_base


def _rank0_favourite():
    """The player in the most rank-0 lineups of an untagged build (CCC WR1 out), to tag Q."""
    from nfldfs import build
    from tests.conftest import SYNTH_MODEL, synthetic_inputs
    pool_base, pw, tw, games = synthetic_inputs()
    pool_base.loc[pool_base["name"] == "CCC WR1", "playable"] = False
    res = build.build_slate(pool_base, pw, tw, SYNTH_MODEL, games, n_sims=300, seed=config.SEED,
                            n_candidates=3, field_size=150)
    rec = res["lineups"][res["lineups"]["rank"] == 0]
    return rec["name"].value_counts().index[0]


def test_nfl_build_publishes_injury_files(tmp_path, monkeypatch):
    fav = _rank0_favourite()
    assert fav != "CCC WR1"
    base = _real_build_inputs(tmp_path, monkeypatch, {"CCC WR1": "Q", fav: "Q", "AAA TE1": "P"})
    sleeper = {n: (t, f"E{d}") for n, t, d in zip(base["name"], base["team"], base["dk_id"])}
    news = {f"E{d}": "He practiced fully on Wednesday." for d in base["dk_id"]}
    cw = int(base.loc[base["name"] == "CCC WR1", "dk_id"].iloc[0])
    dw = int(base.loc[base["name"] == fav, "dk_id"].iloc[0])
    news[f"E{cw}"] = "Smith has been ruled out for Sunday's game."
    news[f"E{dw}"] = "Jones was limited at practice Wednesday."
    sess = FakeInjurySession(sleeper, news)
    monkeypatch.setattr(run_pipeline, "_injury_session", lambda: sess)
    msg = run_pipeline.step_build(dt.date(2026, 10, 15), SimpleNamespace())
    assert "WARNING" not in msg
    pub = tmp_path / "published"
    pool = pd.read_parquet(pub / "player_pool.parquet").set_index("dk_id")
    assert {"inj_tag", "inj_class", "body_part", "news_headline", "news_story", "news_published", "lean",
            "recommendable", "play_prob"} <= set(pool.columns)
    assert pool.loc[cw, "lean"] == "out" and not pool.loc[cw, "recommendable"]
    assert pool.loc[dw, "lean"] == "unclear" and pool.loc[dw, "play_prob"] == config.Q_PLAY_PROB
    lus = pd.read_parquet(pub / "lineups.parquet")
    assert cw not in set(lus.dk_id)
    # news for every recommended/alternate player, and for nobody else who is healthy
    suggested = set(lus.dk_id.astype(int))
    has_news = set(pool.index[pool.news_headline != ""])
    healthy_unsuggested = set(pool.index[(pool.inj_tag == "")]) - suggested
    assert suggested <= has_news and not (has_news & healthy_unsuggested)
    assert sum("sleeper" in u for u in sess.urls) == 1                     # one Sleeper call per run
    bk = pd.read_parquet(pub / "injury_backups.parquet")
    assert list(bk.columns) == ["contest_key", *run_pipeline.build.lineups.BACKUP_COLUMNS]
    rec = lus[lus["rank"] == 0]
    tagged = rec.merge(pool[["inj_class"]], left_on="dk_id", right_index=True)
    assert len(bk) > 0 and dw in set(rec.dk_id)                          # not vacuous
    assert len(bk) == int((tagged.inj_class != "healthy").sum())
    assert set(bk.contest_key) == set(tagged.loc[tagged.inj_class != "healthy", "contest_key"])
    assert set(bk.tagged_dk_id) == {dw}
    assert {int(i) for ids in bk.in_dk_ids for i in ids} <= set(pool.index[pool.inj_class == "healthy"])


def test_nfl_build_survives_news_failure(tmp_path, monkeypatch):
    _real_build_inputs(tmp_path, monkeypatch, {"CCC WR1": "Q", "AAA RB1": "OUT"})
    monkeypatch.setattr(run_pipeline, "_injury_session", lambda: FakeInjurySession(fail=True))
    msg = run_pipeline.step_build(dt.date(2026, 10, 15), SimpleNamespace())
    assert "contest types built" in msg and "; WARNING: injury news unavailable (ConnectionError)" in msg
    pub = tmp_path / "published"
    pool = pd.read_parquet(pub / "player_pool.parquet").set_index("name")
    assert pool.loc["CCC WR1", "inj_tag"] == "Q" and pool.loc["AAA RB1", "inj_tag"] == "OUT"
    assert (pool.news_headline == "").all()
    assert (pub / "injury_backups.parquet").exists() and (pub / "build_meta.json").exists()


def test_nfl_build_survives_injury_code_crash(tmp_path, monkeypatch):
    _real_build_inputs(tmp_path, monkeypatch, {"CCC WR1": "Q"})
    monkeypatch.setattr(run_pipeline.injuries, "add_injury_columns", _boom)
    monkeypatch.setattr(run_pipeline.injuries, "add_news", _boom)
    msg = run_pipeline.step_build(dt.date(2026, 10, 15), SimpleNamespace())
    assert "; WARNING: injury news unavailable (RuntimeError)" in msg
    pool = pd.read_parquet(tmp_path / "published" / "player_pool.parquet").set_index("name")
    # DraftKings tags still applied (classify fallback): discount + sitting match the backups
    assert pool.loc["CCC WR1", "inj_tag"] == "Q" and pool.loc["CCC WR1", "play_prob"] == config.Q_PLAY_PROB


# ── NBA injuries ─────────────────────────────────────────────────────────────────────────────────────────
def _nba_csv(statuses: dict) -> str:
    import io
    df = pd.read_csv(io.StringIO((FIXD / "nba_salaries_sample.csv").read_text()), keep_default_na=False, dtype=str)
    for name, st in statuses.items():
        df.loc[df["Name"] == name, "Status"] = st
    return df.to_csv(index=False)


def _nba_rank0_favourites(tmp_path, monkeypatch):
    """The two players in the most rank-0 lineups of an untagged single-slate run."""
    _one_slate(monkeypatch)
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    pub = tmp_path / "published" / "nba" / "155547"
    lus, pool = pd.read_parquet(pub / "lineups.parquet"), pd.read_parquet(pub / "pool.parquet")
    names = pool.set_index("dk_id")["name"]
    return [names[int(d)] for d in lus[lus["rank"] == 0].dk_id.value_counts().index[:2]]


def test_nba_build_publishes_injury_files(nba_env, monkeypatch):
    from nbadfs.build import sims_fingerprint
    from nbadfs.dk import parse_salaries
    from nbadfs.simulate import simulate
    tmp_path, _ = nba_env
    fav, second = _nba_rank0_favourites(tmp_path, monkeypatch)
    text = _nba_csv({fav: "Q", second: "GTD"})
    monkeypatch.setattr(run_pipeline.nba_dk, "fetch_salary_csv", lambda dg: text)
    lobby = json.loads((FIXD / "nba_lobby_sample.json").read_text())          # all three slates again
    monkeypatch.setattr(run_pipeline.nba_dk, "fetch_lobby", lambda: lobby)
    base = parse_salaries(text)
    sleeper = {n: (t, f"E{d}") for n, t, d in zip(base["name"], base["team"], base["dk_id"])}
    news = {f"E{d}": "He went through shootaround." for d in base["dk_id"]}
    fid = int(base.loc[base["name"] == fav, "dk_id"].iloc[0])
    sid = int(base.loc[base["name"] == second, "dk_id"].iloc[0])
    news[f"E{fid}"] = f"{fav} has been ruled out for Friday's game."
    news[f"E{sid}"] = f"{second} did not practice Thursday."
    sess = FakeInjurySession(sleeper, news)
    monkeypatch.setattr(run_pipeline, "_injury_session", lambda: sess)
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    msg = [s for s in _status(tmp_path)["steps"] if s["name"] == "nba_build"][0]["message"]
    assert msg.startswith("3 of 3 NBA slate(s) built") and "WARNING" not in msg
    assert sum("sleeper" in u for u in sess.urls) == 1                      # one Sleeper call per run
    espn = [u for u in sess.urls if "espn" in u]
    assert len(espn) == len(set(espn))                                     # news shared across slates
    for dg in (155547, 155553, 155557):
        pub = tmp_path / "published" / "nba" / str(dg)
        pool = pd.read_parquet(pub / "pool.parquet")
        meta = json.loads((pub / "build_meta.json").read_text())
        assert sims_fingerprint(simulate(pool, meta["n_sims"], meta["seed"])) == meta["sims_fingerprint"]
        pool = pool.set_index("dk_id")
        assert {"inj_tag", "inj_class", "body_part", "espn_id", "news_headline", "news_story", "news_published",
                "lean", "recommendable", "play_prob"} <= set(pool.columns)
        assert pool.at[fid, "lean"] == "out" and not pool.at[fid, "recommendable"]
        assert pool.at[sid, "lean"] == "unclear" and pool.at[sid, "play_prob"] == config.Q_PLAY_PROB
        lus = pd.read_parquet(pub / "lineups.parquet")
        swaps = pd.read_parquet(pub / "swaps.parquet")
        bk = pd.read_parquet(pub / "injury_backups.parquet")
        assert fid not in set(lus.dk_id) and fid not in set(swaps.in_id)
        assert fid not in {int(i) for ids in bk.in_dk_ids for i in ids}
        suggested = set(lus.dk_id.astype(int))
        has_news = set(pool.index[pool.news_headline != ""])
        assert suggested <= has_news and not (has_news - suggested - set(pool.index[pool.inj_tag != ""]))
        rec = lus[lus["rank"] == 0].merge(pool[["inj_class"]], left_on="dk_id", right_index=True)
        assert list(bk.columns) == ["contest_key", *run_pipeline.build.lineups.BACKUP_COLUMNS]
        assert len(bk) == int((rec.inj_class != "healthy").sum())
        assert {int(i) for ids in bk.in_dk_ids for i in ids} <= set(pool.index[pool.inj_class == "healthy"])
        if dg == 155547:
            assert sid in set(rec.dk_id) and len(bk) > 0                   # not vacuous


def test_nba_build_survives_news_failure(nba_env, monkeypatch):
    tmp_path, _ = nba_env
    monkeypatch.setattr(run_pipeline.nba_dk, "fetch_salary_csv", lambda dg: _nba_csv({"Mikal Bridges": "GTD"}))
    sess = FakeInjurySession(fail=True)
    monkeypatch.setattr(run_pipeline, "_injury_session", lambda: sess)
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    msg = [s for s in _status(tmp_path)["steps"] if s["name"] == "nba_build"][0]["message"]
    assert msg.startswith("3 of 3 NBA slate(s) built")
    assert msg.count("; WARNING: injury news unavailable (ConnectionError)") == 1
    assert sum("sleeper" in u for u in sess.urls) == 1
    pub = tmp_path / "published" / "nba" / "155547"
    pool = pd.read_parquet(pub / "pool.parquet").set_index("name")
    assert pool.at["Mikal Bridges", "inj_tag"] == "GTD" and pool.at["Kawhi Leonard", "inj_tag"] == "OUT"
    assert (pool.news_headline == "").all()
    assert (pub / "injury_backups.parquet").exists() and (pub / "build_meta.json").exists()


def test_nba_build_survives_injury_code_crash(nba_env, monkeypatch):
    tmp_path, _ = nba_env
    _one_slate(monkeypatch)
    monkeypatch.setattr(run_pipeline.injuries, "add_injury_columns", _boom)
    monkeypatch.setattr(run_pipeline.injuries, "add_news", _boom)
    monkeypatch.setattr(run_pipeline.injuries, "fetch_sleeper", _boom)
    assert run_pipeline.main(["--stage", "nba", "--today", NBA_DAY]) == 0
    msg = [s for s in _status(tmp_path)["steps"] if s["name"] == "nba_build"][0]["message"]
    assert msg.startswith("1 of 1 NBA slate(s) built") and "; WARNING: injury news unavailable (RuntimeError)" in msg
    pool = pd.read_parquet(tmp_path / "published" / "nba" / "155547" / "pool.parquet").set_index("name")
    assert pool.at["Mikal Bridges", "inj_tag"] == "Q" and pool.at["Mikal Bridges", "play_prob"] == config.Q_PLAY_PROB
