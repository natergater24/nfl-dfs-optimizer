import json
from pathlib import Path

import numpy as np
import pandas as pd

from nbadfs import build as B
from nbadfs import vegas
from nbadfs.config import NBA_CONTEST_TYPES
from nbadfs.simulate import simulate
from nbadfs.stats import player_rates

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _inputs():
    text = (FIX / "nba_salaries_sample.csv").read_text()
    lines = vegas.team_lines(json.loads((FIX / "nba_odds_sample.json").read_text()), pd.Timestamp("2026-10-23").date())
    s = pd.read_parquet(FIX / "nba_espn_season_sample.parquet")
    return text, lines, player_rates(s[s.season == 2026]), player_rates(s[s.season == 2027])


def test_build_slate_end_to_end(tmp_path):
    res = B.build_slate(*_inputs(), n_sims=400, seed=7, field_size=100, n_candidates=3)
    assert set(res["lineups"].contest_key) == set(NBA_CONTEST_TYPES) and len(NBA_CONTEST_TYPES) == 9
    assert {"n_sims", "seed", "stats_match_rate"} <= set(res["meta"])
    assert res["meta"]["n_sims"] == 400 and res["meta"]["seed"] == 7 and 0 <= res["meta"]["stats_match_rate"] <= 1
    B.write_published(res, tmp_path / "123")
    files = sorted(p.name for p in (tmp_path / "123").iterdir())
    assert files == sorted(B.PUBLISHED_FILES)
    assert not list((tmp_path / "123").glob("*sims*"))
    assert np.load(tmp_path / "123" / "field.npy").dtype == np.int32


def test_written_pool_resimulates_to_the_builds_sims(tmp_path):
    res = B.build_slate(*_inputs(), n_sims=400, seed=7, field_size=100, n_candidates=3)
    B.write_published(res, tmp_path)
    pool = pd.read_parquet(tmp_path / "pool.parquet")
    meta = json.loads((tmp_path / "build_meta.json").read_text())
    assert np.array_equal(simulate(pool, meta["n_sims"], meta["seed"]), res["sims"])
    field = np.load(tmp_path / "field.npy")
    assert field.max() < len(pool)
