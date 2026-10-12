import pandas as pd

from nfldfs_app import ui


def test_money_full_dollars():
    assert ui.money(7500) == "$7,500" and ui.money(-1700) == "-$1,700" and ui.money(49900.0) == "$49,900"


def test_metric_phrase():
    assert ui.metric_phrase("h2h", "Cash") == "Wins the head-to-head"
    assert ui.metric_phrase("fifty_fifty", "Cash") == "Cashes"
    assert ui.metric_phrase("multiplier_3x", "Multiplier") == "Hits the multiplier"
    assert ui.metric_phrase("tournament", "Tournament") == "Finishes top-1%"


def test_updated_text_colors():
    assert ui.updated_text(5) == ("Updated 5 min ago", "green")
    assert ui.updated_text(180) == ("Updated 3 h ago", "orange")
    assert ui.updated_text(3000)[1] == "red" and ui.updated_text(None)[1] == "gray"


def test_styled_lineup_formats_salary(published_dir):
    from nfldfs_app import data
    d = data.load(published_dir)
    rec = d.lineups[(d.lineups.contest_key == "fifty_fifty") & (d.lineups["rank"] == 0)]
    html = ui.styled_lineup(rec).to_html()
    assert "$" in html and "," in html and "background-color" in html


def test_step_labels_are_plain():
    assert ui.step_label("vegas_if_stale") == "Vegas lines" and ui.step_label("salaries") == "DraftKings salaries"
    assert ui.step_label("stats_if_missing") == "NFL stats" and ui.step_label("mystery") == "mystery"
