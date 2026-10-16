"""Local-only actions: run pipeline stages from the app and save uploaded files."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from nfldfs import config, entries, publish

STAGE_TIMEOUT = 900


def run_stage(stage: str, *extra: str, run=subprocess.run) -> tuple[bool, str]:
    try:
        r = run([sys.executable, str(config.ROOT / "run_pipeline.py"), "--stage", stage, *extra], cwd=str(config.ROOT),
                capture_output=True, text=True, timeout=STAGE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "The pipeline run took longer than 15 minutes and was stopped. Check logs/pipeline.log."
    except Exception as e:
        return False, f"Couldn't start the pipeline run ({type(e).__name__}). Check logs/pipeline.log."
    lines = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    return r.returncode == 0, "\n".join(lines[-15:])


def stage_flash(stage: str, result: tuple[bool, str]) -> tuple[bool, str, str]:
    """(ok, headline, detail) for the app's flash; warnings come from the reloaded status file, not stdout."""
    ok, tail = result
    return (True, f"Done — {stage} finished", "") if ok else (False, f"{stage} failed", tail)


def save_upload(uploaded, folder: Path) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / Path(uploaded.name).name
    path.write_bytes(uploaded.getvalue())
    return path


def record_my_build(ids, slate_date, path=None) -> None:
    """Remember a My Lineup download (Mac only) so a matching DraftKings entry is labeled 'My Lineup build'."""
    import datetime as dt

    import pandas as pd

    from nfldfs.status import atomic_write_parquet
    path = Path(path) if path else config.PROCESSED / "my_builds.parquet"
    players = ",".join(str(i) for i in sorted(int(i) for i in ids))
    cur = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["saved_at", "slate_date", "players"])
    if ((cur["slate_date"] == str(slate_date)) & (cur["players"] == players)).any():
        return
    row = pd.DataFrame([{"saved_at": dt.datetime.now().isoformat(timespec="seconds"),
                         "slate_date": str(slate_date), "players": players}])
    atomic_write_parquet(pd.concat([cur, row], ignore_index=True), path)


def _publish(message: str) -> str:
    return publish.publish(config.ROOT, ["data/history"], message)


def save_entry_edit(entry_id: str, **fields) -> tuple[bool, str]:
    try:
        entries.update_entry(config.HISTORY / "entries.parquet", entry_id, **fields)
    except Exception as e:
        return False, f"Couldn't save ({type(e).__name__}: {e})"
    return True, f"Saved. {_publish(f'Edit entry {entry_id}')}"


def add_entry(**fields) -> tuple[bool, str]:
    try:
        entries.add_manual_entry(config.HISTORY / "entries.parquet", **fields)
    except Exception as e:
        return False, f"Couldn't save ({type(e).__name__}: {e})"
    return True, f"Saved. {_publish('Add entry by hand')}"
