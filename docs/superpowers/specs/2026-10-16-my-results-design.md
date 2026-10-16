# My Results — Entry Tracker & Player History (Design Spec)

**Date:** 2026-10-16 · **Status:** Approved · built 2026-10-16 (branch my-results)
**Builds on:** `2026-10-11-nfl-dfs-optimizer-design.md` (engine + app, live at https://nfl-dfs-optimizer.streamlit.app/)
**Approved mockup:** `docs/mockups/my-results-tab.html` (sample data; layout is binding, numbers are not)

## 1. Purpose and success criteria

Nathan wants one place that answers "how am I doing?" for the DraftKings Classic contests he actually enters, and "how has this player done?" across weeks.

**Success looks like:**
- After a Sunday, exporting the contest standings (the existing 2-click flow) makes each of his entries appear in **📒 My Results** automatically: contest, finish, his 9 players, actual vs. projected points, and which app lineup it was.
- Money (fee, winnings, profit) is filled from a DraftKings download when one exists; otherwise he types winnings once on the Mac, and the app flags any entry still missing it.
- Season totals (entries, cashes, cash rate, fees, winnings, profit, ROI, avg actual vs. projected) and per-contest-type breakdowns are always current.
- **Player history**: search any player and see every slate the app projected him for — salary, matchup rating, projected vs. actual points, estimated vs. actual ownership — plus his results in Nathan's entries.
- The phone shows everything read-only; editing happens on the Mac (option A, chosen by Nathan).

**What Nathan said vs. assumptions:**
- Said: approach A (import first, typing as backup); the field list in §4; the mockup layout with player search after the filters; Mac-only editing; his DraftKings username may be stored locally (`natergater24`).
- Assumed: no pre-logging of entries before games (the app's saved weekly projections give "projected"); "cashed" = winnings > 0; ROI = (winnings − fees) / fees.

## 2. Scope

**In:** the My Results tab (totals, by-type breakdown, filters, player history, entry log with box scores, Mac-only edit/add/winnings entry), entry detection from contest-standings imports, money from DraftKings' entry-history download if it exists, weekly actual points for all players, privacy rules below.
**Out (later):** Showdown Captain Mode (separate project), charts over time, bankroll goals, logging from the phone, any automated DraftKings login.

## 3. Constraints

- **No DraftKings login automation** (unchanged). Data arrives only through files Nathan downloads.
- **Privacy:** `DK_USERNAME` lives only in git-ignored `env.txt` on the Mac (Nathan adds it; the app never prints it). Published files (`data/published`, `data/history`) never contain any DraftKings username — Nathan's or anyone else's. Raw standings files stay in git-ignored `data/raw/standings/`.
- **Editing is local-only** (hosted copy is read-only; MLB lesson). Saves are atomic and published by the existing publish step.
- Display rules unchanged: full dollars (`$7,500`), Classic labels, matchup tags, ownership tiers.

## 4. Data model

**`data/history/entries.parquet`** (published) — one row per Nathan entry:

| Field | Source |
|---|---|
| `entry_id` (DK EntryId), `contest_id`, `slate_date` | standings import (contest id from file name `contest-standings-<id>.zip`) |
| `contest_name`, `contest_type` (one of the 9 Classic contest keys or `other`) | entry-history download if available; else typed; best-effort guess from contest name keywords (Double Up, Triple Up, Quintuple Up, 50/50, Head-to-Head, Single Entry, Millionaire → large tournament) |
| `entry_fee`, `winnings` (nullable until known) | entry-history download, or typed |
| `place`, `field_size`, `points` (DK's official total) | standings import |
| `players` — the 9 dk_ids with slot order | standings import (lineup column parsed and matched to the slate snapshot) |
| `projected` — sum of the app's medians for those 9 players that week | slate snapshot |
| `lineup_source` — e.g. "Recommended Double Up", "Alternate #2 · Tournament", "My Lineup build", "Not from the app" | matched by comparing the 9 players to that week's published lineups (exact set match); "My Lineup build" when matched to a saved My Lineup export (see §5); otherwise "Not from the app" |
| `source_flags` — which fields were typed vs. imported | — |

**`data/history/player_weeks.parquet`** (published) — one row per player per built slate: `slate_date, dk_id, name, position, team, opp, salary, median, floor, ceiling, own_pct (est), mu_label, mu_color, actual_pts, actual_own`. Built from the slate snapshot; `actual_pts` filled from nflverse weekly stats on the next Tuesday run (offense) and from standings imports (any position incl. DST); `actual_own` only from standings imports.

The existing `data/history/results.parquet` (per-player actual ownership/points from imports) is folded into `player_weeks.parquet`; the report card reads the new file.

## 5. Flows

1. **Every build** (unchanged): the slate snapshot is archived. New: published `lineups.parquet` for that slate is archived alongside it (`data/processed/slates/<date>_<dg>_lineups.parquet`) so entries can be matched to app lineups later.
2. **My Lineup downloads** (new, local only): when Nathan downloads a My Lineup CSV on the Mac, the 9 dk_ids are appended to `data/processed/my_builds.parquet` with the date, so the entry matcher can label it "My Lineup build". (Phone downloads can't be recorded; those entries show "Not from the app".)
3. **Results import** (extended): for each standings file — existing per-player import, plus: find rows whose `EntryName` starts with `DK_USERNAME` (DraftKings appends " (2/3)" etc. for multi-entry), parse each lineup, create/update entries (keyed by `entry_id`, so re-imports update instead of duplicating). If `DK_USERNAME` is not set, skip entry creation and show "Add your DraftKings username to env.txt to track your entries" in the sidebar.
4. **Entry-history import** (new, conditional): if DraftKings' HISTORY page offers a CSV download (to be confirmed from Nathan's screenshot after Sunday), the watcher also recognizes that file and fills `entry_fee`, `winnings`, `contest_name`, `contest_type` by matching entry id (or contest id + date). If no such download exists, this flow is dropped and typing remains the money path.
5. **Tuesday run** (extended): fill `actual_pts` in `player_weeks.parquet` for last week's slate from nflverse; DST actual points computed if nflverse provides team defensive stats (verified at build time), otherwise DST actuals come only from standings imports.
6. **Mac edits**: ✏️ edit (fee, winnings, contest type) and ➕ add-by-hand (date, contest name, type, fee, winnings, optional lineup from that week's app lineups) write to `entries.parquet` atomically and run the publish step.

## 6. The My Results tab (per the approved mockup)

Order: **season totals** (entries, cashed + rate, fees, winnings, profit, ROI, avg actual vs. projected, "waiting on winnings" count) with **by-contest-type** chips → **filters** (season, contest type, lineup source) + ➕ Add entry by hand (Mac only) → **Player history** (search with suggestions, "Show: every slate / only my entries", summary tiles, week-by-week table incl. "My entry" column) → **entry log** newest first (status stripe ✅ cashed / ✗ didn't cash / 💲 add winnings, expandable 9-player box score with projected vs. actual points and est. vs. actual ownership, ✏️ edit on Mac). Hosted copy: same views, edit controls replaced by "Edit on your Mac".

## 7. Error handling

- Standings file with no rows for `DK_USERNAME`: per-player import as today; message "no entries of yours in this contest".
- Lineup players not on the archived slate (late swap, different slate): entry still created with DK's points; `projected` blank; `lineup_source` "Not from the app"; note shown.
- Duplicate imports: upsert by `entry_id`; typed fields are never overwritten by a blank import value; an imported value overwrites a typed one only for fee/winnings from the entry-history file.
- Entry-history rows that match no entry: create the entry from that row (contest, fee, winnings) with players blank, labeled "no standings imported".
- All failures loud via the existing status/banner path; nothing published contains usernames (tested).

## 8. Testing

Unit tests for: username matching incl. "(2/3)" suffixes; lineup parsing from the standings `Lineup` column; lineup-source matching; upsert/merge rules; totals/ROI/cash-rate math; contest-type guessing; player-history assembly; privacy (no `EntryName`/username in any published file). AppTest for the tab on hosted (read-only) and local (edit/add/winnings save). Browser check of the real tab on Mac and phone after deploy. Real-data check with Nathan's first finished contest (Sun Oct 18 Double Up).

## 9. Open items to verify during build

1. DraftKings standings `Lineup` column format and `EntryName` multi-entry suffix (from Nathan's first real file).
2. Whether HISTORY offers an entry-history CSV and its columns (Nathan's screenshot after Sunday).
3. nflverse team defensive stats availability for DST actual points.

## 10. As built

Deviations from the design above, as built on branch `my-results`:

- `data/history/results.parquet` (per-player standings history behind the report card) is kept alongside the new
  `data/history/player_weeks.parquet`; it was not folded into it.
- Each slate's lineups are archived in `data/processed/slate_lineups/<date>_<draft group>.parquet`, with every build
  (Thursday, Sunday 9:00, Sunday 11:45) appended under a `built_at` time and identical lineups de-duplicated, so an
  entry made from any build is recognized. Matching prefers the entry's contest type, then the latest build.
- The per-entry record of hand-typed values is the column `typed_fields` (the design called it `source_flags`).
- An unknown contest type is stored as `""` and shown as "Type not set"; the edit row offers it and saves only the
  fields Nathan changed, so blanks are never silently replaced.
- Season filter uses the NFL season (`config.season_for`): January slates belong to the previous season.
- The `tuesday` stage now publishes, so nflverse actual points reach the phone the same day.
- Bookkeeping (contest list, player history, lineup archive, actual-points fill, entry reading) can't stop a live
  stage; a failure becomes a "WARNING" note on the step.
- Deferred: importing DraftKings' entry-history CSV (open item 2) and DST actual points from nflverse (open item 3).
- Parked: **➕ Add entry by hand** has no lineup picker yet; there is no lock between app edits and a pipeline run
  writing `entries.parquet` at the same moment.
