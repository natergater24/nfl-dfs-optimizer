import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pytest
import requests

from nfldfs import dk_salaries

FIX = Path(__file__).parent / "fixtures"


def _lobby():
    return json.loads((FIX / "lobby_sample.json").read_text())


def test_find_main_slate_picks_biggest_sunday_1pm_classic():
    slate = dk_salaries.find_main_slate(_lobby(), dt.date(2026, 10, 12))
    assert slate == {"draft_group_id": 154941, "contest_type_id": 21,
                     "start": "2026-10-18T13:00:00", "game_count": 10}


def test_find_main_slate_skips_past_weeks():
    assert dk_salaries.find_main_slate(_lobby(), dt.date(2026, 10, 19))["draft_group_id"] == 153728


def test_find_main_slate_raises_when_none():
    with pytest.raises(LookupError, match="main slate"):
        dk_salaries.find_main_slate({"DraftGroups": []}, dt.date(2026, 10, 12))


def test_parse_salary_csv_statuses_and_bom():
    text = (FIX / "dk_salaries_sample.csv").read_bytes().decode("utf-8")
    pool = dk_salaries.parse_salary_csv(text)
    assert list(pool.columns) == ["dk_id", "name", "position", "salary", "team", "opp", "game_id",
                                  "is_home", "kickoff", "dk_avg", "status", "playable"]
    puka = pool[pool.name == "Puka Nacua"].iloc[0]
    assert puka.dk_id == 44475972 and puka.salary == 8100 and puka.team == "LAR"
    assert puka.opp == "ARI" and puka.game_id == "ARI@LAR" and bool(puka.is_home)
    assert puka.kickoff == pd.Timestamp("2026-10-18 16:05") and puka.status == "Q"
    assert dict(zip(pool.name, pool.playable)) == {
        "Bijan Robinson": True, "Puka Nacua": True, "Some Quarterback": False,
        "Some Tightend": False, "Doubtful Receiver": False, "Rams": True}
    assert pool[pool.name == "Bijan Robinson"].status.iloc[0] == ""


def test_parse_salary_csv_rejects_wrong_file():
    with pytest.raises(ValueError, match="missing columns"):
        dk_salaries.parse_salary_csv("a,b\n1,2\n")


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class _Session:
    def __init__(self, resp):
        self.resp, self.urls = resp, []

    def get(self, url, **kw):
        self.urls.append(url)
        return self.resp


def test_fetch_salary_csv_builds_url_and_returns_text():
    s = _Session(_Resp("﻿Position,Name + ID\n"))
    text = dk_salaries.fetch_salary_csv({"draft_group_id": 154941, "contest_type_id": 21}, session=s)
    assert text.startswith("Position")
    assert s.urls == ["https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId=21&draftGroupId=154941"]


def test_fetch_salary_csv_rejects_html():
    s = _Session(_Resp("<HTML><HEAD><TITLE>Access Denied</TITLE>"))
    with pytest.raises(RuntimeError, match="DKSalaries.csv"):
        dk_salaries.fetch_salary_csv({"draft_group_id": 1, "contest_type_id": 21}, session=s)


def test_fetch_lobby_non_json_gives_plain_guidance():
    class R:
        text = "<html>Access denied</html>"

        def raise_for_status(self):
            pass

        def json(self):
            raise json.JSONDecodeError("Expecting value", self.text, 0)

    class S:
        def get(self, *a, **k):
            return R()

    with pytest.raises(RuntimeError, match="--salary-csv PATH") as e:
        dk_salaries.fetch_lobby(S())
    assert e.value.__suppress_context__ is True


def test_lobby_contests_filters_by_draft_group():
    lobby = {"Contests": [
        {"id": 196653900, "n": "NFL $2.75M Fantasy Football Millionaire", "a": 20, "m": 161764, "dg": 154941},
        {"id": 1, "n": "NFL Showdown", "a": 5, "m": 100, "dg": 999}]}
    c = dk_salaries.lobby_contests(lobby, 154941)
    assert list(c.columns) == ["contest_id", "contest_name", "entry_fee", "max_entries"]
    assert c.to_dict("records") == [{"contest_id": "196653900", "contest_name": "NFL $2.75M Fantasy Football Millionaire",
                                     "entry_fee": 20.0, "max_entries": 161764}]
    assert dk_salaries.lobby_contests({}, 1).empty
