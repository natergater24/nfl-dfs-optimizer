"""NFL DFS Lineups — Streamlit app. Runs locally (full features) and on Streamlit Community Cloud (view/build)."""
from pathlib import Path

import streamlit as st

from nfldfs.config import CONTEST_TYPES
from nfldfs.sim_eval import lineup_scores
from nfldfs_app import actions, data, ui, view_builder, view_pool, view_recommended, view_sidebar

st.set_page_config(page_title="NFL DFS Lineups", page_icon="🏈", layout="wide")


@st.cache_resource(show_spinner=False, max_entries=2)
def _load(pub: str, stamp: tuple):
    d = data.load(Path(pub))
    return d, lineup_scores(d.sims, d.field)


pub = data.published_dir()
hosted = data.is_hosted()
if data.missing_files(pub):
    st.title("NFL DFS Lineups")
    st.warning("No lineups built yet. On your Mac run `./py run_pipeline.py --stage thursday`"
               + (" — this page updates automatically once it publishes." if hosted else "."))
    st.stop()
d, field_scores = _load(str(pub), data.stamp(pub))

flash = st.session_state.pop("flash", None)
if flash:
    (st.success if flash[0] else st.error)(flash[1].splitlines()[-1] if flash[1] else "Done")
    if not flash[0]:
        st.code(flash[1])
if hosted:
    st.info("📱 This is the hosted copy — view lineups, build variations and download CSVs. Refreshing data and "
            "importing results happen on your Mac and publish here automatically.")
failed = [s for s in d.run_status.get("steps", []) if s.get("ok") is False]
if failed:
    st.error(f"⚠ The last {d.run_status.get('stage', '')} run failed at **{failed[0].get('name', 'a step')}**: "
             f"{failed[0].get('message', '')}")

labels = {c["label"]: k for k, c in CONTEST_TYPES.items()}
top = st.columns([3, 3, 1, 1], vertical_alignment="bottom")
with top[0]:
    st.title("NFL DFS Lineups")
    text, color = ui.updated_text(data.minutes_since(d.meta.get("built_at_utc") or d.meta.get("built_at")))
    st.markdown(f"Sunday main slate · {d.meta.get('game_count', '?')} games · :{color}[{text}]")
label = top[1].selectbox("DraftKings contest type", list(labels), index=list(labels.values()).index("single_entry"),
                         key="contest_label")
key = labels[label]
with top[2].popover("ℹ️ Key", width="stretch"):
    st.markdown(ui.KEY_MARKDOWN)
if not hosted and top[3].button("⟳ Refresh", width="stretch", key="refresh",
                                help="Re-fetch injuries and lines, then rebuild lineups (about 2 minutes)"):
    with st.spinner("Refreshing — about 2 minutes…"):
        st.session_state.flash = actions.run_stage("refresh")
    st.cache_resource.clear()
    st.rerun()

view_sidebar.render(d, hosted)
tab_rec, tab_mine, tab_pool = st.tabs(["⭐ Recommended", "🛠 My Lineup", "📋 Player pool"])
with tab_rec:
    view_recommended.render(d, key, label, field_scores)
with tab_mine:
    view_builder.render(d, key, label, field_scores)
with tab_pool:
    view_pool.render(d, key, label, field_scores)
