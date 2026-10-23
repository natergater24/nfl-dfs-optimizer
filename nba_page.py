"""🏀 NBA page of the DFS app — being built in phases (see docs/superpowers/specs, NBA design)."""
import streamlit as st

st.title("NBA DFS Lineups")
st.info("🏗 The NBA optimizer is being built. This page fills in as each part goes live.")
st.markdown("""
**Coming here**
- Tonight's DraftKings Classic slate, picked automatically (the next slate with games still to play)
- ⭐ Recommended lineups per contest type, 🛠 My Lineup, 🔁 Tweak & Rebuild, 📒 My Results
- Games that have started grayed out, a refresh warning, and late swap (⏱ in-progress players)
""")
