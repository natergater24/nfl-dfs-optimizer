import datetime as dt
import json
import os
from pathlib import Path

import pytest
import requests

from nbadfs import vegas

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _games():
    return json.loads((FIX / "nba_odds_sample.json").read_text())


def test_team_abbr_covers_all_30_with_dk_codes():
    assert len(vegas.TEAM_ABBR) == 30 and len(set(vegas.TEAM_ABBR.values())) == 30
    for code in ("PHO", "NOP", "SAS", "GSW", "NYK", "BKN", "UTA", "WAS"):
        assert code in vegas.TEAM_ABBR.values()
    assert vegas.TEAM_ABBR["Phoenix Suns"] == "PHO"


def test_team_lines_filters_day_and_implied():
    games = _games()
    lines = vegas.team_lines(games, dt.date(2026, 10, 23))
    assert list(lines.columns) == ["team", "opp", "total", "spread", "implied_total", "opp_implied"]
    assert len(lines) == 8 and set(lines.team) >= {"MIL", "CHI", "BOS", "NYK"}
    assert (lines.implied_total + lines.opp_implied - lines.total).abs().max() < 1e-9
    mil = lines.set_index("team").loc["MIL"]
    assert mil.opp == "CHI" and mil.spread == pytest.approx(-1.5)
    assert mil.implied_total == pytest.approx(mil.total / 2 + 0.75) and mil.implied_total > mil.opp_implied
    # a spread favorite always gets the larger implied total
    fav = lines[lines.spread < 0]
    assert (fav.implied_total > fav.opp_implied).all()
    xmas = vegas.team_lines(games, dt.date(2026, 12, 25))
    assert len(xmas) == 8 and set(xmas.team).isdisjoint({"MIL"}) is True
    assert vegas.team_lines(games, dt.date(2026, 11, 1)).empty


def test_lines_fresh(tmp_path):
    p = tmp_path / "lines.json"
    p.write_text("{}")
    now = dt.datetime(2026, 10, 23, 18, 0, 0)
    for minutes, expected in ((59, True), (61, False)):
        ts = (now - dt.timedelta(minutes=minutes)).timestamp()
        os.utime(p, (ts, ts))
        assert vegas.lines_fresh(p, now) is expected
    assert vegas.lines_fresh(tmp_path / "missing.json", now) is False


class _Resp:
    def __init__(self, status=200):
        self.status_code, self.headers = status, {"x-requests-remaining": "471"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("boom https://x?apiKey=SECRET", response=self)

    def json(self):
        return [{"id": "g"}]


class _Sess:
    def __init__(self, status=200):
        self.status, self.calls = status, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return _Resp(self.status)


def test_fetch_odds_uses_nba_and_hides_key():
    s = _Sess()
    games, remaining = vegas.fetch_odds("SECRET", s)
    assert games == [{"id": "g"}] and remaining == "471"
    url, params = s.calls[0]
    assert "basketball_nba" in url and params["markets"] == "spreads,totals" and params["regions"] == "us"
    with pytest.raises(RuntimeError) as e:
        vegas.fetch_odds("SECRET", _Sess(401))
    assert "SECRET" not in str(e.value)
