"""Formatting and small widgets shared by the app's tabs."""
from __future__ import annotations

import pandas as pd

TIER_ICON = {"Chalk": "🔥 Chalk", "Popular": "Popular", "Moderate": "Moderate", "Contrarian": "💎 Contrarian"}
MODEL_RELATIVE_HELP = "Share of simulated Sundays where this happens — for comparing lineups, not real-world odds."
KEY_MARKDOWN = (
    "**Ownership** — share of the field expected to play him\n"
    "- 🔥 **Chalk** 25%+ · safe, but no edge\n"
    "- **Popular** 10–25%\n"
    "- **Moderate** 5–10%\n"
    "- 💎 **Contrarian** under 5% · if he hits, you pass most of the field\n\n"
    "**Matchup** — points the defense allows to that position (last 6 games)\n"
    "- 🟩 green = soft defense · 🟥 red = tough defense\n\n"
    "_Cash games: lean Chalk. Tournaments: mix in Moderate/Contrarian._")


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
    return f"Updated {int(minutes // 1440)} days ago", "red"


def _matchup_css(colors: list[str]):
    return lambda col: [f"background-color: {c}; color: white; font-weight: 600" for c in colors]


def _matchup(df: pd.DataFrame):
    return ("vs " + df["opp"].astype(str) + " · " + df["mu_label"].astype(str)).to_numpy()


def styled_lineup(df: pd.DataFrame):
    view = pd.DataFrame({
        "Pos": df["slot"].to_numpy(), "Player": df["name"].to_numpy(), "Team": df["team"].to_numpy(),
        "Matchup": _matchup(df), "Salary": df["salary"].to_numpy(), "Median": df["median"].to_numpy(),
        "Floor": df["floor"].to_numpy(), "Ceiling": df["ceiling"].to_numpy(), "Own %": df["own_pct"].to_numpy(),
        "Tier": df["tier"].map(TIER_ICON).to_numpy()})
    return (view.style.apply(_matchup_css(df["mu_color"].tolist()), subset=["Matchup"])
            .format({"Salary": "${:,.0f}", "Median": "{:.1f}", "Floor": "{:.1f}", "Ceiling": "{:.1f}",
                     "Own %": "{:.0f}%"}))


def styled_pool(df: pd.DataFrame):
    view = pd.DataFrame({
        "Player": df["name"].to_numpy(), "Pos": df["position"].to_numpy(), "Team": df["team"].to_numpy(),
        "Matchup": _matchup(df), "Salary": df["salary"].to_numpy(), "Median": df["median"].to_numpy(),
        "Floor": df["floor"].to_numpy(), "Ceiling": df["ceiling"].to_numpy(),
        "Boom %": (df["boom_rate"] * 100).to_numpy(), "Pts/$1K": df["value"].to_numpy(),
        "Own %": df["own_pct"].to_numpy(), "Tier": df["tier"].map(TIER_ICON).to_numpy()})
    return (view.style.apply(_matchup_css(df["mu_color"].tolist()), subset=["Matchup"])
            .format({"Salary": "${:,.0f}", "Median": "{:.1f}", "Floor": "{:.1f}", "Ceiling": "{:.1f}",
                     "Boom %": "{:.0f}%", "Pts/$1K": "{:.2f}", "Own %": "{:.1f}%"}))


def swap_line(s, pool_by_id) -> str:
    p = pool_by_id.loc[int(s.in_dk_id)]
    sign = "+" if s.salary_delta > 0 else "−"
    tag = (f"<span style='background:{p['mu_color']};color:#fff;font-weight:600;font-size:12px;"
           f"padding:1px 6px;border-radius:4px'>vs {p['opp']} · {p['mu_label']}</span>")
    return (f"Swap **{s.out_name}** → **{s.in_name}** ({s.position}, {s.in_team}, {TIER_ICON[s.in_tier]} "
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
