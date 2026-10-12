import subprocess

import pytest

from nfldfs.publish import publish


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com"); _git(r, "config", "user.name", "T")
    (r / "README.md").write_text("x"); _git(r, "add", "."); _git(r, "commit", "-qm", "init")
    (r / "data" / "published").mkdir(parents=True)
    return r


def test_publish_without_remote_commits_only_given_paths(repo):
    (repo / "data/published/a.json").write_text("{}")
    (repo / "other.txt").write_text("not mine"); _git(repo, "add", "other.txt")
    assert publish(repo, ["data/published", "data/history"], "Slate update") == \
        "committed locally (no GitHub remote yet)"
    files = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert files == ["data/published/a.json"]                      # other staged file not swept in
    assert publish(repo, ["data/published"], "again") == "skipped: nothing new to publish"


def test_publish_pushes_to_remote(repo, tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    _git(repo, "remote", "add", "origin", str(bare)); _git(repo, "push", "-q", "-u", "origin", "main")
    (repo / "data/published/b.json").write_text("{}")
    assert publish(repo, ["data/published"], "Slate update") == "published to GitHub"


def test_publish_push_failure_is_a_warning(repo):
    _git(repo, "remote", "add", "origin", "/nonexistent/remote.git")
    (repo / "data/published/c.json").write_text("{}")
    msg = publish(repo, ["data/published"], "Slate update")
    assert msg.startswith("WARNING: push to GitHub failed")


def test_publish_not_a_repo(tmp_path):
    assert publish(tmp_path, ["data/published"], "x") == "skipped: not a git repository"


def _fake_run(push_stderr="", raises=None):
    def run(cmd, **kw):
        if raises:
            raise raises
        sub = cmd[3]
        rc = {"diff": 1, "push": 1 if push_stderr else 0}.get(sub, 0)
        out = "origin" if sub == "remote" else ""
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=push_stderr if sub == "push" else "")
    return run


def test_publish_never_raises(repo):
    (repo / "data/published/d.json").write_text("{}")
    msg = publish(repo, ["data/published"], "x", run=_fake_run(raises=ValueError("boom")))
    assert msg.startswith("WARNING: publishing failed")


def test_publish_redacts_credentials(repo):
    (repo / "data/published/e.json").write_text("{}")
    msg = publish(repo, ["data/published"], "x",
                  run=_fake_run(push_stderr="fatal: https://user:tok@github.com/x.git denied"))
    assert "://***@" in msg and "tok" not in msg
