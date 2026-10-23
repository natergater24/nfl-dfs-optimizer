import datetime as dt
import json
from pathlib import Path

import pytest

import nfldfs.config as nfl_config
from nbadfs import config, dk

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def test_classic_slates_from_lobby():
    lobby = json.loads((FIX / "nba_lobby_sample.json").read_text())
    slates = dk.classic_slates(lobby, dt.date(2026, 10, 23))
    assert [s["name"] for s in slates] == ["Main", "Night", "Late Night"]
    assert [s["games"] for s in slates] == [6, 5, 3]
    assert [s["draft_group_id"] for s in slates] == [155547, 155553, 155557]
    assert slates[0]["start"] == "2026-10-23T19:00:00"
    assert dk.classic_slates(lobby, dt.date(2026, 10, 24)) == []


def test_parse_salaries():
    df = dk.parse_salaries((FIX / "nba_salaries_sample.csv").read_text())
    assert len(df) == 40
    row = df[df["name"] == "Grayson Allen"].iloc[0]
    assert row["game"] == "ATL@CHA" and row["team"] == "CHA" and row["opp"] == "ATL"
    assert row["tip"] == "2026-10-23T19:00:00"
    assert row["slots"] == ["SG", "SF", "G", "F", "UTIL"]
    assert row["positions"] == "SG/SF" and row["salary"] == 4800
    assert df[df["name"] == "Giannis Antetokounmpo"].iloc[0]["tip"].endswith("20:00:00")
    out = df[df["name"] == "Kawhi Leonard"].iloc[0]
    assert out["status"] == "O" and not out["playable"]
    assert df[df["name"] == "Mikal Bridges"].iloc[0]["status"] == "Q"
    assert df[df["name"] == "Mikal Bridges"].iloc[0]["playable"]
    # DraftKings's real feed writes OUT; it is normalised to "O"
    assert df[df["name"] == "Coby White"].iloc[0]["status"] == "O"
    assert df["game"].nunique() == 6
    assert df["dk_id"].dtype.kind == "i"


def test_fetch_lobby_and_salary_csv_use_nba_urls():
    calls = []

    class R:
        def __init__(self, text): self.text = text
        def raise_for_status(self): pass
        def json(self): return {"DraftGroups": []}

    class S:
        def get(self, url, **kw):
            calls.append(url)
            return R("Position,Name\nPG,x")

    assert dk.fetch_lobby(S()) == {"DraftGroups": []}
    assert "sport=NBA" in calls[0]
    assert dk.fetch_salary_csv(155547, S()).startswith("Position")
    assert "contestTypeId=70" in calls[1] and "draftGroupId=155547" in calls[1]


def test_fetch_salary_csv_rejects_non_csv():
    class R:
        text = "<html>blocked</html>"
        def raise_for_status(self): pass

    class S:
        def get(self, url, **kw): return R()

    with pytest.raises(RuntimeError):
        dk.fetch_salary_csv(1, S())


def test_nba_contest_labels():
    t = config.NBA_CONTEST_TYPES
    assert set(t) == set(nfl_config.CONTEST_TYPES)
    assert t["single_entry"]["label"] == "Single Entry / 3-Max Tournament (e.g. Splash)"
    assert t["tournament"]["label"] == "Tournament (e.g. Fadeaway, Box Out)"
    assert t["large_tournament"]["label"] == "Large-Field Tournament (e.g. Mega 8's)"
    assert not any(c["stack"] for c in t.values())
    # NFL config untouched
    assert nfl_config.CONTEST_TYPES["tournament"]["label"] == "Tournament"
    assert nfl_config.CONTEST_TYPES["tournament"]["stack"] is True
    assert config.SALARY_CAP == 50_000 and config.SEED == 20261023
