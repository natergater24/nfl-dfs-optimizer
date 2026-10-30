"""Formatting and small widgets shared by the app's tabs."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd

TIER_ICON = {"Chalk": "🔥 Chalk", "Popular": "Popular", "Moderate": "Moderate", "Contrarian": "💎 Contrarian"}
MODEL_RELATIVE_HELP = "Share of simulated Sundays where this happens — for comparing lineups, not real-world odds."
KEY_MARKDOWN = (
    "**Game style:** this app builds DraftKings **Classic** lineups only (Sunday main slate). "
    "Showdown Captain Mode, Tiers, Pick6 and other styles aren't supported yet.\n\n"
    "**Ownership** — share of the field expected to play him\n"
    "- 🔥 **Chalk** 25%+ · safe, but no edge\n"
    "- **Popular** 10–25%\n"
    "- **Moderate** 5–10%\n"
    "- 💎 **Contrarian** under 5% · if he hits, you pass most of the field\n\n"
    "**Matchup** — points the defense allows to that position (last 6 games)\n"
    "- 🟩 green = soft defense · 🟥 red = tough defense\n\n"
    "_Cash games: lean Chalk. Tournaments: mix in Moderate/Contrarian._")

EASTERN = ZoneInfo("America/New_York")
# (weekday Mon=0, hour, minute) in US Eastern. Mirrors scripts/launchagents: Tue 9:00, Thu 9:00, Sun 9:00, Sun 11:45.
SCHEDULE_ET = ((1, 9, 0), (3, 9, 0), (6, 9, 0), (6, 11, 45))

STEP_LABELS = {"salaries": "DraftKings salaries", "salaries_if_stale": "DraftKings salaries",
               "stats": "NFL stats", "stats_if_missing": "NFL stats", "vegas": "Vegas lines",
               "vegas_if_stale": "Vegas lines", "build": "building lineups", "results": "importing results",
               "publish": "publishing"}


def step_label(name: str) -> str:
    return STEP_LABELS.get(name, name)


def money(v) -> str:
    v = int(round(float(v)))
    return f"-${abs(v):,}" if v < 0 else f"${v:,}"


def metric_phrase(contest_key: str, group: str) -> str:
    if contest_key == "h2h":
        return "Wins the head-to-head"
    return {"Cash": "Cashes", "Multiplier": "Hits the multiplier", "Tournament": "Finishes top-1%"}[group]


def updated_text(minutes: float | None) -> tuple[str, str]:
    if minutes is None:
        return "Update time unknown", "gray"
    if minutes < 60:
        return f"Updated {max(int(minutes), 0)} min ago", "green"
    if minutes < 24 * 60:
        return f"Updated {int(minutes // 60)} h ago", "orange"
    days = int(minutes // 1440)
    return f"Updated {days} day{'' if days == 1 else 's'} ago", "red"


def to_eastern(iso: str | None) -> dt.datetime | None:
    """Parse a build timestamp into US Eastern; a naive timestamp is taken to already be Eastern."""
    if not iso:
        return None
    try:
        then = dt.datetime.fromisoformat(str(iso))
    except ValueError:
        return None
    return then.replace(tzinfo=EASTERN) if then.tzinfo is None else then.astimezone(EASTERN)


def format_refresh(dt_et: dt.datetime) -> str:
    hour = dt_et.hour % 12 or 12
    return f"{dt_et:%a %b} {dt_et.day}, {hour}:{dt_et:%M} {'AM' if dt_et.hour < 12 else 'PM'} ET"


def next_scheduled_refresh(now_et: dt.datetime) -> dt.datetime:
    """The first scheduled run strictly after now (wall-clock Eastern), wrapping into next week."""
    start = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    best = None
    for week in (0, 7):
        for wd, hour, minute in SCHEDULE_ET:
            day = start + dt.timedelta(days=(wd - start.weekday()) % 7 + week)
            cand = day.replace(hour=hour, minute=minute)      # replace keeps tzinfo, so DST stays wall-clock
            if cand > now_et and (best is None or cand < best):
                best = cand
    return best


def _matchup_css(colors: list[str]):
    return lambda col: [f"background-color: {c}; color: white; font-weight: 600" for c in colors]


def _matchup(df: pd.DataFrame):
    return ("vs " + df["opp"].astype(str) + " · " + df["mu_label"].astype(str)).to_numpy()


def styled_lineup(df: pd.DataFrame):
    view = pd.DataFrame({
        "Pos": df["slot"].to_numpy(), "Player": names_with_chips(df), "Team": df["team"].to_numpy(),
        "Matchup": _matchup(df), "Salary": df["salary"].to_numpy(), "Median": df["median"].to_numpy(),
        "Floor": df["floor"].to_numpy(), "Ceiling": df["ceiling"].to_numpy(), "Own %": df["own_pct"].to_numpy(),
        "Tier": df["tier"].map(TIER_ICON).to_numpy()})
    return (view.style.apply(_matchup_css(df["mu_color"].tolist()), subset=["Matchup"])
            .format({"Salary": "${:,.0f}", "Median": "{:.1f}", "Floor": "{:.1f}", "Ceiling": "{:.1f}",
                     "Own %": "{:.0f}%"}))


def styled_pool(df: pd.DataFrame):
    view = pd.DataFrame({
        "Player": names_with_chips(df), "Pos": df["position"].to_numpy(), "Team": df["team"].to_numpy(),
        "Matchup": _matchup(df), "Salary": df["salary"].to_numpy(), "Median": df["median"].to_numpy(),
        "Floor": df["floor"].to_numpy(), "Ceiling": df["ceiling"].to_numpy(),
        "Boom %": (df["boom_rate"] * 100).to_numpy(), "Pts/$1K": df["value"].to_numpy(),
        "Own %": df["own_pct"].to_numpy(), "Tier": df["tier"].map(TIER_ICON).to_numpy()})
    if has_injury_data(df):
        view["News"] = [news_text(r) for _, r in df.iterrows()]
    return (view.style.apply(_matchup_css(df["mu_color"].tolist()), subset=["Matchup"])
            .format({"Salary": "${:,.0f}", "Median": "{:.1f}", "Floor": "{:.1f}", "Ceiling": "{:.1f}",
                     "Boom %": "{:.0f}%", "Pts/$1K": "{:.2f}", "Own %": "{:.1f}%"}))


def _tag_lean(by_id, dk_id) -> tuple[str, str]:
    if "inj_tag" not in by_id.columns or int(dk_id) not in by_id.index:
        return "", ""
    r = by_id.loc[int(dk_id)]
    return r.get("inj_tag", ""), r.get("lean", "")


def swap_line(s, pool_by_id) -> str:
    p = pool_by_id.loc[int(s.in_dk_id)]
    sign = "+" if s.salary_delta > 0 else "−"
    tag = (f"<span style='background:{p['mu_color']};color:#fff;font-weight:600;font-size:12px;"
           f"padding:1px 6px;border-radius:4px'>vs {p['opp']} · {p['mu_label']}</span>")
    oc = injury_chip(*_tag_lean(pool_by_id, s.out_dk_id))
    ic = injury_chip(*_tag_lean(pool_by_id, s.in_dk_id))
    oc, ic = (" " + oc if oc else ""), (" " + ic if ic else "")
    return (f"Swap **{s.out_name}**{oc} → **{s.in_name}**{ic} ({s.position}, {s.in_team}, {TIER_ICON[s.in_tier]} "
            f"{s.in_own_pct:.1f}%) {tag} · {sign}\\${abs(int(s.salary_delta)):,} · "
            f"\\${int(s.remaining_salary):,} left · ceiling {s.ceiling_delta:+.1f}")


def report_card_widget(card: dict) -> None:
    import streamlit as st
    if not card or not card.get("weeks"):
        st.caption("No results imported yet — after Sunday's games, follow 📥 in the sidebar.")
        return
    lat, sea = card.get("latest", {}), card.get("season", {})
    c = st.columns(3)
    c[0].metric("Projection error", f"{lat.get('proj_mae', '—')} pts",
                help="Average gap between our median and the actual DraftKings points.")
    c[1].metric("Actual inside floor–ceiling", f"{lat.get('in_range_pct', '—')}%",
                help="About 65% means the floor/ceiling ranges are well calibrated.")
    c[2].metric("Ownership error", f"{lat.get('own_mae', '—')} pts of %",
                help="Average gap between estimated and actual ownership.")
    st.caption(f"Latest slate {card.get('latest_slate')} · season to date ({card['weeks']} weeks): "
               f"{sea.get('proj_mae', '—')} pts error, {sea.get('in_range_pct', '—')}% in range, "
               f"ownership error {sea.get('own_mae', '—')}")


HISTORY_FORMATS = {"Salary": "${:,.0f}", "Projected": "{:.1f}", "Actual": "{:.1f}", "+/−": "{:+.1f}",
                   "Own est.": "{:.0f}%", "Own actual": "{:.0f}%"}


def display_numbers(df: pd.DataFrame, formats: dict) -> pd.DataFrame:
    """Format numeric columns to strings ('—' for missing); st.dataframe shows nulls as 'None' otherwise."""
    out = df.copy()
    for col, fmt in formats.items():
        if col in out:
            out[col] = [("—" if pd.isna(v) else fmt.format(v)) for v in out[col]]
    return out


def styled_player_history(table: pd.DataFrame):
    view = display_numbers(table.drop(columns=["mu_color"]), HISTORY_FORMATS)
    return view.style.apply(_matchup_css(table["mu_color"].tolist()), subset=["Matchup"])


def signed_money(v) -> str:
    v = float(v)
    return f"{'+' if v >= 0 else '−'}${abs(v):,.0f}"


# ── injuries (shared by the 🏈 and 🏀 pages) ──────────────────────────────────────────────────────────────

INJURY_COLUMNS = ("inj_tag", "inj_class", "lean", "body_part", "news_headline", "news_story", "news_published",
                  "recommendable", "play_prob")
# tag -> (background, text color, emoji for plain-text places such as select labels and table cells)
CHIP_STYLE = {"Q": ("#f2c94c", "#1a1a1a", "🟡"), "GTD": ("#f2c94c", "#1a1a1a", "🟡"),
              "D": ("#f2994a", "#1a1a1a", "🟠"), "OUT": ("#eb5757", "#ffffff", "🔴"),
              "IR": ("#eb5757", "#ffffff", "🔴"), "P": ("#9e9e9e", "#ffffff", "⚪")}
_OTHER_TAG = ("#eb5757", "#ffffff", "🔴")            # anything unfamiliar (suspended, …) is never suggested
LEAN_TEXT = {"out": "📰 leans out", "in": "📰 leans in"}
TAG_WORD = {"OUT": "Out", "D": "Doubtful", "IR": "on IR"}


def has_injury_data(df) -> bool:
    """True for pools published with the injury columns (older builds have none: no chips, no Injury watch)."""
    return df is not None and "inj_tag" in getattr(df, "columns", ())


def _s(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return ""
    return str(v).strip()


def _lean_of(tag: str, lean) -> str:
    return LEAN_TEXT.get(_s(lean).lower(), "") if tag in ("Q", "GTD") else ""


def injury_chip(tag, lean=None) -> str:
    """HTML chip for an injury tag (Q/GTD yellow, D orange, OUT/IR red, P gray), plus the news lean; "" when healthy."""
    import html
    t = _s(tag).upper()
    if not t:
        return ""
    bg, fg, _ = CHIP_STYLE.get(t, _OTHER_TAG)
    chip = (f"<span style='background:{bg};color:{fg};font-weight:700;font-size:12px;padding:1px 6px;"
            f"border-radius:4px;white-space:nowrap'>{html.escape(t)}</span>")
    ln = _lean_of(t, lean)
    return chip + (f" <span style='font-size:12px;white-space:nowrap'>{ln}</span>" if ln else "")


def chip_text(tag, lean=None) -> str:
    """Plain-text chip for select labels and table cells ("🟡 Q · 📰 leans out"); "" when healthy."""
    t = _s(tag).upper()
    if not t:
        return ""
    ln = _lean_of(t, lean)
    return f"{CHIP_STYLE.get(t, _OTHER_TAG)[2]} {t}" + (f" · {ln}" if ln else "")


def row_chip_text(row) -> str:
    return chip_text(row.get("inj_tag", ""), row.get("lean", "")) if hasattr(row, "get") else ""


def news_age(published, now: dt.datetime | None = None) -> str:
    """"just now", "N min ago", "N h ago", "N d ago" from a UTC ISO timestamp; "" when unknown."""
    p = _s(published)
    if not p:
        return ""
    try:
        then = dt.datetime.fromisoformat(p.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if then.tzinfo is None:
        then = then.replace(tzinfo=dt.timezone.utc)
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    mins = (now - then).total_seconds() / 60
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{int(mins)} min ago"
    if mins < 24 * 60:
        return f"{int(mins // 60)} h ago"
    return f"{int(mins // 1440)} d ago"


def news_text(row, now: dt.datetime | None = None) -> str:
    """"Headline (2 h ago)" for the pool tables' News column; "" without news."""
    head = _s(row.get("news_headline", ""))
    if not head:
        return ""
    age = news_age(row.get("news_published", ""), now)
    return f"{head} ({age})" if age else head


def news_tooltip(row, now: dt.datetime | None = None) -> str:
    """Hover text for a player's name: tag + body part, then the latest headline (age) and story.
    Players without news get their tag only; healthy players without news get ""."""
    tag = _s(row.get("inj_tag", "")).upper()
    first = " · ".join(x for x in (chip_text(tag, row.get("lean", "")), _s(row.get("body_part", ""))) if x)
    head, story = _s(row.get("news_headline", "")), _s(row.get("news_story", ""))
    lines = [first] if first else []
    if head:
        age = news_age(row.get("news_published", ""), now)
        lines.append(f"{head} ({age})" if age else head)
        if story:
            lines.append(story)
    return "\n".join(lines)


def names_with_chips(df: pd.DataFrame) -> list[str]:
    """The lineup/pool tables' Player cells: the name plus a plain-text chip for tagged players."""
    if not has_injury_data(df):
        return df["name"].astype(str).tolist()
    out = []
    for name, tag, ln in zip(df["name"], df["inj_tag"], df["lean"] if "lean" in df else [""] * len(df)):
        c = chip_text(tag, ln)
        out.append(f"{name} · {c}" if c else str(name))
    return out


def hover_names_html(df: pd.DataFrame, now: dt.datetime | None = None) -> str:
    """Recommended lineups: every player's name with an HTML title tooltip holding his latest news
    (st.dataframe does not render pandas Styler tooltips). "" for builds without injury data."""
    if not has_injury_data(df):
        return ""
    parts = []
    for _, r in df.iterrows():
        tip = news_tooltip(r, now)
        chip = injury_chip(r.get("inj_tag", ""), r.get("lean", ""))
        name = safe(r["name"])
        if tip:
            tip = safe(tip).replace("\r", "").replace("\n", "&#10;")   # one markdown line
            name = (f"<span title=\"{tip}\" style='cursor:help;"
                    f"text-decoration:underline dotted'>{name}</span>")
        parts.append(name + (f" {chip}" if chip else ""))
    return ("<div style='font-size:13px;line-height:1.9'>📰 <span style='opacity:.7'>Hover a name for news:</span> "
            + " · ".join(parts) + "</div>")


def injury_warnings(pool: pd.DataFrame, ids) -> list[str]:
    """⚠ for each chosen player the app would never pick itself: excluded tag (Out/Doubtful/IR/…) or news
    leaning out. Same wording as nbadfs.lineups.out_lock_warnings. Empty for builds without injury data."""
    if not has_injury_data(pool):
        return []
    by = _by_id(pool)
    out = []
    for i in ids:
        if i is None or int(i) not in by.index:
            continue
        r = by.loc[int(i)]
        tag = _s(r.get("inj_tag", "")).upper()
        if _s(r.get("inj_class", "")) == "excluded":
            out.append(f"⚠ {r['name']} is listed {TAG_WORD.get(tag, tag or 'Out')}")
        elif tag in ("Q", "GTD") and _s(r.get("lean", "")).lower() == "out":
            out.append(f"⚠ {r['name']}: news leans out")
    return out


def blocks_export(row) -> bool:
    """My Lineup: an unplayable player blocks the export ("ruled out — swap him") unless his injury tag is the
    reason — then Nathan's pick wins (⚠ + backup). Builds without injury data: every unplayable player blocks."""
    if bool(row["playable"]):
        return False
    return _s(row.get("inj_class", "")) != "excluded"


def pick_warnings(pool: pd.DataFrame, ids) -> list[str]:
    """My Lineup: the ⚠ for Nathan's own picks the app would never make; his pick stands."""
    return [f"{w} — your pick stands; see 🩹 Injury watch for a backup." for w in injury_warnings(pool, ids)]


def _ids(v) -> list[int]:
    if v is None:
        return []
    return [int(x) for x in list(v)]


def backup_line(b, name_of: dict) -> str:
    """"If X sits: Y — $1,200 left, 31% → 29%" (markdown, $ escaped) for one injury_backups row."""
    outs, ins = _ids(b["out_dk_ids"]), _ids(b["in_dk_ids"])
    who = safe(name_of.get(int(b["tagged_dk_id"]), "He"))
    if b["kind"] == "none" or not ins:
        return f"If **{who}** sits: {b['message']}"
    names = ", ".join(f"**{safe(name_of.get(i, i))}**" for i in ins)
    extra = [safe(name_of.get(o, o)) for o in outs if o != int(b["tagged_dk_id"])]
    also = f" (also moves out {', '.join(map(str, extra))})" if extra else ""
    return (f"If **{who}** sits: {names}{also} — \\${int(b['remaining_salary']):,} left, "
            f"{float(b['metric_before']):.0%} → {float(b['metric_after']):.0%}")


def apply_backup(ids, out_ids, in_ids) -> tuple[list, int]:
    """Replace each player moving out with the matching player coming in (same slot). Returns (ids, first slot)."""
    new = [None if i is None else int(i) for i in ids]
    first = None
    for o, n in zip(_ids(out_ids), _ids(in_ids)):
        slot = new.index(int(o))
        new[slot] = int(n)
        first = slot if first is None else first
    return new, (first if first is not None else 0)


def pick_backups(published, key: str, tagged_ids, compute):
    """The published backups when they cover every tagged player of the shown (published rank-0) lineup;
    otherwise compute them on this device."""
    tagged = {int(i) for i in tagged_ids}
    if published is not None and len(published) and {"contest_key", "tagged_dk_id"} <= set(published.columns):
        pb = published[published["contest_key"] == key]
        if tagged <= set(pb["tagged_dk_id"].astype("int64")):
            return pb[pb["tagged_dk_id"].astype("int64").isin(tagged)].reset_index(drop=True)
    return compute()


def remembered(cache_key: tuple, compute):
    """On-device backups take a fraction of a second; remember the last few per browser session so reruns
    (every click) don't recompute them."""
    import streamlit as st
    memo = st.session_state.setdefault("_injury_backups_memo", {})
    if cache_key not in memo:
        if len(memo) >= 16:
            memo.pop(next(iter(memo)))
        memo[cache_key] = compute()
    return memo[cache_key]


def _by_id(pool: pd.DataFrame) -> pd.DataFrame:
    u = pool.drop_duplicates("dk_id")
    return u.set_index(u["dk_id"].astype("int64"))


def tagged_ids(pool: pd.DataFrame, ids, include_healthy: bool = False) -> list[int]:
    """Lineup players who need a backup: inj_class not healthy (P is healthy). With include_healthy, every
    player with any tag (P too) — for showing news."""
    if not has_injury_data(pool):
        return []
    by = _by_id(pool)

    def hit(i):
        if include_healthy:
            return bool(_s(by.at[i, "inj_tag"]))
        cls = _s(by.at[i, "inj_class"]) if "inj_class" in by.columns else ""
        return bool(_s(by.at[i, "inj_tag"])) and cls != "healthy"
    return [int(i) for i in ids if i is not None and int(i) in by.index and hit(int(i))]


_MD_SPECIAL = {"\\": "&#92;", "`": "&#96;", "*": "&#42;", "_": "&#95;", "[": "&#91;", "]": "&#93;",
               "$": "&#36;", "~": "&#126;", "#": "&#35;", "|": "&#124;"}


def safe(text) -> str:
    """Feed/name text for st.markdown(unsafe_allow_html=True) or an HTML attribute: HTML-escaped, and Markdown
    specials (\\ ` * _ [ ] $ ~ # |) turned into character references, so "$5 … $10" is no LaTeX and *x* or
    [x](y) stay literal."""
    import html
    return "".join(_MD_SPECIAL.get(ch) or html.escape(ch, quote=True) for ch in _s(text))


def watch_blurb(r, now: dt.datetime | None = None) -> str:
    """One Injury watch entry: name, chip, body part, headline + age, and the story in a <details> block."""
    bits = [f"**{safe(r['name'])}** {injury_chip(r.get('inj_tag', ''), r.get('lean', ''))}"]
    if _s(r.get("body_part", "")):
        bits.append(safe(r["body_part"]))
    head = _s(r.get("news_headline", ""))
    if head:
        age = news_age(r.get("news_published", ""), now)
        bits.append(f"📰 {safe(head)}" + (f" <span style='opacity:.7'>({age})</span>" if age else ""))
    else:
        bits.append("<span style='opacity:.7'>no news yet</span>")
    text = " · ".join(bits)
    story = _s(r.get("news_story", ""))
    if story:
        text += (f"<details><summary style='cursor:pointer;font-size:13px'>Full story</summary>"
                 f"<div style='font-size:13px'>{safe(story).replace(chr(10), ' ')}</div></details>")
    return text


def injury_watch(pool: pd.DataFrame, ids, backups, key_prefix: str, on_apply, now: dt.datetime | None = None) -> None:
    """🩹 Injury watch: per tagged player in the lineup — chip, body part, headline + age (story on expand) and
    the backup line with an Apply button. `on_apply(new_ids, slot)` runs when Apply is clicked. Nothing for
    builds without injury data."""
    import streamlit as st
    if not has_injury_data(pool):
        return
    need = set(tagged_ids(pool, ids))                       # not healthy: these get a backup line
    shown = tagged_ids(pool, ids, include_healthy=True)    # P players still show their news
    by = _by_id(pool)
    name_of = {int(i): str(n) for i, n in zip(by.index, by["name"])}
    with st.expander("🩹 Injury watch", expanded=bool(need)):
        if not shown:
            st.caption("No injury tags in this lineup.")
            return
        bk = backups if backups is not None else pd.DataFrame()
        for t in shown:
            st.markdown(watch_blurb(by.loc[t], now), unsafe_allow_html=True)
            if t not in need:
                continue
            rows = bk[bk["tagged_dk_id"].astype("int64") == t] if len(bk) else bk
            if not len(rows):
                st.caption("No backup computed for this player.")
                continue
            b = rows.iloc[0]
            c = st.columns([7, 1], vertical_alignment="center")
            c[0].markdown(backup_line(b, name_of))
            if b["kind"] != "none" and c[1].button("Apply", key=f"{key_prefix}_backup_{t}"):
                new, slot = apply_backup(ids, b["out_dk_ids"], b["in_dk_ids"])
                on_apply(new, slot)
