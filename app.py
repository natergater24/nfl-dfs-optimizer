"""NFL DFS Lineups — Streamlit app. Runs locally (full features) and on Streamlit Community Cloud (view/build)."""
import datetime as dt
from pathlib import Path

import streamlit as st

from nfldfs.config import CONTEST_TYPES, GAME_STYLE, SALARY_CAP, SLATE_NAME
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

refreshed_at = ui.to_eastern(d.meta.get("built_at_utc") or d.meta.get("built_at"))
if st.session_state.pop("get_latest_pending", False):          # set by "Get latest" before the reload
    st.session_state.flash = (True, "Up to date — lineups last refreshed "
                              + (ui.format_refresh(refreshed_at) if refreshed_at else "(time unknown)"))
flash = st.session_state.pop("flash", None)
if flash:                                        # (ok, headline) or (ok, headline, log tail)
    (st.success if flash[0] else st.error)(flash[1])
    if len(flash) > 2 and flash[2]:
        st.code(flash[2])
if hosted:
    st.info("📱 This is the hosted copy — view lineups, build variations and download CSVs. Refreshing data and "
            "importing results happen on your Mac and publish here automatically.")
failed = [s for s in d.run_status.get("steps", []) if s.get("ok") is False]
if failed:
    st.error(f"⚠ The last {d.run_status.get('stage', '')} run failed at "
             f"**{ui.step_label(failed[0].get('name', 'a step'))}**: {failed[0].get('message', '')}")
for step in d.run_status.get("steps", []):
    if str(step.get("message", "")).startswith("WARNING"):
        st.warning(f"⚠ {ui.step_label(step.get('name', ''))}: {step['message']}")
if not hosted and str(d.run_status.get("publish", "")).startswith("WARNING"):
    st.warning(f"The phone copy may be out of date: {d.run_status['publish']}")

labels = {c["label"]: k for k, c in CONTEST_TYPES.items()}
top = st.columns([3, 3, 1, 1], vertical_alignment="bottom")
with top[0]:
    st.title("NFL DFS Lineups")
    text, color = ui.updated_text(data.minutes_since(d.meta.get("built_at_utc") or d.meta.get("built_at")))
    kickoff = ui.to_eastern(d.meta.get("start"))
    parts = [f"**Game style: {GAME_STYLE}**", SLATE_NAME] + ([ui.format_refresh(kickoff)] if kickoff else []) \
        + [f"{d.meta.get('game_count', '?')} games", f"${SALARY_CAP:,} cap"]
    st.markdown(" · ".join(parts))
    nxt = ui.format_refresh(ui.next_scheduled_refresh(dt.datetime.now(ui.EASTERN)))
    when = f"**Last refreshed: {ui.format_refresh(refreshed_at)}**" if refreshed_at else "**Last refreshed: unknown**"
    age = text.removeprefix("Updated ")
    st.markdown(f"{when} · :{color}[{age}] · next automatic refresh: {nxt}")
label = top[1].selectbox("Classic contest type", list(labels), index=list(labels.values()).index("single_entry"),
                         key="contest_label")
key = labels[label]
with top[2].popover("ℹ️ Key", width="stretch"):
    st.markdown(ui.KEY_MARKDOWN)
if hosted and top[3].button("🔄 Get latest", width="stretch", key="get_latest",
                            help="Loads the newest lineups your Mac has published. To fetch new injuries and lines, "
                                 "use Refresh in the Mac app."):
    st.session_state.get_latest_pending = True
    st.cache_resource.clear()
    st.rerun()
if not hosted and top[3].button("⟳ Refresh data now", width="stretch", key="refresh",
                                help="Re-fetch injuries and lines, then rebuild lineups (about 2 minutes)"):
    with st.spinner("Refreshing — about 2 minutes…"):
        st.session_state.flash = actions.stage_flash("refresh", actions.run_stage("refresh"))
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
