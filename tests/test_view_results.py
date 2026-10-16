import pandas as pd

from nfldfs_app import actions, data, view_results


def test_filter_entries(results_root):
    d = data.load(results_root / "published")
    e = d.entries
    assert len(view_results.filter_entries(e, "2026", "all", "All lineups")) == 2
    assert list(view_results.filter_entries(e, "2026", "double_up", "All lineups").entry_id) == ["9002"]
    assert list(view_results.filter_entries(e, "2026", "all", "App lineups").entry_id) == ["9002"]
    assert list(view_results.filter_entries(e, "2026", "all", "My builds").entry_id) == ["9003"]
    assert view_results.filter_entries(e, "2025", "all", "All lineups").empty


def test_tab_hosted_is_read_only(make_app, results_root):
    at = make_app(results_root / "published", hosted="1")
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert "Profit" in labels and "Cashed" in labels
    assert any("Edit on your Mac" in c.value for c in at.caption)
    assert not [b for b in at.button if str(b.key).startswith("save_")]
    assert not [n for n in at.number_input if str(n.key).startswith("win_")]


def test_tab_local_edit_saves(make_app, results_root, monkeypatch):
    calls = []
    monkeypatch.setattr(actions, "save_entry_edit", lambda entry_id, **f: calls.append((entry_id, f)) or (True, "Saved."))
    at = make_app(results_root / "published", hosted="0")
    assert not at.exception
    at.number_input(key="win_9003").set_value(30.0)
    at.button(key="save_9003").click().run()
    assert calls and calls[0][0] == "9003" and calls[0][1]["winnings"] == 30.0


def test_player_history_search(make_app, results_root):
    at = make_app(results_root / "published", hosted="1")
    d = data.load(results_root / "published")
    name = d.player_weeks["name"].iloc[0]
    at.selectbox(key="ph_player").set_value(name).run()
    assert not at.exception
    assert any("Slates projected" == m.label for m in at.metric)


def test_tab_with_no_entries(make_app, published_dir):
    at = make_app(published_dir, hosted="1")
    assert not at.exception
    assert any("No entries yet" in i.value for i in at.info)


def test_totals_follow_type_filter(make_app, results_root):
    at = make_app(results_root / "published", hosted="1")
    assert [m.value for m in at.metric if m.label == "Entries"] == ["2"]
    at.selectbox(key="res_type").set_value("double_up").run()
    assert not at.exception
    assert [m.value for m in at.metric if m.label == "Entries"] == ["1"]


def test_place_text_handles_missing_field_size():
    nan = float("nan")
    assert view_results._place_text(5.0, nan) == " \u00b7 place 5"
    assert view_results._place_text(5.0, 100.0) == " \u00b7 5 of 100"
    assert view_results._place_text(nan, nan) == ""


def test_md_escapes_dollars_and_box_score_order(results_root):
    assert view_results._md("Fees $40 \u00b7 Won $60") == "Fees \\$40 \u00b7 Won \\$60"
