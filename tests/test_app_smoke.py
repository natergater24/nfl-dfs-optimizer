import json
import shutil

from nfldfs.config import CONTEST_TYPES


def test_app_renders_header(make_app, published_dir):
    at = make_app(published_dir)
    assert not at.exception
    assert at.title[0].value == "NFL DFS Lineups"
    assert at.selectbox(key="contest_label").options == [c["label"] for c in CONTEST_TYPES.values()]
    assert any("hosted copy" in i.value for i in at.info)            # hosted banner


def test_app_without_published_files(make_app, tmp_path):
    at = make_app(tmp_path)
    assert not at.exception
    assert "No lineups built yet" in at.warning[0].value


def test_failed_run_shows_banner(make_app, published_dir, tmp_path):
    pub = tmp_path / "pub"
    shutil.copytree(published_dir, pub)
    (pub / "run_status.json").write_text(json.dumps({"stage": "sunday", "ok": False, "steps": [
        {"name": "vegas", "ok": False, "message": "RuntimeError: The Odds API request failed (HTTP 429)"}]}))
    at = make_app(pub)
    assert any("failed at **Vegas lines**" in e.value for e in at.error)


def test_local_mode_has_refresh_and_no_hosted_banner(make_app, published_dir):
    at = make_app(published_dir, hosted="0")
    assert not at.exception
    assert any(b.key == "refresh" for b in at.button)
    assert not any("hosted copy" in i.value for i in at.info)


def _with_status(published_dir, tmp_path, status):
    pub = tmp_path / "pub"
    shutil.copytree(published_dir, pub)
    (pub / "run_status.json").write_text(json.dumps(status))
    return pub


def test_step_warning_is_shown(make_app, published_dir, tmp_path):
    pub = _with_status(published_dir, tmp_path, {"stage": "sunday", "ok": True, "steps": [
        {"name": "vegas", "ok": True,
         "message": "WARNING: The Odds API request failed (HTTP 429) Reusing lines fetched 30h ago."}]})
    at = make_app(pub)
    assert not at.exception
    assert any("Vegas lines" in w.value and "30h ago" in w.value for w in at.warning)


def test_publish_warning_shown_locally_only(make_app, published_dir, tmp_path):
    pub = _with_status(published_dir, tmp_path, {"stage": "sunday", "ok": True, "steps": [],
                                                 "publish": "WARNING: publishing failed — CalledProcessError"})
    at = make_app(pub, hosted="0")
    assert any("phone copy may be out of date" in w.value for w in at.warning)
    at = make_app(pub, hosted="1")
    assert not any("phone copy" in w.value for w in at.warning)
