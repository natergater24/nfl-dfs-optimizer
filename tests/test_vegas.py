import json
from pathlib import Path

import pytest
import requests

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


KEY = "SECRETKEY123"


class _Resp:
    def __init__(self, status):
        self.status_code = status
        self.headers = {}

    def raise_for_status(self):
        err = requests.HTTPError(f"{self.status_code} Client Error for url: https://x/odds?apiKey={KEY}")
        err.response = self
        raise err


class _Session:
    def __init__(self, result):
        self.result = result

    def get(self, url, **kw):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _assert_clean(e):
    msg = str(e.value)
    assert "apiKey" not in msg and KEY not in msg and "http" not in msg.lower().replace("(http ", "")
    assert e.value.__suppress_context__ is True and e.value.__cause__ is None


def test_fetch_odds_http_error_hides_key():
    with pytest.raises(RuntimeError, match=r"HTTP 401") as e:
        vegas.fetch_odds(KEY, session=_Session(_Resp(401)))
    _assert_clean(e)
    assert "quota" in str(e.value)


def test_fetch_odds_network_error_hides_key():
    boom = requests.ConnectionError(f"HTTPSConnectionPool: url /odds?apiKey={KEY} failed")
    with pytest.raises(RuntimeError, match="network error") as e:
        vegas.fetch_odds(KEY, session=_Session(boom))
    _assert_clean(e)
