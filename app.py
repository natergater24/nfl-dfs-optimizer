"""DFS Lineups — Streamlit entry point. 🏈 NFL and 🏀 NBA are separate pages in the left-hand menu."""
import streamlit as st

st.set_page_config(page_title="DFS Lineups", page_icon="🏈", layout="wide")

st.navigation([st.Page("nfl_page.py", title="NFL", icon="🏈", url_path="nfl", default=True),
               st.Page("nba_page.py", title="NBA", icon="🏀", url_path="nba")]).run()
