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
