import pandas as pd

from nfldfs.config import CONTEST_TYPES
from nfldfs_app import data, view_builder


def _d(published_dir):
    return data.load(published_dir)


def _rec_ids(d, key="fifty_fifty"):
    return d.lineups[(d.lineups.contest_key == key) & (d.lineups["rank"] == 0)].dk_id.astype(int).tolist()


def test_builder_records(published_dir):
    d = _d(published_dir)
    w = CONTEST_TYPES["large_tournament"]["weights"]
    recs = view_builder.builder_records(d.pool, w)
    assert len(recs) == int(d.pool.playable.sum())
    r = recs[0]
    assert set(view_builder.BUILDER_FIELDS) <= set(r) and isinstance(r["dk_id"], int)
    row = d.pool.set_index("dk_id").loc[r["dk_id"]]
    assert abs(r["score"] - (row.ceiling - 0.30 * row.own_pct)) < 1e-2


def test_apply_builder_value():
    cur = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert view_builder.apply_builder_value(None, None, cur) == (None, None)
    v = {"ids": [1, 2, 3, 4, 5, 6, 7, 8, 10], "t": 1}
    new, seen = view_builder.apply_builder_value(v, None, cur)
    assert new == [1, 2, 3, 4, 5, 6, 7, 8, 10] and seen == v
    assert view_builder.apply_builder_value(v, v, cur) == (None, v)               # already applied
    same = {"ids": cur, "t": 2}
    assert view_builder.apply_builder_value(same, v, cur) == (None, same)


def test_lineup_status_valid_and_errors(published_dir):
    d = _d(published_dir)
    ids = _rec_ids(d)
    ok = view_builder.lineup_status(ids, d.pool)
    assert ok["valid"] and ok["messages"] == [] and ok["used"] <= 50_000
    empty = view_builder.lineup_status([None] * 9, d.pool)
    assert not empty["valid"] and "9 slot(s) still empty." in empty["messages"]
    dup = view_builder.lineup_status(ids[:8] + [ids[0]], d.pool)
    assert not dup["valid"]


def test_lineup_status_flags_out_player(published_dir):
    d = _d(published_dir)
    ids = _rec_ids(d)
    pool = d.pool.copy()
    pool.loc[pool.dk_id == ids[1], "playable"] = False
    st = view_builder.lineup_status(ids, pool)
    assert not st["valid"] and any("ruled out" in m for m in st["messages"])


def test_lineup_status_over_cap(published_dir):
    d = _d(published_dir)
    ids = _rec_ids(d)
    pool = d.pool.copy()
    pool.loc[pool.dk_id == ids[0], "salary"] += 20_000
    st = view_builder.lineup_status(ids, pool)
    assert not st["valid"] and any("Over the cap" in m for m in st["messages"])


def test_my_lineup_tab_defaults_and_load_blank(make_app, published_dir):
    at = make_app(published_dir)
    assert not at.exception
    d = _d(published_dir)
    assert at.session_state["my_ids"] == _rec_ids(d, "single_entry")
    at.selectbox(key="builder_start").set_value("Blank lineup").run()
    at.button(key="builder_load").click().run()
    assert at.session_state["my_ids"] == [None] * 9 and not at.exception
