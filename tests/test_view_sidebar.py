from types import SimpleNamespace

from nfldfs_app import actions, view_sidebar


def test_results_message():
    assert view_sidebar.results_message({}) is None
    s = {"finished": "2026-10-19T09:01:00", "steps": [{"name": "results", "ok": True,
                                                      "message": "imported 1 file(s) for the 2026-10-18 slate"}]}
    assert view_sidebar.results_message(s).startswith("✅ imported 1 file(s)")
    bad = {"steps": [{"name": "results", "ok": False, "message": "ValueError: not a standings file"}]}
    assert view_sidebar.results_message(bad).startswith("⚠")
    skip = {"steps": [{"name": "results", "ok": True, "message": "skipped: no new contest-standings file"}]}
    assert "✅" not in view_sidebar.results_message(skip)


def test_save_upload(tmp_path):
    up = SimpleNamespace(name="../../contest-standings-1.zip", getvalue=lambda: b"PK")
    p = actions.save_upload(up, tmp_path / "inbox")
    assert p == tmp_path / "inbox" / "contest-standings-1.zip" and p.read_bytes() == b"PK"


def test_sidebar_actions_disabled_when_hosted(make_app, published_dir):
    at = make_app(published_dir, hosted="1")
    assert at.sidebar.button(key="check_results").disabled


def test_check_results_runs_stage_locally(make_app, published_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(actions, "run_stage", lambda *a: calls.append(a) or (True, "imported 1 file(s)"))
    at = make_app(published_dir, hosted="0")
    at.sidebar.button(key="check_results").click().run()
    assert calls == [("results",)] and not at.exception
    assert any("Done — results finished" in s.value for s in at.success)


def test_failed_local_action_shows_error_and_log_tail(make_app, published_dir, monkeypatch):
    monkeypatch.setattr(actions, "run_stage", lambda *a: (False, "Traceback (most recent call last)\nboom"))
    at = make_app(published_dir, hosted="0")
    at.sidebar.button(key="check_results").click().run()
    assert any(e.value == "results failed" for e in at.error)
    assert any("boom" in c.value for c in at.code)
