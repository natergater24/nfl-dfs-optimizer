from nfldfs.teams import ODDS_API_NAMES, normalize_name, to_dk_team


def test_nflverse_abbreviations_map_to_draftkings():
    assert to_dk_team("LA") == "LAR"
    assert to_dk_team("kc") == "KC"
    assert to_dk_team("JAX") == "JAX"


def test_odds_api_names_cover_32_teams():
    assert len(ODDS_API_NAMES) == 32 and len(set(ODDS_API_NAMES.values())) == 32
    assert ODDS_API_NAMES["Los Angeles Rams"] == "LAR"


def test_normalize_name_strips_suffixes_and_punctuation():
    assert normalize_name("Kenneth Walker III") == normalize_name("Kenneth Walker") == "kenneth walker"
    assert normalize_name("Amon-Ra St. Brown") == "amon ra st brown"
    assert normalize_name("D'Andre Swift") == "dandre swift"
    assert normalize_name("Marvin Harrison Jr.") == "marvin harrison"
