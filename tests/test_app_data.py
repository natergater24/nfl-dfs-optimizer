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
