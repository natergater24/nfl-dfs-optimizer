"""🏀 NBA page: sidebar, header, slate picker and the ⭐ Recommended / 🛠 My Lineup / 🔁 Tweak & Rebuild /
📒 My Results tabs. Session-state keys all start with `nba_` so they never collide with the NFL page."""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from nbadfs import lineups as nba_lineups
from nbadfs.config import NBA_CONTEST_TYPES, SALARY_CAP
from nbadfs.optimizer import InfeasibleError
from nbadfs.rules import ROSTER_SLOTS, SLOT_POSITIONS, upload_csv_text, validate_lineup
from nbadfs_app import data
from nfldfs.sim_eval import contest_metric, lineup_scores
from nfldfs_app import actions, ui
from nfldfs_app import data as app_data
from nfldfs_app.view_builder import add_injury_fields, apply_builder_value

POSITIONS = ["PG", "SG", "SF", "PF", "C"]
SLOT_ELIG = {s: [p for p in POSITIONS if p in SLOT_POSITIONS[s]] for s in ROSTER_SLOTS}
N_SLOTS = len(ROSTER_SLOTS)
BUILDS_ET = ((14, 0), (18, 30))              # mirrors scripts/launchagents nba_afternoon / nba_evening
REBUILD_CANDIDATES = nba_lineups.REBUILD_CANDIDATES
SIMS_HELP = "Share of simulated nights where this happens — for comparing lineups, not real-world odds."
NOT_BUILT_HOSTED = " — the Mac publishes them at 2:00 PM and 6:30 PM ET."
SORTS = {"Median": "median", "Ceiling": "ceiling", "Value (pts/$1K)": "value", "Ownership": "own_pct",
         "Salary": "salary"}
BUILDER_FIELDS = ["dk_id", "name", "position", "team", "opp", "salary", "median", "ceiling", "own_pct", "tier",
                  "score", "value", "mu_color", "mu_text", "mu_label", "out", "slots", "inj", "inj_color", "inj_fg",
                  "inj_title"]
INJURED_ONLY = "🩹 Injured / questionable only"


# ── helpers (pure, tested) ──────────────────────────────────────────────────────────────────────────────

def next_build(now_et: dt.datetime) -> dt.datetime:
    """The next automatic NBA build (daily 2:00 PM and 6:30 PM ET) strictly after now."""
    day = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    for add in (0, 1):
        for h, m in BUILDS_ET:
            cand = (day + dt.timedelta(days=add)).replace(hour=h, minute=m)
            if cand > now_et:
                return cand
    raise AssertionError("unreachable")


KEY_MARKDOWN = (
    "**Game style:** DraftKings NBA **Classic** only — PG, SG, SF, PF, C, G (PG/SG), F (SF/PF), UTIL; "
    "\\$50,000 cap; players from at least 2 games.\n\n"
    "**Ownership** — share of the field expected to play him\n"
    "- 🔥 **Chalk** 25%+ · safe, but no edge\n"
    "- **Popular** 10–25%\n"
    "- **Moderate** 5–10%\n"
    "- 💎 **Contrarian** under 5% · if he hits, you pass most of the field\n\n"
    "_Cash games: lean Chalk. Tournaments: mix in Moderate/Contrarian._")


def player_label(row, dk_id=None) -> str:
    if "inj_tag" in row.index:
        chip = ui.row_chip_text(row)
        out = f" · {chip}" if chip else ""
    else:                                          # builds made before injury tags
        out = "" if bool(row["playable"]) else " · OUT"
    return f"{row['name']} · {row['positions']} · {row['team']} · {ui.money(row['salary'])}{out}"


def delta_text(delta: float) -> str:
    v = round(float(delta) * 100, 1) + 0.0         # round first: a tiny negative must not read "−0.0"
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.1f} pts"


def lineup_table(df: pd.DataFrame):
    view = pd.DataFrame({
        "Slot": df["slot"].to_numpy(), "Player": ui.names_with_chips(df), "Team": df["team"].to_numpy(),
        "Salary": df["salary"].to_numpy(), "Median": df["median"].to_numpy(), "Floor": df["floor"].to_numpy(),
        "Ceiling": df["ceiling"].to_numpy(), "Own %": df["own_pct"].to_numpy(),
        "Tier": df["tier"].map(ui.TIER_ICON).to_numpy()})
    return view.style.format({"Salary": "${:,.0f}", "Median": "{:.1f}", "Floor": "{:.1f}", "Ceiling": "{:.1f}",
                              "Own %": "{:.0f}%"})


def pool_table(df: pd.DataFrame):
    view = pd.DataFrame({
        "Player": ui.names_with_chips(df), "Pos": df["positions"].to_numpy(), "Team": df["team"].to_numpy(),
        "Opp": df["opp"].to_numpy(), "Salary": df["salary"].to_numpy(), "Median": df["median"].to_numpy(),
        "Floor": df["floor"].to_numpy(), "Ceiling": df["ceiling"].to_numpy(), "Pts/$1K": df["value"].to_numpy(),
        "Own %": df["own_pct"].to_numpy(), "Tier": df["tier"].map(ui.TIER_ICON).to_numpy()})
    if ui.has_injury_data(df):
        view["News"] = [ui.news_text(r) for _, r in df.iterrows()]
    else:
        view["Status"] = df["status"].fillna("").to_numpy()
    return view.style.format({"Salary": "${:,.0f}", "Median": "{:.1f}", "Floor": "{:.1f}", "Ceiling": "{:.1f}",
                              "Pts/$1K": "{:.2f}", "Own %": "{:.1f}%"})


def pool_view(pool, positions, tiers, sort_label, injured_only=False):
    """Playable players by position/tier, sorted; with injured_only, every tagged player (any tag) instead."""
    has_pos = pool["positions"].map(lambda s: bool(set(str(s).split("/")) & set(positions)))
    keep = (pool["inj_tag"].fillna("").astype(str) != "") if injured_only and ui.has_injury_data(pool) \
        else pool["playable"].astype(bool)
    v = pool[keep & has_pos & pool["tier"].isin(tiers)].copy()
    v["value"] = v["median"] / (v["salary"] / 1000)
    return v.sort_values(SORTS[sort_label], ascending=False, kind="stable").reset_index(drop=True)


def builder_records(pool: pd.DataFrame, weights: dict, lineup_ids=()) -> list[dict]:
    keep = {int(i) for i in lineup_ids if i is not None}
    play = pool[pool["playable"].astype(bool) | pool["dk_id"].isin(keep)].copy()
    play["out"] = ~play["playable"].astype(bool)
    play["position"] = play["positions"]
    play["score"] = (weights.get("floor", 0) * play["floor"] + weights.get("median", 0) * play["median"]
                     + weights.get("ceiling", 0) * play["ceiling"] - weights.get("own_penalty", 0) * play["own_pct"])
    play["value"] = play["median"] / (play["salary"] / 1000)
    play["mu_label"] = play["implied_total"].map(lambda v: f"{v:.0f} implied")
    play["mu_color"] = "#5b6770"
    play["mu_text"] = ["Team implied total (league average — no Vegas line yet)" if m else "Team implied total (Vegas)"
                       for m in play["line_missing"].astype(bool)]
    play["slots"] = [list(s) for s in play["slots"]]
    add_injury_fields(play)
    recs = play[BUILDER_FIELDS].round(3).to_dict("records")
    for r in recs:
        r["dk_id"], r["salary"], r["out"] = int(r["dk_id"]), int(r["salary"]), bool(r["out"])
    return recs


def lineup_status(ids, pool: pd.DataFrame) -> dict:
    by = pool.set_index("dk_id")
    picked = [int(i) for i in ids if i is not None]
    gone = [i for i in picked if i not in by.index]
    known = [i for i in picked if i in by.index]
    # Builds with injury tags: Nathan's own picks win whatever the tag (⚠ + a backup in 🩹 Injury watch).
    # Older builds: an unplayable player still blocks the export.
    out = [] if ui.has_injury_data(pool) else [by.at[i, "name"] for i in known if not bool(by.at[i, "playable"])]
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
    if len(picked) < N_SLOTS:
        messages.append(f"{N_SLOTS - len(picked)} slot(s) still empty.")
    rule_errors = []
    if len(picked) == N_SLOTS and not gone and not dupes:
        rule_errors = [e for e in validate_lineup(by.loc[picked].reset_index(), list(ROSTER_SLOTS))
                       if not e.startswith("Salary")]
        messages += [f"⚠ {e}." for e in rule_errors]
    valid = len(picked) == N_SLOTS and not gone and not out and not dupes and used <= SALARY_CAP and not rule_errors
    return {"picked": picked, "used": used, "valid": valid, "messages": messages}


def lineup_metric(sd: data.SlateData, ids, key: str) -> float:
    rows = [sd.row_of[int(i)] for i in ids]
    sims = data.sims_for(sd)
    return float(contest_metric(lineup_scores(sims, [rows]), data.field_scores_for(sd),
                                NBA_CONTEST_TYPES[key]["metric"])[0])


def device_backups(sd: data.SlateData, ids, key: str) -> pd.DataFrame:
    """nbadfs.lineups.injury_backups for any full lineup (dk_ids in ROSTER_SLOTS order), computed on this device."""
    from nfldfs.lineups import BACKUP_COLUMNS
    picked = [int(i) for i in ids if i is not None]
    if len(picked) != N_SLOTS or len(set(picked)) != N_SLOTS or any(i not in sd.row_of for i in picked):
        return pd.DataFrame(columns=BACKUP_COLUMNS)
    stamp = ("nba", sd.dg, str(sd.meta.get("built_at_utc", "")), key, tuple(picked))
    return ui.remembered(stamp, lambda: nba_lineups.injury_backups(sd.pool, data.sims_for(sd), data.field_scores_for(sd),
                                                                   picked, NBA_CONTEST_TYPES[key]))


def _watch(sd: data.SlateData, ids, key: str, prefix: str, on_apply, published: bool = False) -> None:
    """🩹 Injury watch for a lineup: the published backups for the published rank-0 lineup, else on-device ones."""
    if not ui.has_injury_data(sd.pool):
        return
    tagged = ui.tagged_ids(sd.pool, ids)
    bk = None
    if tagged:
        compute = lambda: device_backups(sd, ids, key)      # noqa: E731
        bk = ui.pick_backups(sd.backups, key, tagged, compute) if published else compute()
    ui.injury_watch(sd.pool, ids, bk, prefix, on_apply)


def _to_my_lineup(new_ids, slot, what="Backup") -> None:
    st.session_state.nba_my_ids = list(new_ids)
    st.session_state.nba_focus_slot = slot
    st.session_state.nba_focus_token = st.session_state.get("nba_focus_token", 0) + 1
    st.toast(f"{what} copied into 🛠 My Lineup — open that tab.")


def _apply_mine(new_ids, slot) -> None:
    _to_my_lineup(new_ids, slot)
    st.session_state.nba_flash = (True, "Backup applied to 🛠 My Lineup")
    st.rerun()


def _send_rebuilt(new_ids, slot=None) -> None:
    st.session_state.nba_my_ids = list(new_ids)
    st.session_state.nba_flash = (True, "Copied into 🛠 My Lineup" if slot is None else "Backup copied into 🛠 My Lineup")
    st.rerun()


def rebuild(sd: data.SlateData, key: str, locks, excludes, n_candidates: int | None = None):
    """(dk_ids in slot order, contest metric, ⚠ warnings for locked Out players)."""
    ids, metric = nba_lineups.best_lineup(sd.pool, data.sims_for(sd), sd.field, NBA_CONTEST_TYPES[key],
                                          locks=locks, excludes=excludes,
                                          n_candidates=n_candidates or REBUILD_CANDIDATES)
    return [int(i) for i in ids], metric, nba_lineups.out_lock_warnings(sd.pool, locks)


def _slotted(sd: data.SlateData, ids) -> pd.DataFrame:
    lu = sd.pool.set_index("dk_id").loc[[int(i) for i in ids]].reset_index()
    lu.insert(0, "slot", list(ROSTER_SLOTS))
    return lu


def _rec(sd, key, rank=0) -> pd.DataFrame:
    return sd.lineups[(sd.lineups.contest_key == key) & (sd.lineups["rank"] == rank)].reset_index(drop=True)


def _phrase(key: str) -> str:
    return ui.metric_phrase(key, NBA_CONTEST_TYPES[key]["group"])


# ── page ────────────────────────────────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False, max_entries=6)
def _load(nba_dir: str, dg: int, stamp: tuple) -> data.SlateData:
    return data.load_slate(Path(nba_dir), dg)


def _sidebar(hosted: bool) -> None:
    with st.sidebar:
        st.markdown("### 🏀 NBA DFS")
        if hosted:
            if st.button("🔄 Get latest", width="stretch", key="nba_get_latest",
                         help="Loads the newest NBA lineups your Mac has published."):
                st.session_state.nba_get_latest_pending = True
                st.cache_resource.clear()
                st.rerun()
            st.caption("Hosted copy — the Mac builds NBA lineups at 2:00 PM and 6:30 PM ET and publishes them here.")
        elif st.button("⟳ Refresh NBA now", width="stretch", key="nba_refresh",
                       help="Re-fetch today's DraftKings slates, injuries and lines, then rebuild (about a minute)"):
            with st.spinner("Refreshing NBA — about a minute…"):
                st.session_state.nba_flash = actions.stage_flash("nba", actions.run_stage("nba"))
            st.cache_resource.clear()
            st.rerun()


def _status_messages(run_status: dict, hosted: bool) -> None:
    failed = [s for s in run_status.get("steps", []) if s.get("ok") is False]
    if failed:
        st.error(f"⚠ The last NBA run failed at **{failed[0].get('name', 'a step')}**: {failed[0].get('message', '')}")
    for step in run_status.get("steps", []):
        if "WARNING" in str(step.get("message", "")):
            st.warning(f"⚠ {step.get('name', '')}: {step['message']}")
    if not hosted and str(run_status.get("publish", "")).startswith("WARNING"):
        st.warning(f"The phone copy may be out of date: {run_status['publish']}")


def render() -> None:
    hosted = app_data.is_hosted()
    nba_dir = data.published_dir()
    slates = data.load_slates(nba_dir)
    run_status = data.load_run_status(nba_dir)
    _sidebar(hosted)

    flash = st.session_state.pop("nba_flash", None)
    if flash:
        (st.error if not flash[0] else st.warning if "WARNING" in flash[1] else st.success)(flash[1])
        if len(flash) > 2 and flash[2]:
            st.code(flash[2])
    st.title("NBA DFS Lineups")
    now = dt.datetime.now(ui.EASTERN)
    published = [s for s in (slates or []) if s.get("published")]
    if not published:
        if slates == []:
            st.info("No NBA slate today — DraftKings has no NBA Classic contests. Check back on the next game day.")
        else:
            st.warning("No NBA lineups built yet" + (NOT_BUILT_HOSTED if hosted
                                                     else " — click ⟳ Refresh NBA now in the sidebar."))
        _status_messages(run_status, hosted)
        st.caption(f"Next automatic build: {ui.format_refresh(next_build(now))}")
        return

    labels = [data.slate_label(s) for s in published]
    choice = st.radio("Slate", labels, index=data.default_slate(published, now), horizontal=True, key="nba_slate")
    slate = published[labels.index(choice)]
    dg = int(slate["draft_group_id"])
    st.session_state.nba_dg = dg
    sd = _load(str(nba_dir), dg, data.slate_stamp(nba_dir, dg))

    built = sd.meta.get("built_at_utc")
    refreshed = ui.to_eastern(built)
    if st.session_state.pop("nba_get_latest_pending", False):
        st.success("Up to date — NBA lineups last refreshed "
                   + (ui.format_refresh(refreshed) if refreshed else "(time unknown)"))
    text, color = ui.updated_text(app_data.minutes_since(built))
    when = f"**Last refreshed: {ui.format_refresh(refreshed)}**" if refreshed else "**Last refreshed: unknown**"
    st.markdown(f"{when} · :{color}[{text.removeprefix('Updated ')}] · next automatic build: "
                f"{ui.format_refresh(next_build(now))}")
    start = ui.to_eastern(slate.get("start"))
    if start is not None and start.date() < now.date():
        st.warning(f"These are {start:%a %b} {start.day}'s slates — today's haven't been built yet.")
    if hosted:
        st.info("📱 This is the hosted copy — view lineups, build variations and download CSVs. Refreshing happens "
                "on your Mac and publishes here automatically.")
    _status_messages(run_status, hosted)

    ctl = {c["label"]: k for k, c in NBA_CONTEST_TYPES.items()}
    label = st.selectbox("Classic contest type", list(ctl), index=list(ctl.values()).index("single_entry"),
                         key="nba_contest_label")
    key = ctl[label]
    st.session_state.nba_contest_key = key

    if st.session_state.get("nba_my_dg") != dg:          # a new slate (or a new day): start My Lineup over
        st.session_state.nba_my_ids = _rec(sd, key).dk_id.astype(int).tolist()
        st.session_state.nba_my_dg = dg
        st.session_state.pop("nba_rebuilt", None)
        st.session_state.pop("nba_focus_slot", None)

    with st.sidebar:
        st.caption(f"{slate.get('name', '')}: {sd.meta.get('games', '?')} games · {sd.meta.get('n_sims', 0):,} sims · "
                   f"name match {sd.meta.get('stats_match_rate', 0):.0%} · "
                   f"Odds API left: {sd.meta.get('odds_remaining', '?')}")
        with st.popover("ℹ️ Key", width="stretch"):
            st.markdown(KEY_MARKDOWN)

    tabs = st.tabs(["⭐ Recommended", "🛠 My Lineup", "🔁 Tweak & Rebuild", "📒 My Results"])
    with tabs[0]:
        _recommended(sd, key)
    with tabs[1]:
        _my_lineup(sd, key, label)
    with tabs[2]:
        _tweak(sd, key, label)
    with tabs[3]:
        st.caption("NBA results arrive in phase 3.")


def _metrics(cols, total, median, ceiling):
    cols[0].metric("Salary used", ui.money(total),
                   f"{ui.money(SALARY_CAP - total)} left" if total <= SALARY_CAP
                   else f"-{ui.money(total - SALARY_CAP)} over", delta_color="off")
    cols[1].metric("Projected median", f"{median:.1f}")
    cols[2].metric("Ceiling (p85 sum)", f"{ceiling:.1f}")


SIMS_DIFFER = ("Simulations on this device differ slightly from the Mac's build; percentages may differ a little.")


def _sims_note(sd: data.SlateData) -> None:
    if data.sims_mismatch(sd):
        st.caption(SIMS_DIFFER)


def _recommended(sd: data.SlateData, key: str) -> None:
    rec = _rec(sd, key)
    if rec.empty:
        st.info("No lineup was built for this contest type.")
        return
    ids = rec.dk_id.astype(int).tolist()
    m = st.columns(4)
    _metrics(m, int(rec.salary.sum()), rec["median"].sum(), rec["ceiling"].sum())
    m[3].metric(f"{_phrase(key)} in", f"{float(rec.metric.iloc[0]):.0%} of sims", help=SIMS_HELP)
    st.dataframe(lineup_table(rec), hide_index=True, width="stretch")
    hover = ui.hover_names_html(rec)
    if hover:
        st.markdown(hover, unsafe_allow_html=True)
    st.caption(f"{rec.game.nunique()} games · teams: {', '.join(sorted(rec.team.unique()))}")
    _watch(sd, ids, key, f"nba_rec_{key}", _to_my_lineup, published=True)
    st.download_button("⬇ Download for DraftKings", upload_csv_text([ids]), file_name=f"dk_nba_classic_{key}.csv",
                       mime="text/csv", key=f"nba_dl_{key}")

    with st.expander("Alternates (#2 and #3)"):
        for r in (1, 2):
            alt = _rec(sd, key, r)
            if alt.empty:
                continue
            st.markdown(f"**#{r + 1}** — {ui.money(alt.salary.sum()).replace('$', chr(92) + '$')} · "
                        f"{_phrase(key).lower()} in {float(alt.metric.iloc[0]):.0%} of sims")
            st.dataframe(lineup_table(alt), hide_index=True, width="stretch")
            hover = ui.hover_names_html(alt)
            if hover:
                st.markdown(hover, unsafe_allow_html=True)

    st.subheader("🔄 One-player swaps (stay under the cap)")
    st.caption(f"The number is how the {_phrase(key).lower()} share moves, in percentage points. A ▼ swap scores "
               "worse in the sims — use it only if you want that player (a hunch, or a lower-owned look).")
    sw = sd.swaps[sd.swaps.contest_key == key]
    if sw.empty:
        st.caption("No cap-safe swaps for this lineup.")
    by = sd.pool.set_index("dk_id")
    for i, s in enumerate(sw.itertuples(index=False)):
        if int(s.out_id) not in ids or int(s.in_id) not in by.index:
            continue
        o, n = by.loc[int(s.out_id)], by.loc[int(s.in_id)]
        diff = int(n.salary) - int(o.salary)
        shown = round(float(s.delta) * 100, 1)
        arrow = "▲" if shown > 0 else "▼" if shown < 0 else "＝"
        c = st.columns([7, 1], vertical_alignment="center")
        oc = ui.injury_chip(o.get("inj_tag", ""), o.get("lean", ""))
        nc = ui.injury_chip(n.get("inj_tag", ""), n.get("lean", ""))
        c[0].markdown(f"Swap **{o['name']}**{' ' + oc if oc else ''} → **{n['name']}**{' ' + nc if nc else ''} "
                      f"({n.positions}, {n.team}, {ui.TIER_ICON[n.tier]} "
                      f"{n.own_pct:.1f}%) · {'+' if diff >= 0 else '−'}\\${abs(diff):,} · "
                      f"{arrow} {delta_text(s.delta)}", unsafe_allow_html=True)
        if c[1].button("Apply", key=f"nba_apply_{key}_{i}"):
            new = list(ids)
            slot = new.index(int(s.out_id))
            new[slot] = int(s.in_id)
            _to_my_lineup(new, slot, what="Swap")


def _my_lineup(sd: data.SlateData, key: str, label: str) -> None:
    contest = NBA_CONTEST_TYPES[key]
    keys = list(NBA_CONTEST_TYPES)
    labels = [NBA_CONTEST_TYPES[k]["label"] for k in keys]
    t = st.columns([3, 1, 4], vertical_alignment="bottom")
    start = t[0].selectbox("Start from", ["Blank lineup"] + labels, index=1 + keys.index(key), key="nba_builder_start")
    if t[1].button("Load", width="stretch", key="nba_builder_load"):
        st.session_state.nba_my_ids = ([None] * N_SLOTS if start == "Blank lineup"
                                       else _rec(sd, keys[labels.index(start)]).dk_id.astype(int).tolist())
        st.session_state.pop("nba_focus_slot", None)
        st.rerun()

    ids = list(st.session_state.get("nba_my_ids") or [None] * N_SLOTS)
    status = lineup_status(ids, sd.pool)
    by = sd.pool.set_index("dk_id")
    known = [i for i in status["picked"] if i in by.index]
    m = st.columns(4)
    _metrics(m, status["used"], by.loc[known, "median"].sum(), by.loc[known, "ceiling"].sum())
    if status["valid"]:
        _sims_note(sd)
        rec = _rec(sd, key)
        m[3].metric(f"{_phrase(key)} in", f"{lineup_metric(sd, status['picked'], key):.0%} of sims",
                    f"recommended: {float(rec.metric.iloc[0]):.0%}" if not rec.empty else None,
                    delta_color="off", help=SIMS_HELP)
    for msg in status["messages"]:
        (st.error if msg.startswith("⚠") or msg.startswith("Over the cap") else st.info)(msg)
    st.caption(f"“Recommended” ranking = best fit for **{label}**. Click a slot then a player (or a player then a "
               "slot), or drag a player onto a slot. G = PG/SG, F = SF/PF, UTIL = anyone. Gray = not eligible.")

    value = None
    if os.environ.get("NFLDFS_NO_COMPONENT") == "1":
        st.info("Interactive builder is off in test mode.")
    else:
        from nfldfs_app.builder_component import lineup_builder
        res = lineup_builder(key="nba_builder", on_lineup_change=lambda: None, data={
            "pool": builder_records(sd.pool, contest["weights"], ids), "lineup": ids, "slots": list(ROSTER_SLOTS),
            "slot_elig": SLOT_ELIG, "ns": "nba", "cap": SALARY_CAP,
            "focus_slot": st.session_state.get("nba_focus_slot"),
            "focus_token": st.session_state.get("nba_focus_token")})
        value = getattr(res, "lineup", None)
    new, st.session_state.nba_lb_seen = apply_builder_value(value, st.session_state.get("nba_lb_seen"), ids)
    if new is not None:
        st.session_state.nba_my_ids = new
        st.rerun()

    if status["valid"]:
        _watch(sd, ids, key, "nba_mine", _apply_mine)

    csv = upload_csv_text([status["picked"]]) if status["valid"] else ""
    st.download_button("⬇ Download My Lineup for DraftKings", csv, file_name="dk_nba_classic_my_lineup.csv",
                       mime="text/csv", disabled=not status["valid"], key="nba_dl_mine")


def _tweak(sd: data.SlateData, key: str, label: str) -> None:
    st.caption(f"Don't like someone in the recommended {label} lineup (an injury, a hunch)? Exclude that player, or "
               "lock in a player you want, then rebuild. The app re-picks the other spots around your choices.")
    pool = sd.pool.sort_values("salary", ascending=False, kind="stable")
    all_names = {player_label(r): int(r["dk_id"]) for _, r in pool.iterrows()}
    playable = dict(zip(sd.pool["dk_id"].astype(int), sd.pool["playable"].astype(bool)))
    play_names = {n: i for n, i in all_names.items() if playable.get(i, False)}
    c = st.columns(2)
    locks = [all_names[n] for n in c[0].multiselect("🔒 Lock players (must be in the lineup)", list(all_names),
                                                    key="nba_locks")]
    excl = [play_names[n] for n in c[1].multiselect("✖ Exclude players", list(play_names), key="nba_excludes")]
    if st.button(f"🔁 Rebuild {label} lineup with my choices", disabled=not (locks or excl), key="nba_rebuild"):
        try:
            with st.spinner("Building…"):
                ids, metric, warns = rebuild(sd, key, locks, excl)
            st.session_state.nba_rebuilt = {"dg": sd.dg, "key": key, "ids": ids, "metric": metric, "warnings": warns}
        except InfeasibleError as e:
            st.error(str(e))
    rb = st.session_state.get("nba_rebuilt")
    if rb and (rb.get("dg") != sd.dg or any(int(i) not in sd.row_of for i in rb["ids"])):
        st.session_state.pop("nba_rebuilt", None)
        rb = None
    if rb and rb["key"] == key:
        for w in rb.get("warnings", []):
            st.warning(w)
        st.markdown(f"**Rebuilt lineup** — {_phrase(key).lower()} in {rb['metric']:.0%} of sims")
        st.dataframe(lineup_table(_slotted(sd, rb["ids"])), hide_index=True, width="stretch")
        _watch(sd, rb["ids"], key, "nba_rebuilt", _send_rebuilt)
        if st.button("Send to 🛠 My Lineup", key="nba_send"):
            _send_rebuilt(rb["ids"])

    st.subheader("All players")
    f = st.columns(3)
    pos = f[0].multiselect("Position", POSITIONS, default=POSITIONS, key="nba_pool_pos")
    tiers = f[1].multiselect("Ownership tier", list(ui.TIER_ICON), default=list(ui.TIER_ICON), key="nba_pool_tiers")
    sort = f[2].selectbox("Sort by", list(SORTS), key="nba_pool_sort")
    hurt = ui.has_injury_data(sd.pool) and st.checkbox(INJURED_ONLY, key="nba_pool_injured")
    st.dataframe(pool_table(pool_view(sd.pool, pos, tiers, sort, hurt)), hide_index=True, width="stretch", height=480)
