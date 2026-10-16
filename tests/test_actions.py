import subprocess
from types import SimpleNamespace

from nfldfs_app import actions


def _fake(rc=0, out="", err=""):
    return lambda *a, **k: SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def _raiser(exc):
    def run(*a, **k):
        raise exc
    return run


def test_run_stage_success_keeps_last_15_lines():
    ok, tail = actions.run_stage("refresh", run=_fake(0, "\n".join(f"l{i}" for i in range(40))))
    assert ok and len(tail.splitlines()) == 15 and tail.splitlines()[-1] == "l39"


def test_run_stage_nonzero_exit():
    ok, tail = actions.run_stage("refresh", run=_fake(1, "a\n", "boom\n"))
    assert not ok and "boom" in tail


def test_run_stage_timeout_and_oserror():
    ok, msg = actions.run_stage("refresh", run=_raiser(subprocess.TimeoutExpired(["x"], 900)))
    assert not ok and "15 minutes" in msg
    ok, msg = actions.run_stage("refresh", run=_raiser(OSError("nope")))
    assert not ok and "OSError" in msg and "nope" not in msg


def test_save_upload_writes_and_strips_dirs(tmp_path):
    up = SimpleNamespace(name="../../evil/standings.csv", getvalue=lambda: b"abc")
    path = actions.save_upload(up, tmp_path / "sub")
    assert path == tmp_path / "sub" / "standings.csv" and path.read_bytes() == b"abc"


def test_stage_flash_headline_comes_from_outcome_not_stdout():
    assert actions.stage_flash("refresh", (True, "INFO lots of log lines")) == (True, "Done — refresh finished", "")
    assert actions.stage_flash("results", (False, "Traceback\nboom")) == (False, "results failed", "Traceback\nboom")


def test_record_my_build_dedupes(tmp_path):
    import pandas as pd
    path = tmp_path / "my_builds.parquet"
    actions.record_my_build([3, 1, 2], "2026-10-18", path=path)
    actions.record_my_build([1, 2, 3], "2026-10-18", path=path)
    actions.record_my_build([1, 2, 4], "2026-10-18", path=path)
    b = pd.read_parquet(path)
    assert len(b) == 2 and set(b["players"]) == {"1,2,3", "1,2,4"}


def test_save_entry_edit_and_add_entry(tmp_path, monkeypatch):
    from nfldfs import config, entries
    monkeypatch.setattr(config, "HISTORY", tmp_path / "history")
    monkeypatch.setattr(actions, "_publish", lambda message: "skipped: test")
    ok, msg = actions.add_entry(slate_date="2026-10-18", contest_name="NFL $5 Double Up", contest_type="double_up",
                                entry_fee=5.0, winnings=10.0)
    assert ok and "Saved" in msg
    e = entries.load_entries(tmp_path / "history" / "entries.parquet")
    ok, msg = actions.save_entry_edit(e.entry_id.iloc[0], winnings=0.0)
    assert ok and entries.load_entries(tmp_path / "history" / "entries.parquet").winnings.iloc[0] == 0.0
    ok, msg = actions.save_entry_edit("nope", winnings=1.0)
    assert not ok and "Couldn't save" in msg


def test_record_my_build_never_raises(tmp_path):
    path = tmp_path / "my_builds.parquet"
    path.write_bytes(b"not a parquet file")
    actions.record_my_build([1, 2, 3], "2026-10-18", path=path)       # bookkeeping failure must not break download
    assert path.read_bytes() == b"not a parquet file"
