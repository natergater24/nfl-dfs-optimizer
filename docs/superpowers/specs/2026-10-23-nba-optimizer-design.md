# NBA DFS Optimizer — Design

**Date:** 2026-10-23 · **Status:** Reviewed by a builder check; for Nathan's approval
**Builds on:** the live NFL app (`2026-10-11-nfl-dfs-optimizer-design.md`, `2026-10-16-my-results-design.md`).
**Already live:** the app has separate 🏈 NFL / 🏀 NBA pages in the left menu (`app.py` routes to `nfl_page.py` /
`nba_page.py`); the NBA page is a placeholder. A throwaway data spike (branch `nba-spike`, not merged) proved the data
sources below.

## 1. Intent

Nathan plays DraftKings NFL on Sundays with this app and wants the same help for NBA, which has slates almost every
night of the season. He plays either in the **afternoon** or **much later at night**, so the app must always show
something useful for the slate he can still enter, and must cope with NBA's late injury news and late swap.

Success: on any NBA night he opens the 🏀 NBA page (phone or Mac) and sees the next slate that still has games to
play, a recommended lineup per contest type with outlier swaps, and the same tools he uses for NFL (🛠 My Lineup,
🔁 Tweak & Rebuild, 📒 My Results). If he opens it after some games have tipped, the app helps him re-pick only the
players he can still change.

## 2. Goals, non-goals, anti-goals

**Goals**
- Same four tabs and behavior as NFL: ⭐ Recommended (lineup + outlier swaps per contest type), 🛠 My Lineup
  (builder), 🔁 Tweak & Rebuild (lock / exclude / rebuild), 📒 My Results (entries, money, player history).
- DraftKings **Classic** NBA only, every Classic slate of the day (DK currently labels them Main, "Night",
  "Late Night").
- Projections anchored on Vegas (team implied totals, spreads), simulated outcomes, ownership tiers (🔥 Chalk ≥25%,
  Popular 10–25%, Moderate 5–10%, 💎 Contrarian <5%), PuLP optimizer — the NFL approach adapted to basketball.

**Non-goals (for now)**
- Showdown Captain Mode, Tiers, Snake, In-Game Showdown, Pick 6 (other DK styles), WNBA.
- Automated entry into DraftKings or any DraftKings login.
- Live in-game scoring.

**Anti-goals (would be a failure even if it "works")**
- Breaking or slowing the live NFL app or its Tue/Thu/Sun schedule during the NFL season.
- Running out of the free Odds API allowance (500 requests/month, shared with NFL).
- Recommending a player DraftKings lists as **Out**, or a player from a game that already started, without the
  user choosing that.
- Publishing any DraftKings username.

## 3. Constraints (carried over from the NFL app)
- Python via `./py`; hosted copy runs on Streamlit Community Cloud (Python 3.12, read-only); local Mac pipeline via
  LaunchAgents publishes `data/published` / `data/history` to GitHub; atomic writes; privacy rules; tests stay green
  under `-W error`; the Mac must be awake for scheduled runs (keep-awake already in `run_stage.sh`).
- NBA files live apart from NFL files: `data/published/nba/`, `data/history/nba/`, `data/processed/nba/`,
  `data/raw/nba/` — a failure in one sport must never block the other.
- Free data only.

## 4. Data sources (verified by the spike, 2026-10-23)
| Need | Source | Notes |
|---|---|---|
| Slates, salaries, eligibility, injury status | DK lobby `getcontests?sport=NBA`, Classic = ContestTypeId 70; salary CSV `getavailableplayerscsv?contestTypeId=70&draftGroupId=…` | CSV has `Roster Position` (e.g. `PG/G/UTIL`), `Status` (O/Q/GTD…), `AvgPointsPerGame`, `Game Info` with tip time. Slate name from `ContestStartTimeSuffix` (blank = Main). |
| Lines | The Odds API `basketball_nba`, markets spreads+totals, region us | 2 credits per call; response includes the next day's games — filter to the slate date. |
| Season stats | sportsdataverse-data releases `espn_nba_player_season_stats` (parquet, long format; file year = season end, 2027 = current) | Matched 173/207 slate players by name in the spike; misses are mostly rookies. |
| Recent game logs (minutes trends, current season) | ESPN site API (`site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=…` + game summaries) | Works; stats.nba.com times out and cdn.nba.com returns 403 — **do not use either**. |

## 5. What Nathan decided

**Layout**
- One app; 🏈 NFL and 🏀 NBA are separate pages at the top of the left menu, each with its own address (`/nfl`,
  `/nba`). Below the page links, the left side shows that sport's own sidebar (refresh, results import, uploads).
- The NBA page mirrors the NFL page's structure and four tabs.
- NBA contest types use DraftKings' NBA names where they differ from NFL's; otherwise the same set (Head-to-Head,
  50/50, Double Up, multipliers, Single Entry, Tournament, Large-Field Tournament).

**Which slate**
- The page opens on **whichever slate hasn't locked yet**: the next slate whose first game hasn't tipped, so it can
  still be entered (afternoon → Main; after Main's first tip → the next later slate, if any). Slates already underway
  stay one click away for late swap. If every slate of the day has started, it opens on the one with games still to
  play.
- The slate's games are listed with tip time and line; **games that have started are grayed out**.
- If the lineups were built before a game that has since started, a small warning recommends refreshing.

**Daily timing — option C**
- One automatic NBA build every afternoon (all of the day's Classic slates), plus a refresh for late news.
- **Plus an automatic evening build (~6:30 PM ET)** so late slates carry the late injury news on the phone without
  touching the Mac (Nathan, 2026-10-23). The Mac must be awake then (plugged in, lid open).
- Odds API: pull NBA and NFL lines in the same runs where possible, and only as needed, so the free allowance covers
  both sports.

**Late swap (NBA Classic locks each player at his own game's tip)**
- After a game has tipped, a refresh **only re-picks players in games that haven't tipped**; players from started
  games stay as they were. That becomes the new recommendation.
- Nathan can add players from in-progress games when they're part of his real in-progress lineup; such players are
  marked with a small icon (⏱) and act as locks.

## 6. My calls (Nathan can overrule)
- **Phases:** (1) projections + optimizer + Recommended / My Lineup / Tweak & Rebuild for all of the day's slates,
  with the automatic afternoon build; (2) slate auto-pick, grayed games, refresh warning, late swap with ⏱ players;
  (3) NBA in My Results (standings + entry-history imports; the entry-history CSV has `Sport` = NBA) and fixes from
  the first live nights.
- **Build times:** 2:00 PM ET and ~6:30 PM ET daily. No season dates to maintain: a run does nothing (no Odds API
  call) when the DK lobby has no NBA Classic slate. NFL keeps its schedule. Each run fetches only its own sport's
  lines, and skips the Odds API call when lines are under ~60 minutes old (like NFL's `vegas_if_stale`). Expected NBA
  use ≈ 2 credits × (2 builds + a few refreshes) per game day ≈ 130–180/month; NFL ≈ 30–40/month; total stays under
  the 500 limit. The evening run, like the NFL runs, keeps the Mac awake while it works.
- **"Refresh" after tip-off:** on the **Mac**, Refresh re-downloads salaries/injury status (and lines if stale) and
  rebuilds; once games have started it keeps started players fixed (late swap). On the **phone** (read-only, no data
  fetch), the same re-pick runs on the already-published data, like Tweak & Rebuild does today.
- **Which lineup stays fixed after tip-off:** the one on screen — the recommended lineup for the chosen contest
  type, or the lineup in 🛠 My Lineup if he sent one there (one lineup at a time; no multi-entry handling). If the
  open spots can't be filled (cap, positions, 2-game rule), show why — same as Tweak & Rebuild's infeasible message.
- **DK `Status`:** `O` (out) players are excluded from builds; `Q`/`GTD` are flagged in tables and allowed. An Out
  player in the fixed lineup whose game hasn't tipped is replaced automatically by the re-pick. If Nathan locks an
  Out player himself, the lock wins and the player is flagged ⚠.
- **Slate choice** is not remembered between visits or devices; the default rule above applies each time.
- **NBA results** live in their own files (`data/history/nba/`); the existing entry-history importer routes rows by
  `Sport`, so NFL behavior is unchanged.
- **Ownership:** same tiers and same field-simulation approach as NFL; the learned ownership model starts after a
  few weeks of imported NBA results.

## 7. Projection approach (sketch — details left to the builder)
- DraftKings NBA scoring: point 1, made 3 +0.5, rebound 1.25, assist 1.5, steal 2, block 2, turnover −0.5,
  double-double +1.5, triple-double +3.
- Roster: PG, SG, SF, PF, C, G (PG/SG), F (SF/PF), UTIL; $50,000 cap; 8 players; at least 2 games represented
  (DK rule).
- Projection = expected **minutes** × **DK points per minute**, both blended from last season and this season by
  games played, then scaled by the team's Vegas implied total vs. league average (pace/efficiency).
- When a player is **Out**, his minutes are shared among teammates at similar positions (analogous to NFL's injury
  redistribution).
- Simulation: correlated per-game outcomes (game total shifts both teams), per-player variance on minutes and rate;
  10,000 sims like NFL.
- The builder decides the exact model, priors for rookies (no prior stats: salary-implied baseline), and how much
  to trust DK's `AvgPointsPerGame` early in the season.

## 8. Left to the builder
- Code structure (how much of `nfldfs/` to generalize vs. a parallel `nbadfs/` package), file names, the scheduling
  mechanism, the minutes model details, the exact DK NBA contest names (read them from the lobby), and how the NBA
  sidebar reuses the NFL sidebar.
- Must keep: every existing NFL test and behavior, the privacy rules, the publish flow.

## 9. Testing and checks
- Unit tests for NBA scoring, roster eligibility (G/F/UTIL flex slots), slate picking by time, late-swap re-pick
  (started players fixed, only open-game players change), Out-player exclusion, odds staleness, credit-saving skip.
- App tests for the NBA page on hosted (read-only) and local.
- Real-data checks on at least two live NBA nights before calling a phase done, including one night opened after the
  main slate tipped.
