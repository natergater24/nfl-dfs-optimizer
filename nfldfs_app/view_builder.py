"""🛠 My Lineup tab: live totals, the interactive builder component, export."""
from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from nfldfs.config import CONTEST_TYPES, SALARY_CAP
from nfldfs.dk_rules import ROSTER_SLOTS, upload_csv_text, validate_lineup
from nfldfs_app import actions, data, ui
from nfldfs_app.scoring import device_backups, published_metric

BUILDER_FIELDS = ["dk_id", "name", "position", "team", "opp", "salary", "median", "ceiling", "own_pct", "tier",
                  "score", "value", "mu_color", "mu_text", "mu_label", "out", "inj", "inj_color", "inj_fg",
                  "inj_title"]
SLOT_ELIG = {"QB": ["QB"], "RB": ["RB"], "WR": ["WR"], "TE": ["TE"], "FLEX": ["RB", "WR", "TE"], "DST": ["DST"]}
_SLOT_ORDER = list(dict.fromkeys(ROSTER_SLOTS))


def player_slots(position: str) -> list[str]:
    """The roster slots an NFL player of this position may fill (FLEX takes RB/WR/TE)."""
    return [s for s in _SLOT_ORDER if position in SLOT_ELIG[s]]


def builder_records(pool: pd.DataFrame, weights: dict, lineup_ids=()) -> list[dict]:
    keep = {int(i) for i in lineup_ids if i is not None}
    play = pool[pool["playable"] | pool["dk_id"].isin(keep)].copy()
    play["out"] = ~play["playable"].astype(bool)
    play["score"] = (weights.get("floor", 0) * play["floor"] + weights.get("median", 0) * play["median"]
                     + weights.get("ceiling", 0) * play["ceiling"] - weights.get("own_penalty", 0) * play["own_pct"])
    play["value"] = play["median"] / (play["salary"] / 1000)
    add_injury_fields(play)
    recs = play[BUILDER_FIELDS].round(3).to_dict("records")
    for r in recs:
        r["dk_id"], r["salary"] = int(r["dk_id"]), int(r["salary"])
        r["slots"] = player_slots(r["position"])
    return recs


def add_injury_fields(play: pd.DataFrame) -> None:
    """Builder-card tag fields (shared with the 🏀 page): chip text, colors and the news tooltip."""
    if ui.has_injury_data(play):
        tags = play["inj_tag"].fillna("").astype(str).str.upper()
        play["inj"] = [ui.chip_text(t, ln) for t, ln in zip(tags, play["lean"].fillna(""))]
        play["inj_color"] = [ui.CHIP_STYLE.get(t, ui._OTHER_TAG)[0] if t else "" for t in tags]
        play["inj_fg"] = [ui.CHIP_STYLE.get(t, ui._OTHER_TAG)[1] if t else "" for t in tags]
        play["inj_title"] = [ui.news_tooltip(r) for _, r in play.iterrows()]
    else:
        play["inj"] = play["inj_color"] = play["inj_fg"] = play["inj_title"] = ""


def apply_builder_value(value, seen, current):
    """The component reports its whole lineup; apply it only when it is a new user action."""
    if not value or value == seen:
        return None, seen
    new = [None if v is None else int(v) for v in value["ids"]]
    return (new if new != list(current) else None), value


def lineup_status(ids, pool: pd.DataFrame) -> dict:
    by = pool.set_index("dk_id")
    picked = [int(i) for i in ids if i is not None]
    gone = [i for i in picked if i not in by.index]
    known = [i for i in picked if i in by.index]
    tagged = ui.has_injury_data(pool)
    # Builds with injury tags: Nathan's own picks win whatever the tag (⚠ + a backup below). Older builds: an
    # unplayable player still blocks the export.
    out = [] if tagged else [by.at[i, "name"] for i in known if not bool(by.at[i, "playable"])]
    used = int(by.loc[known, "salary"].sum()) if known else 0
    dupes = len(set(picked)) != len(picked)
    messages = [f"⚠ {n} is now ruled out — swap him before lock." for n in out]
    messages += ui.pick_warnings(pool, known)
    if gone:
        messages.append("⚠ A player in this lineup is no longer on the slate — swap him.")
    if dupes:
        messages.append("⚠ The same player is in two slots.")
    if used > SALARY_CAP:
        messages.append(f"Over the cap by {ui.money(used - SALARY_CAP)} — export disabled.")
    if len(picked) < 9:
        messages.append(f"{9 - len(picked)} slot(s) still empty.")
    valid = (len(picked) == 9 and not gone and not out and not dupes
             and validate_lineup(by.loc[known].reset_index()) == [])
    return {"picked": picked, "used": used, "valid": valid, "messages": messages}


def _apply_mine(new_ids, slot) -> None:
    st.session_state.my_ids = new_ids
    st.session_state.focus_slot = slot
    st.session_state.focus_token = st.session_state.get("focus_token", 0) + 1
    st.session_state.flash = (True, "Backup applied to 🛠 My Lineup")
    st.rerun()


def render(d, key, label, field_scores):
    contest = CONTEST_TYPES[key]
    keys = list(CONTEST_TYPES)
    labels = [CONTEST_TYPES[k]["label"] for k in keys]
    rec_of = lambda k: d.lineups[(d.lineups.contest_key == k) & (d.lineups["rank"] == 0)].dk_id.astype(int).tolist()
    rec_ids = rec_of(key)
    if "my_ids" not in st.session_state:
        st.session_state.my_ids = rec_ids

    t = st.columns([3, 1, 4], vertical_alignment="bottom")
    start = t[0].selectbox("Start from", ["Blank lineup"] + labels, index=1 + keys.index(key), key="builder_start")
    if t[1].button("Load", width="stretch", key="builder_load"):
        st.session_state.my_ids = [None] * 9 if start == "Blank lineup" else rec_of(keys[labels.index(start)])
        st.session_state.pop("focus_slot", None)
        st.rerun()

    ids = list(st.session_state.my_ids)
    status = lineup_status(ids, d.pool)
    by = d.pool.set_index("dk_id")
    known = [i for i in status["picked"] if i in by.index]
    used = status["used"]
    m = st.columns(4)
    m[0].metric("Salary used", ui.money(used),
                f"{ui.money(SALARY_CAP - used)} left" if used <= SALARY_CAP else f"-{ui.money(used - SALARY_CAP)} over",
                delta_color="normal")
    m[1].metric("Projected median", f"{by.loc[known, 'median'].sum():.1f}")
    m[2].metric("Ceiling (p85 sum)", f"{by.loc[known, 'ceiling'].sum():.1f}")
    if status["valid"]:
        mine = published_metric(d, status["picked"], key, field_scores)
        recm = published_metric(d, rec_ids, key, field_scores)
        m[3].metric(f"{ui.metric_phrase(key, contest['group'])} in", f"{mine:.0%} of sims", f"recommended: {recm:.0%}",
                    delta_color="off", help=ui.MODEL_RELATIVE_HELP)
    for msg in status["messages"]:
        (st.error if msg.startswith("⚠") or msg.startswith("Over the cap") else st.info)(msg)
    st.caption(f"“Recommended” ranking = best fit for **{label}**. Click a slot then a player (or a player then a "
               "slot), or drag a player onto a slot. Gray = not eligible. Esc clears a selection.")

    value = None
    if os.environ.get("NFLDFS_NO_COMPONENT") == "1":
        st.info("Interactive builder is off in test mode.")
    else:
        from nfldfs_app.builder_component import lineup_builder
        res = lineup_builder(key="builder", on_lineup_change=lambda: None, data={
            "pool": builder_records(d.pool, contest["weights"], ids), "lineup": ids, "slots": list(ROSTER_SLOTS), "slot_elig": SLOT_ELIG, "ns": "nfl",
            "cap": SALARY_CAP, "focus_slot": st.session_state.get("focus_slot"),
            "focus_token": st.session_state.get("focus_token")})
        value = getattr(res, "lineup", None)
    new, st.session_state.lb_seen = apply_builder_value(value, st.session_state.get("lb_seen"), ids)
    if new is not None:
        st.session_state.my_ids = new
        st.rerun()

    if ui.has_injury_data(d.pool) and status["valid"]:
        ui.injury_watch(d.pool, ids, device_backups(d, ids, key, field_scores) if ui.tagged_ids(d.pool, ids) else None,
                        "mine", _apply_mine)

    csv = upload_csv_text([by.loc[status["picked"]].reset_index()]) if status["valid"] else ""
    hosted = data.is_hosted()
    st.download_button("⬇ Download My Lineup (DraftKings CSV)", csv, file_name="dk_classic_my_lineup.csv",
                       mime="text/csv", disabled=not status["valid"], key="dl_mine",
                       on_click=None if hosted else actions.record_my_build,
                       args=None if hosted else (status["picked"], d.meta.get("slate_date", "")))
    if status["valid"]:
        with st.expander("Side by side with the recommended lineup"):
            rec = d.lineups[(d.lineups.contest_key == key) & (d.lineups["rank"] == 0)].reset_index(drop=True)
            mine = by.loc[status["picked"]].reset_index()
            st.dataframe(pd.DataFrame({
                "Pos": rec["slot"], "Recommended": rec["name"], "Salary": rec["salary"].map(ui.money),
                "Median": rec["median"].round(1), "My pick": mine["name"], "My salary": mine["salary"].map(ui.money),
                "My median": mine["median"].round(1)}), hide_index=True, width="stretch")
