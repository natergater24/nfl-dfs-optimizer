import pytest

from nfldfs import dk_rules
from nfldfs.optimizer import InfeasibleError
from nfldfs_app import data, view_pool


def test_pool_view_filters_and_sorts(published_dir):
    d = data.load(published_dir)
    v = view_pool.pool_view(d.pool, ["WR", "TE"], ["Chalk", "Popular", "Moderate", "Contrarian"], "Ceiling")
    assert set(v.position) <= {"WR", "TE"} and v.playable.all()
    assert v.ceiling.is_monotonic_decreasing and "value" in v.columns


def test_rebuild_respects_locks(published_dir):
    d = data.load(published_dir)
    lock = int(d.pool[(d.pool.position == "TE") & d.pool.playable].sort_values("salary").dk_id.iloc[0])
    lu, metric = view_pool.rebuild(d, "tournament", [lock], [])
    assert dk_rules.validate_lineup(lu) == [] and lock in lu.dk_id.tolist() and 0 <= metric <= 1
    assert list(lu.slot) == list(dk_rules.ROSTER_SLOTS)


def test_rebuild_impossible_locks_raise(published_dir):
    d = data.load(published_dir)
    qbs = d.pool[(d.pool.position == "QB") & d.pool.playable].dk_id.astype(int).tolist()[:2]
    with pytest.raises(InfeasibleError):
        view_pool.rebuild(d, "tournament", qbs, [])                     # two QBs can't both fit


def test_pool_tab_renders(make_app, published_dir):
    at = make_app(published_dir)
    assert not at.exception
    assert at.multiselect(key="pool_locks") is not None and at.button(key="pool_rebuild").disabled


def test_send_rebuilt_lineup_to_builder(make_app, published_dir):
    d = data.load(published_dir)
    at = make_app(published_dir)
    ms = at.multiselect(key="pool_locks")
    te = d.pool[(d.pool.position == "TE") & d.pool.playable].sort_values("salary").iloc[0]
    label = next(o for o in ms.options if o.startswith(f"{te['name']} · TE"))
    ms.select(label).run()
    at.button(key="pool_rebuild").click().run()
    rebuilt = at.session_state["rebuilt"]["ids"]
    at.button(key="pool_send").click().run()
    assert not at.exception
    assert at.session_state["my_ids"] == rebuilt and int(te.dk_id) in rebuilt
    assert any("Copied into 🛠 My Lineup" in s.value for s in at.success)


def test_stale_rebuilt_lineup_is_dropped(make_app, published_dir):
    at = make_app(published_dir)
    at.session_state["rebuilt"] = {"key": "single_entry", "ids": list(range(1, 10)), "metric": 0.5}
    at.run()
    assert not at.exception and "rebuilt" not in at.session_state
