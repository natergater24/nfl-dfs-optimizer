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
