"""Sidebar: slate status, accuracy, results-import guide and local-only actions."""
from __future__ import annotations

import streamlit as st

from nfldfs import config
from nfldfs_app import actions

# Plain-language steps. Final DraftKings button names are confirmed from Nathan's screenshots (Task 13).
IMPORT_GUIDE = """
1. On a **computer** (not the phone app), open **draftkings.com** and sign in as usual.
2. At the top, click **My Contests**.
3. Click the tab for **completed** contests.
4. Click last Sunday's contest to open it.
5. Next to the standings, click **Export** once.
6. A file named like `contest-standings-123456789.zip` downloads to your **Downloads** folder. Don't open,
   rename or move it.
7. That's it — your Mac imports it within a minute (or click **Check for results** below) and files it away.
8. You'll see **✅ imported …** here. The 📈 Report card on the Recommended tab updates after that.

**If nothing happens:** drag the zip file into **Upload results** below and click **Import**.
"""


def results_message(results_status: dict) -> str | None:
    steps = results_status.get("steps") or []
    if not steps:
        return None
    s = steps[0]
    if not s.get("ok"):
        return f"⚠ Results import failed: {s.get('message', '')}"
    return s["message"] if s["message"].startswith("skipped") else f"✅ {s['message']}"


def _run(stage: str, *extra: str) -> None:
    with st.spinner("Working…"):
        st.session_state.flash = actions.stage_flash(stage, actions.run_stage(stage, *extra))
    st.cache_resource.clear()
    st.rerun()


def render(d, hosted: bool) -> None:
    with st.sidebar:
        st.markdown("### 🏈 NFL DFS")
        st.metric("Slate", f"{d.meta.get('game_count', '?')} games")
        st.caption(f"Built {str(d.meta.get('built_at', ''))[:16].replace('T', ' ')} · "
                   f"{d.meta.get('n_sims', 0):,} sims · name match {d.meta.get('match_rate', 0):.0%} · "
                   f"Odds API left: {d.meta.get('odds_requests_remaining', '?')}")
        sea = d.report_card.get("season") if d.report_card.get("weeks") else None
        if sea:
            st.caption(f"Season accuracy: {sea.get('proj_mae', '—')} pts avg error · "
                       f"{sea.get('in_range_pct', '—')}% inside floor–ceiling")
        st.divider()
        with st.expander("📥 How to import last week's results"):
            st.markdown(IMPORT_GUIDE)
        msg = results_message(d.results_status)
        if msg:
            st.caption(msg)
        if not hosted and config.dk_username() is None:
            st.info("To track your own entries in 📒 My Results, add a line `DK_USERNAME=your DraftKings "
                    "username` to env.txt (see the user manual).")
        if hosted:
            st.caption("Importing results and uploading files work in the app on your Mac.")
        if st.button("Check for results", disabled=hosted, key="check_results", width="stretch"):
            _run("results")
        up = st.file_uploader("Upload results (fallback)", type=["zip", "csv"], disabled=hosted, key="up_results")
        if up is not None and st.button("Import", key="import_upload", disabled=hosted):
            _run("results", "--results-file", str(actions.save_upload(up, config.RAW / "standings_inbox")))
        sal = st.file_uploader("Upload DKSalaries.csv (fallback)", type=["csv"], disabled=hosted, key="up_salaries")
        if sal is not None and st.button("Rebuild with this salary file", key="use_salaries", disabled=hosted):
            _run("refresh", "--salary-csv", str(actions.save_upload(sal, config.RAW / "manual")))
