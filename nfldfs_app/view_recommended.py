"""⭐ Recommended tab: the contest's best lineup, alternates, outlier swaps, report card."""
from __future__ import annotations

import streamlit as st

from nfldfs.config import CONTEST_TYPES, SALARY_CAP
from nfldfs.dk_rules import upload_csv_text
from nfldfs_app import ui
from nfldfs_app.scoring import published_metric


def stack_summary(lu) -> str:
    qbs = lu[lu["position"] == "QB"]
    if qbs.empty:
        return ""
    qb = qbs.iloc[0]
    mates = lu[(lu["team"] == qb["team"]) & lu["position"].isin(["WR", "TE"])]["name"].tolist()
    back = lu[(lu["team"] == qb["opp"]) & lu["position"].isin(["RB", "WR", "TE"])]["name"].tolist()
    if not mates:
        return f"No QB stack ({qb['name']} alone)"
    return f"Stack: {qb['name']} + {', '.join(mates)}" + (f" · bring-back: {', '.join(back)}" if back else "")


def apply_swap(rec_ids, out_id, in_id) -> tuple[list[int], int]:
    ids = [int(i) for i in rec_ids]
    slot = ids.index(int(out_id))
    ids[slot] = int(in_id)
    return ids, slot


def render(d, key, label, field_scores):
    contest = CONTEST_TYPES[key]
    rec = d.lineups[(d.lineups.contest_key == key) & (d.lineups["rank"] == 0)]
    ids = rec.dk_id.astype(int).tolist()
    total = int(rec.salary.sum())
    m = st.columns(4)
    m[0].metric("Salary used", ui.money(total), f"{ui.money(SALARY_CAP - total)} left", delta_color="off")
    m[1].metric("Projected median", f"{rec['median'].sum():.1f}")
    m[2].metric("Ceiling (p85 sum)", f"{rec['ceiling'].sum():.1f}")
    m[3].metric(f"{ui.metric_phrase(key, contest['group'])} in",
                f"{published_metric(d, ids, key, field_scores):.0%} of sims", help=ui.MODEL_RELATIVE_HELP)
    st.dataframe(ui.styled_lineup(rec), hide_index=True, width="stretch")
    st.caption(stack_summary(rec))
    st.download_button("⬇ Download DraftKings upload CSV", upload_csv_text([rec]), file_name=f"dk_upload_{key}.csv",
                       mime="text/csv", key=f"dl_{key}")

    with st.expander("Alternates (#2 and #3)"):
        for r in (1, 2):
            alt = d.lineups[(d.lineups.contest_key == key) & (d.lineups["rank"] == r)]
            if alt.empty:
                continue
            st.markdown(f"**#{r + 1}** — {ui.money(alt.total_salary.iloc[0]).replace('$', chr(92) + '$')} · "
                        f"{ui.metric_phrase(key, contest['group']).lower()} in "
                        f"{published_metric(d, alt.dk_id.astype(int).tolist(), key, field_scores):.0%} of sims")
            st.dataframe(ui.styled_lineup(alt), hide_index=True, width="stretch")

    st.subheader("💎 Outliers — swaps that keep you under the cap")
    sw = d.swaps[d.swaps.contest_key == key]
    if sw.empty:
        st.caption("No cap-safe swaps for this lineup.")
    by_id = d.pool.set_index("dk_id")
    for i, s in enumerate(sw.itertuples(index=False)):
        c = st.columns([7, 1], vertical_alignment="center")
        c[0].markdown(ui.swap_line(s, by_id), unsafe_allow_html=True)
        if c[1].button("Apply", key=f"apply_{key}_{i}"):
            new_ids, slot = apply_swap(ids, s.out_dk_id, s.in_dk_id)
            st.session_state.my_ids = new_ids
            st.session_state.focus_slot = slot
            st.session_state.focus_token = st.session_state.get("focus_token", 0) + 1
            st.toast("Swap copied into 🛠 My Lineup — open that tab.")

    with st.expander("📈 Report card — projections vs. actual results"):
        ui.report_card_widget(d.report_card)
