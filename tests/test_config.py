import datetime as dt

from nfldfs import config


def test_contest_types_use_draftkings_names_and_valid_metrics():
    labels = [c["label"] for c in config.CONTEST_TYPES.values()]
    assert labels == [
        "Head-to-Head", "50/50", "Double Up",
        "Multiplier (3x)", "Multiplier (5x)", "Multiplier (10x)",
        "Single Entry / 3-Max Tournament", "Tournament", "Large-Field Tournament",
    ]
    for c in config.CONTEST_TYPES.values():
        assert c["group"] in ("Cash", "Multiplier", "Tournament")
        assert c["metric"]["kind"] in ("h2h", "top_pct")
        if c["metric"]["kind"] == "top_pct":
            assert 0 < c["metric"]["pct"] < 1
        assert set(c["weights"]) <= {"floor", "median", "ceiling", "own_penalty"}
        assert c["stack"] == (c["group"] == "Tournament")


def test_season_for_rolls_over_in_september():
    assert config.season_for(dt.date(2026, 10, 12)) == 2026
    assert config.season_for(dt.date(2027, 1, 3)) == 2026
    assert config.season_for(dt.date(2026, 9, 1)) == 2026
