# Injury Tags, News and Backup Plans — Design

**Date:** 2026-10-29 · **Status:** Reviewed by a builder check; for Nathan's approval · **Priority:** highest (before NBA phase 2)
**Builds on:** NFL app (`2026-10-11-nfl-dfs-optimizer-design.md`), NBA phase 1 (`2026-10-23-nba-optimizer-design.md`).

## 1. Intent
Nathan wants the fantasy-site experience of seeing who is hurt, with the latest note about it, everywhere he picks
players, and wants the app to handle injuries for him. Example: Puka Nacua is recommended, then turns up
questionable; Nathan wants that flagged, a read on whether he'll play, and a ready-made replacement if he sits.

Success: on either sport's page, every player with an injury designation shows its tag and, where available, the
latest news blurb with its age; recommended lineups never contain a player who is unlikely to play; any
questionable player who does make a recommended lineup comes with a ready replacement (1:1 swap or a two-player
rework); and any injured player in Nathan's own lineup gets the same help.

## 2. Goals, non-goals, anti-goals
**Goals**
- Injury tags for NFL and NBA: Questionable (Q), Game-Time Decision (GTD, NBA), Probable (P, NFL), Doubtful (D),
  Out (O/OUT), Injured Reserve (IR), plus body part where known ("Q · ankle").
- Latest news blurb per relevant player, with its age ("2 h ago").
- Recommendation rules below; backup plans below; shown on Mac and phone.

**Non-goals:** paid news feeds; live in-game injury updates; predicting injuries.

**Anti-goals**
- A Doubtful, Out or IR player in any app-made recommendation, swap or backup — **never**.
- A questionable player whose latest news reads as unlikely to play in any app-made recommendation.
- A questionable player in a recommended lineup **without** a backup plan.
- Breaking the build when a news source is down (tags must still work).
- Spending Odds API credits on this (it uses none).

## 3. Data (verified 2026-10-29)
| Need | Source | Notes |
|---|---|---|
| Tag (what DraftKings shows) | DraftKings salary CSV `Status` column — already downloaded every run, both sports | NFL today: 55 Q, 5 OUT, 70 IR. NBA uses Q, GTD, OUT. |
| Body part, when status changed | Sleeper API `api.sleeper.app/v1/players/{nfl,nba}` (free, no key, one call per sport, ~14 MB, <1 s) | `injury_status`, `injury_body_part`, `news_updated`; also gives `espn_id` for the news lookup. Match by normalized name + team. |
| News blurb | ESPN athlete overview `site.web.api.espn.com/apis/common/v3/sports/{football/nfl,basketball/nba}/athletes/{espn_id}/overview` → `rotowire.{headline, story, published}` | Unofficial; one request per player. Example: "Jackson (ankle) was a full participant at Thursday's practice…". |

DraftKings' tag is the source of truth for the tag; Sleeper adds the body part; ESPN adds the words.

## 4. What Nathan decided
- **Show** every injury tag everywhere players appear (lineups, swaps, player lists, builders, Tweak & Rebuild) in
  both sports, with the news blurb where there is one.
- **Questionable players:** used like normal but **avoided unless clearly better value**.
- **Read the news:** if the latest note says a questionable player is on the unlikely side, leave him out of
  recommendations entirely.
- **Never** recommend Doubtful, Out or IR players — not in recommended lineups, alternates, swaps or backups.
- **Backup plans:** whenever a recommended lineup contains any questionable player, always provide a 1:1
  replacement or, if no single swap fits, a two-player rework. Do the same for any injured player (any tag) in a
  lineup Nathan builds or locks himself.

## 5. My calls (Nathan can overrule)
- **"Clearly better value":** a questionable player counts at 85% of his projection inside the optimizer (they
  play roughly four times in five); the number lives in config so it can be tuned. NBA "GTD" is treated as Q.
  NFL "P" (probable) is treated as healthy but still shows its tag.
- **Reading the news ("lean"):** a keyword reading of the most recent blurb from the last 72 hours (Q/GTD only):
  - *Leans out* (excluded like Doubtful) only on statements about **the game**, not practice: "ruled out",
    "will not play", "won't play", "not expected to play", "unlikely to play", "will miss", "expected to miss",
    "out for", "listed as doubtful", "doubtful to play". Nathan (2026-10-29): don't go by keywords alone —
    players sometimes miss practice and still play.
  - *Practice-only notes* ("did not practice", "DNP", "limited", "rest day", "veteran rest", "maintenance")
    are **unclear**, never out on their own.
  - *Leans in*: "full participant", "full practice", "expected to play", "will play", "on track to play",
    "cleared", "upgraded", "removed from the injury report", "probable".
  - Otherwise *unclear* → treated as plain Questionable. A game-level "in" statement ("expected to play",
    "will play", "on track to play") beats any practice note; when game-level statements of both kinds appear, the
    one later in the text wins; "not"/"no longer" directly before a phrase flips it. Shown as "📰 leans out" / "leans in" next to the tag.
- **Backup plan for a questionable player in a recommended lineup:** best 1:1 swap (same slot, under the cap,
  healthy, not already in the lineup) by the contest's own score. If none fits, the best two-player rework (that
  player plus one other spot) that fits. Each shows: who comes in, salary left, and the lineup's score before →
  after. Precomputed by the Mac at every build, so the phone has them.
- **Injured players in Nathan's own lineup** (🛠 My Lineup, 🔁 Tweak & Rebuild results): the same 1:1 / two-player
  suggestions, computed on the device. A lock Nathan places on a D/OUT/IR player still wins (it's his lineup), with
  ⚠ and a backup shown — but the app itself never suggests one.
- **Which players get news fetched:** every tagged player plus everyone in a recommended lineup or alternate
  (~50–100 requests per run, a few seconds). Requests are made politely (small delay, timeouts); failures leave the
  tag without words.
- **When:** at every scheduled build and every "Refresh now" (NFL Tue/Thu/Sun 9:00 and 11:45; NBA 2:00 and 6:30 PM).
- **How "avoid unless clearly better value" works:** in the simulations a questionable (or GTD) player scores 0 in
  15% of outcomes (he sits), and the optimizer weighs him at 85%. Both numbers live in config. Displayed projections
  (median/floor/ceiling) stay the player's when-he-plays numbers, with the tag beside them. The same simulations
  score every lineup, including Nathan's own, so his lineup's percentages reflect the risk too.
- **Backups are healthy only:** a replacement (1:1 or two-player) never carries any tag except P. If no healthy
  1:1 swap fits under the cap, the best healthy two-player rework is shown; if none exists either, the box says so.
  Ranking and the "before → after" numbers use the same contest score as today's swaps (share of simulations
  that cash / finish top-1%), which the app already computes cheaply from the simulations.
- **User locks win:** a player Nathan locks or puts in 🛠 My Lineup himself stays, whatever his tag or lean,
  with ⚠ and a backup shown. App-made suggestions never include D/OUT/IR or lean-out players.
- **When sources disagree:** DraftKings' tag is the tag. The news lean only applies to Q/GTD players: a Q player
  whose latest blurb (≤72 h old) reads as out is treated like Doubtful. Keyword reading only — no practice
  calendar. Each run is fresh; nothing is stored about past leans.
- **Missing matches:** a DK player Sleeper or ESPN can't match keeps his DraftKings tag with no body part or news.
- **Phone:** backups for recommended lineups are stored by the Mac; backups for lineups changed on the phone
  (applied swaps, My Lineup, Tweak & Rebuild) are computed on the phone from the published simulations/pool.
  Pages built before this feature still load (no tags/news shown).
- **Order of work:** before NBA phase 2.

## 6. Where it shows
- Recommended lineups: hovering a player shows his latest news (headline, age, story) as a tooltip.
- Tag chip next to the name: Q / GTD yellow, D orange, OUT / IR red, P gray; "📰 leans out / leans in" when read.
- ⭐ Recommended: a "🩹 Injury watch" box under the lineup listing each tagged player in it with the blurb, its
  age, and the backup plan ("If X sits: swap to Y — $300 left, 12% → 11%"), with an Apply button like swaps.
- Player lists: a filter "Injured / questionable only" and a news column (short headline; full story on expand).
- 🛠 My Lineup and 🔁 Tweak & Rebuild: tag chips, ⚠ for D/OUT/IR, and the backup plan for any tagged player.

## 7. Testing
Unit tests for tag parsing (both sports), the 85% discount, exclusion of D/OUT/IR and lean-out players from every
recommendation path (lineups, alternates, swaps, backups), the keyword lean reader (fixtures of real blurbs),
backup selection (1:1, two-player fallback, none possible message), source failures (Sleeper/ESPN down → tags
still shown, build succeeds). App tests on both pages, hosted and local. A browser check with real data on an NFL
Sunday morning and an NBA evening.
