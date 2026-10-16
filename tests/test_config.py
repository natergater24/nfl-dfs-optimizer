import datetime as dt

from nfldfs import config


def test_contest_types_use_draftkings_names_and_valid_metrics():
    labels = [c["label"] for c in config.CONTEST_TYPES.values()]
    assert labels == [
        "Head-to-Head", "50/50", "Double Up",
        "Triple Up (3x)", "Quintuple Up (5x)", "10x Multiplier",
        "Single Entry / 3-Max Tournament", "Tournament", "Large-Field Tournament (e.g. Millionaire Maker)",
    ]
    for c in config.CONTEST_TYPES.values():
        assert c["group"] in ("Cash", "Multiplier", "Tournament")
        assert c["metric"]["kind"] in ("h2h", "top_pct")
        if c["metric"]["kind"] == "top_pct":
            assert 0 < c["metric"]["pct"] < 1
        assert set(c["weights"]) <= {"floor", "median", "ceiling", "own_penalty"}
        assert c["stack"] == (c["group"] == "Tournament")


def test_game_style_constants():
    assert config.GAME_STYLE == "Classic"
    assert config.SLATE_NAME == "Sunday main slate"


def test_season_for_rolls_over_in_september():
    assert config.season_for(dt.date(2026, 10, 12)) == 2026
    assert config.season_for(dt.date(2027, 1, 3)) == 2026
    assert config.season_for(dt.date(2026, 9, 1)) == 2026


def test_dk_username_from_env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("DK_USERNAME", raising=False)
    assert config.dk_username() is None
    (tmp_path / "env.txt").write_text("DK_USERNAME= someone \n")
    assert config.dk_username() == "someone"
    monkeypatch.delenv("DK_USERNAME", raising=False)
