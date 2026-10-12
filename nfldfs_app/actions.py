"""Local-only actions: run pipeline stages from the app and save uploaded files."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from nfldfs.config import ROOT

STAGE_TIMEOUT = 900


def run_stage(stage: str, *extra: str, run=subprocess.run) -> tuple[bool, str]:
    r = run([sys.executable, str(ROOT / "run_pipeline.py"), "--stage", stage, *extra], cwd=str(ROOT),
            capture_output=True, text=True, timeout=STAGE_TIMEOUT)
    lines = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    return r.returncode == 0, "\n".join(lines[-15:])


def save_upload(uploaded, folder: Path) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / Path(uploaded.name).name
    path.write_bytes(uploaded.getvalue())
    return path
