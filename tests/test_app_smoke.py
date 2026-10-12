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
    assert any("failed at **vegas**" in e.value for e in at.error)


def test_local_mode_has_refresh_and_no_hosted_banner(make_app, published_dir):
    at = make_app(published_dir, hosted="0")
    assert not at.exception
    assert any(b.key == "refresh" for b in at.button)
    assert not any("hosted copy" in i.value for i in at.info)
