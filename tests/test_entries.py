import math

import numpy as np
import pandas as pd
import pytest

from nfldfs import entries as ent
from tests.conftest import make_pool

LINEUP_A = ("DST BBB DST1 FLEX AAA RB2 QB AAA QB1 RB AAA RB1 RB BBB RB1 TE AAA TE1 "
            "WR AAA WR1 WR AAA WR2 WR BBB WR1")
LINEUP_B = ("DST BBB DST1 FLEX AAA RB3 QB AAA QB1 RB AAA RB1 RB BBB RB1 TE AAA TE1 "
            "WR AAA WR1 WR AAA WR2 WR Somebody Else")
CSV = ("Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS\n"
       f"1,9001,someoneelse,0,150.5,{LINEUP_A},,AAA QB1,QB,40.00%,25.1\n"
       f"2,9002,natergater24 (1/2),0,140.1,{LINEUP_A},,AAA WR1,WR,12.50%,18.3\n"
       f"3,9003,NaterGater24 (2/2),0,120.0,{LINEUP_B},,BBB DST1,DST,5.25%,7\n")


def _pool():
    p = make_pool()
    p["median"] = 10.0
    return p


def _ids(p, names):
    return [int(p.loc[p["name"] == n, "dk_id"].iloc[0]) for n in names]


A_NAMES = ["BBB DST1", "AAA RB2", "AAA QB1", "AAA RB1", "BBB RB1", "AAA TE1", "AAA WR1", "AAA WR2", "BBB WR1"]


def test_parse_lineup():
    pairs = ent.parse_lineup(LINEUP_A)
    assert len(pairs) == 9 and pairs[0] == ("DST", "BBB DST1") and pairs[1] == ("FLEX", "AAA RB2")
    assert ent.parse_lineup("") == []


def test_read_my_entries_multi_entry_case_insensitive():
    mine = ent.read_my_entries(CSV, "natergater24")
    assert list(mine.entry_id) == ["9002", "9003"]
    assert list(mine.place) == [2, 3] and mine.field_size.iloc[0] == 3
    assert "natergater24" not in mine.to_csv().lower() and "someoneelse" not in mine.to_csv()
    assert ent.read_my_entries(CSV, "nobody").empty


def test_match_lineup_ids_and_unknown_player():
    p = _pool()
    ids = ent.match_lineup_ids(ent.parse_lineup(LINEUP_A), p)
    assert ids == _ids(p, A_NAMES)
    ids_b = ent.match_lineup_ids(ent.parse_lineup(LINEUP_B), p)
    assert ids_b[-1] is None and all(i is not None for i in ids_b[:-1])


@pytest.mark.parametrize("name,field,key", [
    ("NFL GIANT $25 Double Up [Single Entry]", 2758, "double_up"),
    ("NFL $10 Triple Up", 4100, "multiplier_3x"),
    ("NFL $2.75M Fantasy Football Millionaire", 161764, "large_tournament"),
    ("NFL $25 Head-to-Head", 2, "h2h"),
    ("NFL $400K Spy [Single Entry]", 9000, "single_entry"),
    ("", 2, "h2h"), ("", 50000, "large_tournament"), ("", 500, ""), ("NFL $20K Thunderdome", 900, "tournament")])
def test_guess_contest_type(name, field, key):
    assert ent.guess_contest_type(name, field) == key


def _slate_lineups(p):
    ids = _ids(p, A_NAMES)
    rows = []
    for key in ("h2h", "fifty_fifty", "double_up"):            # cash lineups are identical across cash types
        rows += [{"contest_key": key, "rank": 0, "dk_id": i} for i in ids]
    alt = ids[:-1] + _ids(p, ["CCC WR1"])
    rows += [{"contest_key": "tournament", "rank": 1, "dk_id": i} for i in alt]
    return pd.DataFrame(rows), ids, alt


def test_lineup_source_prefers_entry_contest_type():
    p = _pool()
    lus, ids, alt = _slate_lineups(p)
    assert ent.lineup_source(ids, lus, prefer="double_up") == "Recommended Double Up"
    assert ent.lineup_source(ids, lus) == "Recommended Head-to-Head"
    assert ent.lineup_source(alt, lus) == "Alternate #2 · Tournament"
    builds = pd.DataFrame({"players": [",".join(map(str, _ids(p, ["CCC QB1"] + A_NAMES[1:])))]})
    assert ent.lineup_source(_ids(p, ["CCC QB1"] + A_NAMES[1:]), lus, builds) == "My Lineup build"
    assert ent.lineup_source(ids[:-1] + [None], lus) == "Not from the app"


def test_build_entry_rows_and_unknown_player():
    p = _pool()
    lus, _, _ = _slate_lineups(p)
    mine = ent.read_my_entries(CSV, "natergater24")
    contest = {"contest_name": "NFL GIANT $25 Double Up [Single Entry]", "entry_fee": 25.0}
    rows = ent.build_entry_rows(mine, p, lus, None, "2026-10-18", "123", contest)
    assert list(rows.columns) == ent.ENTRY_COLUMNS
    a, b = rows.iloc[0], rows.iloc[1]
    assert a.contest_type == "double_up" and a.entry_fee == 25.0 and math.isnan(a.winnings)
    assert a.projected == pytest.approx(90.0) and a.lineup_source == "Recommended Double Up"
    assert len(a.players.split(",")) == 9 and a.points == pytest.approx(140.1)
    assert math.isnan(b.projected) and b.lineup_source == "Not from the app" and len(b.players.split(",")) == 8


def test_build_entry_rows_unknown_player():
    p = _pool()
    mine = ent.read_my_entries(CSV, "natergater24").iloc[[1]]
    rows = ent.build_entry_rows(mine, p, None, None, "2026-10-18", "123", None)
    r = rows.iloc[0]
    assert r.entry_id == "9003" and r.place == 3 and math.isnan(r.projected) and r.contest_type == ""


def test_upsert_keeps_typed_and_ignores_blanks(tmp_path):
    path = tmp_path / "entries.parquet"
    p = _pool()
    mine = ent.read_my_entries(CSV, "natergater24")
    first = ent.build_entry_rows(mine, p, None, None, "2026-10-18", "123", None)
    ent.upsert_entries(path, first)
    ent.update_entry(path, "9002", winnings=50.0, contest_type="double_up")
    again = first.copy()
    again.loc[0, "place"] = 1.0
    again.loc[0, "contest_type"] = "tournament"                    # import guess must not beat the typed type
    out = ent.upsert_entries(path, again).set_index("entry_id")
    assert len(out) == 2
    assert out.loc["9002", "winnings"] == 50.0 and out.loc["9002", "contest_type"] == "double_up"
    assert out.loc["9002", "place"] == 1.0
    assert set(out.loc["9002", "typed_fields"].split(",")) == {"winnings", "contest_type"}


def test_update_entry_rejects_unknown_fields(tmp_path):
    path = tmp_path / "entries.parquet"
    ent.upsert_entries(path, ent.build_entry_rows(ent.read_my_entries(CSV, "natergater24"), _pool(), None, None,
                                                  "2026-10-18", "123", None))
    with pytest.raises(ValueError):
        ent.update_entry(path, "9002", points=999.0)
    with pytest.raises(KeyError):
        ent.update_entry(path, "nope", winnings=1.0)


def test_add_manual_entry_and_summary(tmp_path):
    path = tmp_path / "entries.parquet"
    ent.add_manual_entry(path, slate_date="2026-10-11", contest_name="NFL $5 Double Up", contest_type="double_up",
                         entry_fee=5.0, winnings=10.0)
    ent.add_manual_entry(path, slate_date="2026-10-11", contest_name="NFL $10 Triple Up",
                         contest_type="multiplier_3x", entry_fee=10.0, winnings=0.0)
    e = ent.add_manual_entry(path, slate_date="2026-10-18", contest_name="NFL $20 Tournament",
                             contest_type="tournament", entry_fee=20.0, winnings=np.nan)
    assert len(e) == 3 and e.entry_id.str.startswith("manual-").all() and e.entry_id.is_unique
    s = ent.summary(e)
    assert (s["entries"], s["settled"], s["cashed"], s["waiting"]) == (3, 2, 1, 1)
    assert s["fees"] == 15.0 and s["winnings"] == 10.0 and s["profit"] == -5.0
    assert s["cash_rate"] == pytest.approx(0.5) and s["roi"] == pytest.approx(-5 / 15)
    by = {r["contest_type"]: r for r in ent.summary_by_type(e)}
    assert by["double_up"]["label"] == "Double Up" and by["double_up"]["profit"] == 5.0
    empty = ent.summary(ent.empty_entries())
    assert empty["entries"] == 0 and empty["cash_rate"] is None and empty["roi"] is None


def test_lineup_source_matches_any_build_preferring_latest():
    p = _pool()
    ids = _ids(p, A_NAMES)
    other = ids[:-1] + _ids(p, ["CCC WR1"])
    rows = [{"built_at": "2026-10-15T08:00:00", "contest_key": "h2h", "rank": 0, "dk_id": i} for i in ids]
    rows += [{"built_at": "2026-10-18T09:00:00", "contest_key": "h2h", "rank": 0, "dk_id": i} for i in other]
    lus = pd.DataFrame(rows)
    assert ent.lineup_source(ids, lus, prefer="h2h") == "Recommended Head-to-Head"      # from the first build
    later = pd.DataFrame(rows + [{"built_at": "2026-10-18T11:45:00", "contest_key": "h2h", "rank": 1, "dk_id": i}
                                 for i in ids])
    assert ent.lineup_source(ids, later, prefer="h2h") == "Alternate #2 · Head-to-Head"  # latest build wins
