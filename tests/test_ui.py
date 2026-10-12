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


def test_to_eastern_aware_utc_and_naive():
    aware = ui.to_eastern("2026-10-18T13:02:00+00:00")           # EDT = UTC-4
    assert (aware.hour, aware.minute, aware.day) == (9, 2, 18) and aware.tzinfo is not None
    naive = ui.to_eastern("2026-10-18T09:02:00")                 # naive = already Eastern
    assert (naive.hour, naive.minute) == (9, 2) and naive.utcoffset().total_seconds() == -4 * 3600
    assert ui.to_eastern(None) is None and ui.to_eastern("not a date") is None


def test_format_refresh():
    assert ui.format_refresh(ui.to_eastern("2026-10-18T09:02:00")) == "Sun Oct 18, 9:02 AM ET"
    assert ui.format_refresh(ui.to_eastern("2026-10-18T15:05:00")) == "Sun Oct 18, 3:05 PM ET"
    assert ui.format_refresh(ui.to_eastern("2026-10-18T00:30:00")) == "Sun Oct 18, 12:30 AM ET"
    assert ui.format_refresh(ui.to_eastern("2026-10-18T12:00:00")) == "Sun Oct 18, 12:00 PM ET"


def _next(iso):
    return ui.next_scheduled_refresh(ui.to_eastern(iso))


def test_next_scheduled_refresh():
    assert ui.format_refresh(_next("2026-10-12T10:00:00")) == "Tue Oct 13, 9:00 AM ET"      # Mon -> Tue
    assert ui.format_refresh(_next("2026-10-13T09:00:00")) == "Thu Oct 15, 9:00 AM ET"      # exactly on a run
    assert ui.format_refresh(_next("2026-10-18T10:00:00")) == "Sun Oct 18, 11:45 AM ET"
    assert ui.format_refresh(_next("2026-10-18T12:00:00")) == "Tue Oct 20, 9:00 AM ET"      # wraps to next week
