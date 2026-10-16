"""📒 My Results tab: season totals, filters, player history and the entry log (read-only on the phone)."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from nfldfs import entries as ent
from nfldfs import player_history as ph
from nfldfs.config import CONTEST_TYPES
from nfldfs_app import actions, ui

SOURCES = ("All lineups", "App lineups", "My builds")


def filter_entries(e: pd.DataFrame, season: str, type_key: str, source: str) -> pd.DataFrame:
    out = e[e["slate_date"].astype(str).str[:4] == str(season)]
    if type_key != "all":
        out = out[out["contest_type"] == type_key]
    if source == "App lineups":
        out = out[out["lineup_source"].str.startswith(("Recommended", "Alternate"))]
    elif source == "My builds":
        out = out[out["lineup_source"] == "My Lineup build"]
    return out


def _pct(v) -> str:
    return "—" if v is None else f"{v:.0%}"


def _totals(e: pd.DataFrame) -> None:
    s = ent.summary(e)
    c = st.columns(4)
    c[0].metric("Entries", s["entries"])
    c[1].metric("Cashed", f"{s['cashed']} ({_pct(s['cash_rate'])})")
    c[2].metric("Profit", ui.signed_money(s["profit"]),
                f"ROI {s['roi']:+.0%}" if s["roi"] is not None else None, delta_color="normal")
    c[3].metric("Avg score vs projected",
                "—" if s["avg_points"] is None else f"{s['avg_points']:.1f}",
                None if s["avg_vs_projected"] is None else f"{s['avg_vs_projected']:+.1f}")
    st.caption(f"Fees {ui.money(s['fees'])} · Winnings {ui.money(s['winnings'])}"
               + (f" · 💲 {s['waiting']} waiting on winnings" if s["waiting"] else ""))
    for t in ent.summary_by_type(e):
        st.caption(f"**{t['label']}**: {t['entries']} entries · {t['cashed']} cashed · {ui.signed_money(t['profit'])}")


def _add_form() -> None:
    with st.expander("➕ Add entry by hand"):
        with st.form("add_entry_form", clear_on_submit=True):
            day = st.date_input("Slate date", value=dt.date.today())
            name = st.text_input("Contest name")
            keys = list(CONTEST_TYPES)
            ctype = st.selectbox("Classic contest type", keys, format_func=ent.type_label)
            fee = st.number_input("Entry fee ($)", min_value=0.0, step=1.0)
            won = st.number_input("Winnings ($)", min_value=0.0, step=1.0)
            if st.form_submit_button("Save entry"):
                st.session_state.flash = actions.add_entry(slate_date=str(day), contest_name=name, contest_type=ctype,
                                                           entry_fee=float(fee), winnings=float(won))
                st.rerun()


def _player_history(pw: pd.DataFrame, e: pd.DataFrame) -> None:
    st.subheader("Player history")
    if pw.empty:
        st.caption("Player history starts with the first slate this app builds after this update.")
        return
    names = sorted(pw["name"].unique())
    c = st.columns([3, 2])
    name = c[0].selectbox("Player", ["—"] + names, key="ph_player")
    scope = c[1].radio("Show", ["Every slate the app projected", "Only my entries"], key="ph_scope",
                       horizontal=True)
    if name == "—":
        st.caption("Pick a player to see projected vs. actual points, ownership and your results with him.")
        return
    summary, table = ph.search(pw, e, name, mine_only=scope == "Only my entries")
    m = st.columns(3)
    m[0].metric("Slates projected", summary["slates"])
    avg_p, avg_a = summary["avg_projected"], summary["avg_actual"]
    m[1].metric("Avg projected → actual", "—" if avg_p is None else
                f"{avg_p:.1f} → {'—' if avg_a is None else f'{avg_a:.1f}'}")
    m[2].metric("In my lineups", summary["times_played"])
    if table.empty:
        st.caption(f"You haven't played {name} yet.")
    else:
        st.dataframe(ui.styled_player_history(table), hide_index=True, width="stretch")


def _box_score(row, pw: pd.DataFrame) -> None:
    ids = [int(x) for x in str(row["players"]).split(",") if x]
    week = pw[(pw["slate_date"] == row["slate_date"]) & pw["dk_id"].isin(ids)]
    if week.empty:
        st.caption("Player details appear once this slate's history is available.")
        return
    t = pd.DataFrame({"Pos": week["position"], "Player": week["name"], "Team": week["team"],
                      "Salary": week["salary"], "Projected": week["median"], "Actual": week["actual_pts"],
                      "+/−": week["actual_pts"] - week["median"], "Own est.": week["own_pct"],
                      "Own actual": week["actual_own"]})
    st.dataframe(t.style.format({"Salary": "${:,.0f}", "Projected": "{:.1f}", "Actual": "{:.1f}", "+/−": "{:+.1f}",
                                 "Own est.": "{:.0f}%", "Own actual": "{:.0f}%"}, na_rep="—"),
                 hide_index=True, width="stretch")


def _entry(row, pw: pd.DataFrame, hosted: bool) -> None:
    won, fee = row["winnings"], row["entry_fee"]
    icon = "💲" if pd.isna(won) else ("✅" if won > 0 else "✗")
    name = row["contest_name"] or f"Contest {row['contest_id'] or ''}".strip()
    with st.expander(f"{icon} {row['slate_date']} · {name} · Classic · {ent.type_label(row['contest_type'])}"):
        money = ("Fee " + (ui.money(fee) if not pd.isna(fee) else "—") + " → "
                 + ("winnings not entered yet" if pd.isna(won) else f"Won {ui.money(won)} "
                    f"({ui.signed_money(won - (0 if pd.isna(fee) else fee))})"))
        place = "" if pd.isna(row["place"]) else f" · {int(row['place']):,} of {int(row['field_size']):,}"
        score = ("" if pd.isna(row["points"]) else f" · Actual {row['points']:.1f}"
                 + ("" if pd.isna(row["projected"]) else
                    f" vs projected {row['projected']:.1f} ({row['points'] - row['projected']:+.1f})"))
        st.markdown(money.replace("$", "\\$") + place + score)
        st.caption(f"Lineup: {row['lineup_source']}")
        _box_score(row, pw)
        if hosted:
            st.caption("Edit on your Mac.")
            return
        eid = row["entry_id"]
        c = st.columns(4)
        new_fee = c[0].number_input("Entry fee ($)", min_value=0.0, step=1.0, key=f"fee_{eid}",
                                    value=0.0 if pd.isna(fee) else float(fee))
        new_won = c[1].number_input("Winnings ($)", min_value=0.0, step=1.0, key=f"win_{eid}",
                                    value=0.0 if pd.isna(won) else float(won))
        keys = list(CONTEST_TYPES)
        new_type = c[2].selectbox("Contest type", keys, format_func=ent.type_label, key=f"type_{eid}",
                                  index=keys.index(row["contest_type"]) if row["contest_type"] in keys else 0)
        c[3].write("")
        if c[3].button("Save", key=f"save_{eid}"):
            st.session_state.flash = actions.save_entry_edit(eid, entry_fee=float(new_fee), winnings=float(new_won),
                                                             contest_type=new_type)
            st.rerun()


def render(d, hosted: bool) -> None:
    e, pw = d.entries, d.player_weeks
    seasons = sorted({str(s)[:4] for s in e["slate_date"]} | {str(dt.date.today().year)}, reverse=True)
    if e.empty:
        st.info("No entries yet. After a contest ends, export its standings from DraftKings (📥 in the sidebar) "
                "and your entries appear here." + ("" if hosted else " You can also add one by hand below."))
    season = st.session_state.get("res_season", seasons[0])
    _totals(filter_entries(e, season, "all", "All lineups") if len(e) else e)
    c = st.columns([1, 2, 2, 2], vertical_alignment="bottom")
    season = c[0].selectbox("Season", seasons, key="res_season")
    type_keys = ["all"] + list(CONTEST_TYPES)
    type_key = c[1].selectbox("Contest type", type_keys, key="res_type",
                              format_func=lambda k: "All types" if k == "all" else ent.type_label(k))
    source = c[2].selectbox("Lineup source", SOURCES, key="res_source")
    if not hosted:
        with c[3]:
            _add_form()
    _player_history(pw, e)
    st.subheader("Entries")
    shown = filter_entries(e, season, type_key, source) if len(e) else e
    if len(e) and shown.empty:
        st.caption("No entries match these filters.")
    for _, row in shown.sort_values(["slate_date", "place"], ascending=[False, True]).iterrows():
        _entry(row, pw, hosted)
