import numpy as np
import pandas as pd
import pytest

from nfldfs import entries as ent

HEADER = ('"Sport","Game_Type","Entry_Key","Entry","Contest_Key","Contest_Date_EST","Place","Points",'
          '"Winnings_Non_Ticket","Winnings_Ticket","Contest_Entries","Entry_Fee","Prize_Pool","Places_Paid"\n')
ROW = '"NFL","Classic",5295086450,"NFL GIANT $25 Double Up [Single Entry]",196672055,"2026-10-18 13:00:00",430,141.98,"$50.00","$0.00",2758,"$25.00","$60,000.00",1200\n'
NBA = '"NBA","Classic",1,"NBA thing",2,"2026-10-18 19:00:00",5,100.0,"$0.00","$0.00",100,"$5.00","$400.00",20\n'
SHOW = '"NFL","Showdown Captain Mode",3,"NFL Showdown",4,"2026-10-18 20:00:00",9,80.0,"$0.00","$0.00",100,"$3.00","$200.00",20\n'
BIG = '"NFL","Classic",7,"NFL Milly",8,"2026-10-18 13:00:00",1,200.5,"$1,234.50","$10.00",30000,"$1,000.00","$1","1"\n'


def _file(tmp_path, *rows, name="draftkings-contest-entry-history.csv"):
    p = tmp_path / name
    p.write_text(HEADER + "".join(rows))
    return p


def test_read_entry_history_sample(tmp_path):
    rows, skipped = ent.read_entry_history(_file(tmp_path, ROW))
    assert skipped == 0 and list(rows.columns) == ent.ENTRY_COLUMNS
    r = rows.iloc[0]
    assert (r.entry_id, r.contest_id, r.slate_date) == ("5295086450", "196672055", "2026-10-18")
    assert r.contest_type == "double_up" and r.entry_fee == 25.0 and r.winnings == 50.0
    assert (r.place, r.points, r.field_size) == (430, 141.98, 2758)
    assert r.players == "" and np.isnan(r.projected) and r.lineup_source == "No standings imported"
    assert r.typed_fields == ""


def test_read_entry_history_skips_other_games_and_parses_money(tmp_path):
    rows, skipped = ent.read_entry_history(_file(tmp_path, ROW, NBA, SHOW, BIG))
    assert skipped == 2 and list(rows.entry_id) == ["5295086450", "7"]
    assert rows.iloc[1].winnings == 1244.5 and rows.iloc[1].entry_fee == 1000.0


def test_read_entry_history_missing_columns(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text('"Sport","Entry_Key"\n"NFL",1\n')
    with pytest.raises(ValueError, match="Game_Type"):
        ent.read_entry_history(p)


def test_is_entry_history(tmp_path):
    assert ent.is_entry_history(_file(tmp_path, ROW))
    assert ent.is_entry_history(HEADER + ROW)
    assert ent.is_entry_history(str(_file(tmp_path, ROW, name="a.csv")))
    other = tmp_path / "o.csv"
    other.write_text("Rank,EntryId,EntryName\n1,2,x\n")
    assert not ent.is_entry_history(other)
    z = tmp_path / "s.zip"
    z.write_bytes(b"PK\x03\x04junk")
    assert not ent.is_entry_history(z)
    assert not ent.is_entry_history(tmp_path / "missing.csv")


def _store(tmp_path, **kw):
    base = {"entry_id": "5295086450", "contest_id": "", "slate_date": "2026-10-18", "contest_name": "",
            "contest_type": "", "entry_fee": np.nan, "winnings": np.nan, "place": np.nan, "field_size": np.nan,
            "points": np.nan, "players": "1,2,3", "projected": 90.0, "lineup_source": "Recommended X",
            "typed_fields": ""}
    base.update(kw)
    path = tmp_path / "entries.parquet"
    ent.upsert_entries(path, pd.DataFrame([base], columns=ent.ENTRY_COLUMNS))
    return path


def test_merge_inserts_new(tmp_path):
    path = tmp_path / "entries.parquet"
    rows, _ = ent.read_entry_history(_file(tmp_path, ROW))
    out = ent.merge_entry_history(path, rows)
    assert len(out) == 1 and len(ent.load_entries(path)) == 1
    assert ent.load_entries(path).iloc[0].winnings == 50.0


def test_merge_overrides_typed_money_keeps_typed_type_and_lineup(tmp_path):
    path = _store(tmp_path, winnings=10.0, entry_fee=20.0, contest_type="tournament", contest_name="My name",
                  typed_fields="winnings,entry_fee,contest_type,contest_name")
    rows, _ = ent.read_entry_history(_file(tmp_path, ROW))
    e = ent.merge_entry_history(path, rows).iloc[0]
    assert e.winnings == 50.0 and e.entry_fee == 25.0
    assert e.typed_fields == "contest_name,contest_type"
    assert e.contest_type == "tournament" and e.contest_name == "My name"
    assert (e.place, e.points, e.field_size, e.contest_id) == (430, 141.98, 2758, "196672055")
    assert e.players == "1,2,3" and e.projected == 90.0 and e.lineup_source == "Recommended X"


def test_merge_fills_blank_name_and_type_and_never_erases(tmp_path):
    path = _store(tmp_path, winnings=7.0, place=3.0)
    rows, _ = ent.read_entry_history(_file(tmp_path, ROW))
    e = ent.merge_entry_history(path, rows).iloc[0]
    assert e.contest_name == "NFL GIANT $25 Double Up [Single Entry]" and e.contest_type == "double_up"
    blank = rows.copy()
    blank[["entry_fee", "winnings", "place", "points", "field_size"]] = np.nan
    blank["contest_id"] = ""
    e = ent.merge_entry_history(path, blank).iloc[0]
    assert e.winnings == 50.0 and e.place == 430 and e.contest_id == "196672055"


def test_merge_typed_blank_name_not_replaced(tmp_path):
    path = _store(tmp_path, typed_fields="contest_name,contest_type")
    rows, _ = ent.read_entry_history(_file(tmp_path, ROW))
    e = ent.merge_entry_history(path, rows).iloc[0]
    assert e.contest_name == "" and e.contest_type == ""
