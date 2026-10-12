"""Atomic file writes and per-step run status (read by the app's failure banner)."""
from __future__ import annotations

import datetime as dt
import json
import os
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd


def _tmp(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.with_name(path.name + ".tmp")


def atomic_write_bytes(path, data: bytes) -> None:
    path = Path(path)
    tmp = _tmp(path)
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_write_text(path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_parquet(df: pd.DataFrame, path) -> None:
    path = Path(path)
    tmp = _tmp(path)
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def atomic_save_npy(arr: np.ndarray, path) -> None:
    path = Path(path)
    tmp = _tmp(path)
    with open(tmp, "wb") as f:
        np.save(f, arr)
    os.replace(tmp, path)


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


class RunStatus:
    """Writes {stage, started, finished, ok, steps[...]} after every change."""

    def __init__(self, path, stage: str):
        self.path = Path(path)
        self.data = {"stage": stage, "started": _now(), "finished": None, "ok": None, "steps": []}
        self._write()

    @contextmanager
    def step(self, name: str):
        rec = {"name": name, "started": _now(), "finished": None, "ok": None, "message": ""}
        self.data["steps"].append(rec)
        self._write()
        try:
            yield rec
        except Exception as e:
            rec.update(ok=False, finished=_now(), message=f"{type(e).__name__}: {e}")
            self._write()
            raise
        rec.update(ok=True, finished=_now())
        self._write()

    def finish(self, ok: bool) -> None:
        self.data.update(ok=ok, finished=_now())
        self._write()

    def _write(self) -> None:
        atomic_write_text(self.path, json.dumps(self.data, indent=2, default=str))
