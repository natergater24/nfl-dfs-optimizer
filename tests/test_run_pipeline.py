import json

import run_pipeline
from nfldfs import config


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
    for f in ("team_weeks.parquet", "team_model.json"):
        (tmp_path / f).write_text("x")
    ts = dt.datetime.combine(mtime, dt.time(12, 0)).timestamp()
    for f in ("player_weeks.parquet", "team_weeks.parquet", "team_model.json"):
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
