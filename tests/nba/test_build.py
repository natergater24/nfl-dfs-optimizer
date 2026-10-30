import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nbadfs import build as B
from nbadfs import vegas
from nbadfs.config import NBA_CONTEST_TYPES
from nbadfs.simulate import simulate
from nbadfs.stats import player_rates
from nfldfs.lineups import BACKUP_COLUMNS

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


def _set_status(text: str, statuses: dict) -> str:
    """Salary CSV with DraftKings Status replaced for the named players."""
    df = pd.read_csv(__import__("io").StringIO(text), keep_default_na=False, dtype=str)
    for name, st in statuses.items():
        df.loc[df["Name"] == name, "Status"] = st
    return df.to_csv(index=False)


def _plain_rank0_favourites(inputs):
    res = B.build_slate(*inputs, n_sims=300, seed=7, field_size=100, n_candidates=3)
    rec = res["lineups"][res["lineups"]["rank"] == 0]
    names = res["pool"].set_index("dk_id")["name"]
    return [names[int(d)] for d in rec["dk_id"].value_counts().index[:2]]


def test_resim_matches_with_play_prob(tmp_path):
    text, *rest = _inputs()
    fav, second = _plain_rank0_favourites((text, *rest))
    text = _set_status(text, {fav: "Q", second: "GTD"})
    base = B.parse_salaries(text)
    info = pd.DataFrame({"dk_id": base["dk_id"], "lean": ["out" if n == fav else "" for n in base["name"]],
                         "news_headline": ["ruled out" if n == fav else "" for n in base["name"]]})
    res = B.build_slate(text, *rest, n_sims=300, seed=7, field_size=100, n_candidates=3, injury_info=info)
    pool = res["pool"].set_index("name")
    assert pool.at[fav, "inj_tag"] == "Q" and pool.at[fav, "lean"] == "out" and not pool.at[fav, "recommendable"]
    assert pool.at[fav, "median"] == 0 and pool.at[fav, "news_headline"] == "ruled out"
    assert pool.at[second, "play_prob"] == pytest.approx(0.85) and pool.at[second, "median"] > 0
    assert pool.at["Kawhi Leonard", "inj_tag"] == "OUT" and pool.at["Kawhi Leonard", "status"] == "O"
    q = list(res["pool"]["name"]).index(second)
    assert 0.05 < (res["sims"][:, q] == 0).mean() < 0.3
    fav_id = int(pool.at[fav, "dk_id"])
    assert fav_id not in set(res["lineups"].dk_id) and fav_id not in set(res["swaps"].in_id)
    B.write_published(res, tmp_path)
    pub = pd.read_parquet(tmp_path / "pool.parquet")
    meta = json.loads((tmp_path / "build_meta.json").read_text())
    assert {"inj_tag", "inj_class", "recommendable", "play_prob", "lean"} <= set(pub.columns)
    again = simulate(pub, meta["n_sims"], meta["seed"])
    assert np.array_equal(again, res["sims"]) and B.sims_fingerprint(again) == meta["sims_fingerprint"]


def test_nba_build_slate_backups_cover_rank0_lineups():
    text, *rest = _inputs()
    fav, _ = _plain_rank0_favourites((text, *rest))
    res = B.build_slate(_set_status(text, {fav: "GTD"}), *rest, n_sims=300, seed=7, field_size=100,
                        n_candidates=3)
    lus, bk, p = res["lineups"], res["injury_backups"], res["pool"]
    q = int(p.set_index("name").at[fav, "dk_id"])
    rec = lus[lus["rank"] == 0]
    keys = set(rec.loc[rec.dk_id == q, "contest_key"])
    assert keys                                                          # not vacuous
    assert list(bk.columns) == ["contest_key", *BACKUP_COLUMNS]
    tagged = rec.merge(p[["dk_id", "inj_class"]], on="dk_id")
    assert len(bk) == int((tagged.inj_class != "healthy").sum())
    assert set(bk.loc[bk.tagged_dk_id == q, "contest_key"]) == keys
    healthy = set(p.loc[p.inj_class == "healthy", "dk_id"].astype(int))
    assert {int(i) for ids in bk.in_dk_ids for i in ids} <= healthy
    assert set(bk.kind) <= {"1:1", "two-player", "none"}


def test_old_style_call_still_builds_and_classifies():
    res = B.build_slate(*_inputs(), n_sims=200, seed=7, field_size=100, n_candidates=2)
    p = res["pool"].set_index("name")
    assert p.at["Mikal Bridges", "inj_tag"] == "Q" and p.at["Mikal Bridges", "play_prob"] == pytest.approx(0.85)
    assert (p["news_headline"] == "").all() and (p["lean"] == "").all()


def test_build_slate_survives_backup_failure(monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("backups broke")
    monkeypatch.setattr(B, "rank0_backups", boom)
    with caplog.at_level("ERROR", logger="nbadfs.build"):
        res = B.build_slate(*_inputs(), n_sims=200, seed=7, field_size=100, n_candidates=2)
    bk = res["injury_backups"]
    assert len(bk) == 0 and list(bk.columns) == ["contest_key", *BACKUP_COLUMNS]
    assert len(res["lineups"]) and "injury backups failed" in caplog.text
