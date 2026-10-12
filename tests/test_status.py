import json

import numpy as np
import pandas as pd
import pytest

from nfldfs.status import (RunStatus, atomic_save_npy, atomic_write_parquet,
                           atomic_write_text)


def test_atomic_writes_leave_no_tmp_files(tmp_path):
    atomic_write_text(tmp_path / "a" / "x.json", '{"k": 1}')
    atomic_write_parquet(pd.DataFrame({"a": [1, 2]}), tmp_path / "a" / "x.parquet")
    atomic_save_npy(np.arange(3), tmp_path / "a" / "x.npy")
    names = sorted(p.name for p in (tmp_path / "a").iterdir())
    assert names == ["x.json", "x.npy", "x.parquet"]
    assert np.load(tmp_path / "a" / "x.npy").tolist() == [0, 1, 2]


def test_run_status_records_success_failure_and_reraises(tmp_path):
    path = tmp_path / "run_status.json"
    rs = RunStatus(path, "thursday")
    with rs.step("salaries") as rec:
        rec["message"] = "fetched 513 players"
    with pytest.raises(ValueError):
        with rs.step("vegas"):
            raise ValueError("quota exhausted")
    rs.finish(False)
    data = json.loads(path.read_text())
    assert data["stage"] == "thursday" and data["ok"] is False
    assert [s["name"] for s in data["steps"]] == ["salaries", "vegas"]
    assert data["steps"][0]["ok"] is True and data["steps"][0]["message"] == "fetched 513 players"
    assert data["steps"][1]["ok"] is False and "quota exhausted" in data["steps"][1]["message"]
