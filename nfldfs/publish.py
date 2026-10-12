"""Commit and push published files so Streamlit Cloud redeploys. Never raises; never blocks local use."""
from __future__ import annotations

import subprocess
from pathlib import Path

PUSH_TIMEOUT = 90


def _git(repo: Path, *args: str, run=subprocess.run, timeout: int = 60):
    return run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)


def publish(repo, paths: list[str], message: str, run=subprocess.run) -> str:
    repo = Path(repo)
    if not (repo / ".git").exists():
        return "skipped: not a git repository"
    paths = [p for p in paths if (repo / p).exists()]
    if not paths:
        return "skipped: nothing to publish yet"
    try:
        add = _git(repo, "add", "--", *paths, run=run)
        if add.returncode != 0:
            return f"WARNING: git add failed — {add.stderr.strip()[:200]}"
        if _git(repo, "diff", "--cached", "--quiet", "--", *paths, run=run).returncode == 0:
            return "skipped: nothing new to publish"
        commit = _git(repo, "commit", "-m", message, "--", *paths, run=run)
        if commit.returncode != 0:
            return f"WARNING: git commit failed — {commit.stderr.strip()[:200]}"
        if not _git(repo, "remote", run=run).stdout.strip():
            return "committed locally (no GitHub remote yet)"
        push = _git(repo, "push", run=run, timeout=PUSH_TIMEOUT)
        if push.returncode != 0:
            return (f"WARNING: push to GitHub failed — {push.stderr.strip()[:200]} "
                    f"(the local app still works)")
        return "published to GitHub"
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"WARNING: publishing failed — {type(e).__name__}"
