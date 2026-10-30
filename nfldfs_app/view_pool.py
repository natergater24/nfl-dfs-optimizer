"""🔁 Tweak & Rebuild tab: lock or exclude players, rebuild the lineup, and browse every playable player."""
from __future__ import annotations

import streamlit as st

from nfldfs import lineups
from nfldfs.config import CONTEST_TYPES
from nfldfs.dk_rules import ROSTER_SLOTS, assign_slots
from nfldfs.optimizer import InfeasibleError
from nfldfs_app import ui
from nfldfs_app.scoring import device_backups

SORTS = {"Median": "median", "Ceiling": "ceiling", "Boom %": "boom_rate", "Value (pts/$1K)": "value",
         "Ownership": "own_pct", "Salary": "salary"}
POSITIONS = ["QB", "RB", "WR", "TE", "DST"]
INJURED_ONLY = "🩹 Injured / questionable only"


def pool_view(pool, positions, tiers, sort_label, injured_only=False):
    """Playable players by position/tier, sorted; with injured_only, every tagged player (any tag) instead."""
    keep = (pool["inj_tag"].fillna("").astype(str) != "") if injured_only and ui.has_injury_data(pool) \
        else pool["playable"].astype(bool)
    v = pool[keep & pool["position"].isin(positions) & pool["tier"].isin(tiers)].copy()
    v["value"] = v["median"] / (v["salary"] / 1000)
    return v.sort_values(SORTS[sort_label], ascending=False, kind="stable").reset_index(drop=True)


def rebuild(d, key, locks, excludes):
    rows, metric = lineups.best_lineup(d.pool, d.sims, d.field, CONTEST_TYPES[key], locks=locks, excludes=excludes)
    lu = d.pool.iloc[rows]
    order = assign_slots(lu)
    lu = lu.set_index("dk_id").loc[order].reset_index()
    lu.insert(0, "slot", list(ROSTER_SLOTS))
    return lu, metric


def player_label(r) -> str:
    chip = ui.row_chip_text(r)
    return f"{r['name']} · {r.position} · {r.team} · {ui.money(r.salary)}" + (f" · {chip}" if chip else "")


def lock_options(pool) -> dict:
    """🔒 choices: every player when the build has injury tags (Nathan's locks win, with ⚠); else playable ones."""
    allowed = pool if ui.has_injury_data(pool) else pool[pool["playable"]]
    return {player_label(r): int(r.dk_id) for _, r in allowed.sort_values("salary", ascending=False).iterrows()}


def _send_to_mine(new_ids, slot=None) -> None:
    st.session_state.my_ids = list(new_ids)
    st.session_state.flash = (True, "Copied into 🛠 My Lineup" if slot is None else "Backup copied into 🛠 My Lineup")
    st.rerun()                          # the 🛠 tab rendered earlier this run; redraw it with the new ids


def render(d, key, label, field_scores):
    st.caption(f"Don't like someone in the recommended {label} lineup (an injury, a hunch)? Exclude that player, or lock in "
               "a player you want, then rebuild. The app re-picks the other spots around your choices.")
    play = d.pool[d.pool["playable"]].sort_values("salary", ascending=False)
    names = {player_label(r): int(r.dk_id) for _, r in play.iterrows()}
    lock_names = lock_options(d.pool)
    c = st.columns(2)
    locks = [lock_names[n] for n in c[0].multiselect("🔒 Lock players (must be in the lineup)", list(lock_names),
                                                     key="pool_locks")]
    excl = [names[n] for n in c[1].multiselect("✖ Exclude players", list(names), key="pool_excludes")]
    if st.button(f"🔁 Rebuild {label} lineup with my locks", disabled=not (locks or excl), key="pool_rebuild"):
        try:
            with st.spinner("Building…"):
                lu, metric = rebuild(d, key, locks, excl)
            st.session_state.rebuilt = {"key": key, "ids": lu.dk_id.astype(int).tolist(), "metric": metric,
                                        "warnings": ui.injury_warnings(d.pool, locks)}
        except InfeasibleError as e:
            st.error(str(e))
    rb = st.session_state.get("rebuilt")
    if rb and any(int(i) not in d.row_of for i in rb["ids"]):    # stale after a new slate was built
        st.session_state.pop("rebuilt", None)
        rb = None
    if rb and rb["key"] == key:
        lu = d.pool.set_index("dk_id").loc[rb["ids"]].reset_index()
        lu.insert(0, "slot", list(ROSTER_SLOTS))
        st.markdown(f"**Rebuilt lineup** — {ui.metric_phrase(key, CONTEST_TYPES[key]['group']).lower()} in "
                    f"{rb['metric']:.0%} of sims")
        for w in rb.get("warnings", []):
            st.warning(w)
        st.dataframe(ui.styled_lineup(lu), hide_index=True, width="stretch")
        if ui.has_injury_data(d.pool):
            ui.injury_watch(d.pool, rb["ids"], device_backups(d, rb["ids"], key, field_scores)
                            if ui.tagged_ids(d.pool, rb["ids"]) else None, "rebuilt", _send_to_mine)
        if st.button("Send to 🛠 My Lineup", key="pool_send"):
            _send_to_mine(rb["ids"])

    st.subheader("All players")
    f = st.columns(3)
    pos = f[0].multiselect("Position", POSITIONS, default=POSITIONS, key="pool_pos")
    tiers = f[1].multiselect("Ownership tier", list(ui.TIER_ICON), default=list(ui.TIER_ICON), key="pool_tiers")
    sort = f[2].selectbox("Sort by", list(SORTS), key="pool_sort")
    hurt = ui.has_injury_data(d.pool) and st.checkbox(INJURED_ONLY, key="pool_injured")
    st.dataframe(ui.styled_pool(pool_view(d.pool, pos, tiers, sort, hurt)), hide_index=True, width="stretch",
                 height=480)
