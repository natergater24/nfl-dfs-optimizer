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


def test_display_numbers_uses_dash_for_missing():
    import numpy as np
    from nfldfs_app import ui
    t = pd.DataFrame({"Slate": ["x"], "Matchup": ["vs A"], "Salary": [7500.0], "Projected": [20.0],
                      "Actual": [np.nan], "+/\u2212": [np.nan], "Own est.": [19.0], "Own actual": [np.nan],
                      "My entry": ["\u2014"], "mu_color": ["#123456"]})
    shown = ui.display_numbers(t.drop(columns=["mu_color"]), ui.HISTORY_FORMATS)
    row = shown.iloc[0]
    assert row["Salary"] == "$7,500" and row["Projected"] == "20.0" and row["Own est."] == "19%"
    assert row["Actual"] == row["+/\u2212"] == row["Own actual"] == "\u2014"
    styled = ui.styled_player_history(t)
    assert "None" not in styled.data.to_string() and "nan" not in styled.data.to_string().lower()


def _root_with_blank_entry(results_root, tmp_path):
    import shutil
    from nfldfs import entries as ent
    root = tmp_path / "data"
    shutil.copytree(results_root, root)
    ent.upsert_entries(root / "history" / "entries.parquet", pd.DataFrame([
        {"entry_id": "9004", "contest_id": "557", "slate_date": "2026-10-18", "contest_name": "NFL $5 Showdown $1K",
         "contest_type": "", "entry_fee": float("nan"), "winnings": float("nan"), "place": 3.0, "field_size": 500.0,
         "points": 90.0, "players": "", "projected": float("nan"), "lineup_source": "Not from the app",
         "typed_fields": ""}]))
    return root


def test_edit_blank_type_and_fee_sends_only_changed_fields(make_app, results_root, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(actions, "save_entry_edit", lambda entry_id, **f: calls.append((entry_id, f)) or (True, "Saved."))
    at = make_app(_root_with_blank_entry(results_root, tmp_path) / "published", hosted="0")
    assert not at.exception
    assert at.selectbox(key="type_9004").value == ""
    assert at.number_input(key="fee_9004").value is None
    at.number_input(key="win_9004").set_value(30.0)
    at.button(key="save_9004").click().run()
    assert calls == [("9004", {"winnings": 30.0})]


def test_entry_label_escapes_dollars(make_app, results_root, tmp_path):
    at = make_app(_root_with_blank_entry(results_root, tmp_path) / "published", hosted="1")
    labels = [x.label for x in at.expander if "Showdown" in x.label]
    assert labels and "\\$5" in labels[0] and "\\$1K" in labels[0]


def test_save_with_failed_publish_shows_warning(make_app, results_root, monkeypatch):
    monkeypatch.setattr(actions, "save_entry_edit",
                        lambda entry_id, **f: (True, "Saved. WARNING: push to GitHub failed — offline"))
    at = make_app(results_root / "published", hosted="0")
    at.number_input(key="win_9003").set_value(30.0)
    at.button(key="save_9003").click().run()
    assert any("push to GitHub failed" in w.value for w in at.warning)
    assert not any("push to GitHub failed" in s.value for s in at.success)


def test_filter_entries_uses_nfl_season():
    e = pd.DataFrame({"entry_id": ["a", "b"], "slate_date": ["2027-01-03", "2027-09-12"],
                      "contest_type": ["h2h", "h2h"], "lineup_source": ["", ""]})
    assert list(view_results.filter_entries(e, "2026", "all", "All lineups").entry_id) == ["a"]
    assert list(view_results.filter_entries(e, "2027", "all", "All lineups").entry_id) == ["b"]
