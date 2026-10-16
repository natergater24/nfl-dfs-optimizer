import datetime as dt

from nfldfs_app import data


def test_load_published(published_dir):
    d = data.load(published_dir)
    assert data.missing_files(published_dir) == []
    assert {"mu_label", "mu_color", "mu_text"} <= set(d.lineups.columns)
    assert d.sims.dtype.name == "float32" and d.field.shape[1] == 9
    assert d.row_of[int(d.pool.dk_id.iloc[5])] == 5
    assert d.meta["game_count"] == 2


def test_missing_files_and_hosted_override(tmp_path, monkeypatch):
    assert "player_pool.parquet" in data.missing_files(tmp_path)
    monkeypatch.setenv("NFLDFS_FORCE_HOSTED", "1"); assert data.is_hosted()
    monkeypatch.setenv("NFLDFS_FORCE_HOSTED", "0"); assert not data.is_hosted()


def test_minutes_since_naive_and_aware():
    now = dt.datetime(2026, 10, 15, 10, 0)
    assert data.minutes_since("2026-10-15T09:00:00", now) == 60
    aware_now = dt.datetime(2026, 10, 15, 14, 0, tzinfo=dt.timezone.utc)
    assert data.minutes_since("2026-10-15T13:00:00+00:00", aware_now) == 60
    assert data.minutes_since(None) is None


def test_load_reads_history_when_present(published_dir, tmp_path):
    import shutil
    import pandas as pd
    root = tmp_path / "data"
    shutil.copytree(published_dir, root / "published")
    (root / "history").mkdir()
    pd.DataFrame({"entry_id": ["1"]}).to_parquet(root / "history" / "entries.parquet", index=False)
    d = data.load(root / "published")
    assert len(d.entries) == 1 and d.player_weeks.empty
    assert any("entries.parquet" in str(k) for k, _ in data.stamp(root / "published"))


def test_load_without_history_gives_empty_frames(published_dir):
    d = data.load(published_dir)
    assert d.entries.empty and d.player_weeks.empty
