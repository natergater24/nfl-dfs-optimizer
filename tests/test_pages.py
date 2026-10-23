"""The app has separate 🏈 NFL and 🏀 NBA pages in the left-hand menu; NFL is the default."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_nfl_is_the_default_page(make_app, published_dir):
    at = make_app(published_dir)
    assert not at.exception
    assert any(t.value == "NFL DFS Lineups" for t in at.title)


def test_nba_page_renders():
    # AppTest can't follow st.navigation to another page, so run the NBA page script directly.
    at = AppTest.from_file(str(ROOT / "nba_page.py"), default_timeout=30).run()
    assert not at.exception
    assert [t.value for t in at.title] == ["NBA DFS Lineups"]


def test_entry_point_lists_both_pages():
    text = (ROOT / "app.py").read_text()
    assert 'st.Page("nfl_page.py"' in text and 'default=True' in text and 'st.Page("nba_page.py"' in text
