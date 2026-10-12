import json
from pathlib import Path

import pytest

from nfldfs import vegas

FIX = Path(__file__).parent / "fixtures"


def _games():
    return vegas.parse_odds(json.loads((FIX / "odds_sample.json").read_text()))


def test_parse_odds_takes_median_and_skips_unknown_or_empty():
    g = _games()
    assert sorted(g.game_id) == ["ARI@LAR", "CHI@ATL"]
    rams = g[g.game_id == "ARI@LAR"].iloc[0]
    assert rams.total == pytest.approx(48.0) and rams.home_spread == pytest.approx(-3.0) and rams.n_books == 2


def test_implied_totals_split_total_by_spread():
    it = _games().pipe(vegas.implied_totals).set_index("team")
    assert it.loc["LAR", "implied_total"] == pytest.approx(25.5)
    assert it.loc["ARI", "implied_total"] == pytest.approx(22.5)
    assert it.loc["LAR", "exp_margin"] == pytest.approx(3.0)
    assert it.loc["ARI", "exp_margin"] == pytest.approx(-3.0)
    assert it.loc["ATL", "implied_total"] == pytest.approx(21.25)   # home underdog by 1.5
    assert it.loc["CHI", "opp"] == "ATL" and it.loc["CHI", "game_id"] == "CHI@ATL"
