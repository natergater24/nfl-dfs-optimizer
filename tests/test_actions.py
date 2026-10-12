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
