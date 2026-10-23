# NFL DFS Lineups — User Manual

## One-time setup (already done if Claude set it up with you)
Run these in Terminal, in the NFL_DFS folder:
1. Turn on the weekly schedule: `bash scripts/install_schedule.sh`
2. Let the Mac wake itself before each run: `sudo pmset repeat wakeorpoweron TRU 08:55:00` (it asks for your
   Mac password). Check it with `pmset -g sched`; stop it with `sudo pmset repeat cancel`.
3. Let the app read your Downloads folder. If the sidebar ever says **"Results import failed: PermissionError"**:
   open **System Settings → Privacy & Security → Full Disk Access**, click **+**, press **⌘⇧G**, paste
   `/Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app`, click **Open**, then switch it on.
4. Stay logged in on the Mac and keep it plugged in — scheduled runs only happen while you're logged in.
5. For My Results, add one line to `env.txt`: `DK_USERNAME=<your DraftKings username>`. The app shows a reminder
   in the sidebar if it's missing. The username stays on your Mac and is never published.
6. The Mac app keeps the Mac awake while it's open. Quit it when you're done: **Ctrl+C** in its Terminal
   window, or run `pkill -f "streamlit run app.py"`.

## What happens automatically each week
| When | What your Mac does |
|---|---|
| Tuesday 9:00 AM | Downloads this week's DraftKings salaries and last week's NFL stats, fills in last week's actual points, publishes to your phone |
| Thursday 9:00 AM | Gets Vegas lines, builds every contest type's lineups, publishes to your phone |
| Sunday 9:00 AM | Re-checks injuries and lines, rebuilds, publishes |
| Sunday 11:45 AM | Re-checks injuries after inactives are announced, rebuilds, publishes |
| Whenever a results file lands in Downloads | Imports it and updates the report card |

Your Mac must be plugged in. It wakes itself 5 minutes before each run.

## Your 2 minutes on Sunday
1. Open the app — on your phone (https://nfl-dfs-optimizer.streamlit.app/) or on the Mac (double-click **Launch_NFL_DFS** on the Desktop).
2. In the DraftKings app choose **Classic** and the **Sunday 1:00 PM main slate**, then pick the matching **Classic contest type** in this app (top of the page). Showdown Captain Mode, Tiers, Pick6 and other game styles aren't supported yet.
3. Use the ⭐ **Recommended** lineup, or build your own in 🛠 **My Lineup**.
4. Click **Download** and upload that CSV on DraftKings (Lineups → Upload Lineups).

## Building your own lineup (🛠 My Lineup)
- Click a slot on the left → the right side shows who can fill it. Click a player to swap him in.
- Or click a player on the right → slots he can't fill turn gray. Click a highlighted slot.
- Or drag a player onto a slot. On a phone, tap instead of dragging.
- The salary bar turns red over $50,000 and the download button turns off until you fix it.

## What the colors and labels mean
Open **ℹ️ Key** in the app. Short version: 🔥 Chalk = most people have him; 💎 Contrarian = few do.
Green matchup = soft defense, red = tough defense.

## After Sunday's games (optional, 2 clicks)
Follow **📥 How to import last week's results** in the app's sidebar. The 📈 report card then shows how
close the projections were. After 3 imported weeks, ownership estimates start learning from your results.

## 📒 My Results
The **📒 My Results** tab keeps a record of your contest entries and how each player did.

**What fills in by itself.** After you export a contest's standings (the sidebar import guide), the app finds your
entries and fills in the place, your points, which app lineup it was (if any), and actual vs. projected points.
An entry made from any of the slate's builds (Thursday, Sunday 9:00 or Sunday 11:45) is recognized, even if a
later rebuild changed the lineup. If the app saw that contest in the DraftKings lobby, the entry fee and contest
name fill in too. If it can't tell the contest type, the entry shows **Type not set**.

**Fees and winnings.** Download your **entry history** from DraftKings (`draftkings-contest-entry-history.csv`, from
the same My Contests page's history view). It imports by itself from Downloads, in either order with the standings,
and fills in fee, winnings, place and points for every NFL Classic entry. DraftKings' numbers replace anything you
typed for fee and winnings.

**Typing winnings (Mac only, the fallback).** If you don't have the entry history yet, open the entry, fill the
boxes (winnings, and entry fee or contest type if they're blank), then **Save**. Only the boxes you change are saved; a
blank fee or a **Type not set** you leave alone stays blank. If saving worked but the phone copy couldn't be
updated, you'll see a yellow warning instead of the green "Saved". A 💲 marks entries still waiting on winnings.
For a contest you didn't export, use **➕ Add entry by hand**.

**My Lineup downloads.** Lineups you download from 🛠 My Lineup on the Mac are remembered, so those entries show
**My Lineup build**. Downloads made on your phone can't be remembered.

**Player history.** Pick a player to see his weeks. **Every slate the app projected** shows all weeks; **Only my
entries** shows just weeks you played him. Actual points fill in after the Tuesday run (which also publishes
them to your phone); actual ownership fills in after a standings import.

**Season filter.** Seasons are NFL seasons: games in January (weeks 17-18) count toward the season that started
the previous September.

**On your phone** My Results is read-only and says "Edit on your Mac".

## If a scheduled run was missed
- **Best setup on run mornings (Tue/Thu/Sun):** Mac plugged in, or at least with the lid open. Each run keeps the
  Mac awake while it works, even on battery, but a closed lid on battery forces sleep and the run crawls along in
  short bursts (in October a 2-minute build took 3½ hours that way).
- **Mac asleep:** the missed run happens as soon as it wakes.
- **Mac off or logged out:** the run doesn't happen.
- Each later run catches up: Thursday covers a missed Tuesday, Sunday 9:00 covers a missed Thursday, and
  Sunday 11:45 covers a missed 9:00.
- **How to notice:** look at the header. **Last refreshed** shows when the lineups were last built; its color is
  green under 1 hour old, orange under 1 day, red older. **Next automatic refresh** shows when the next run is due.
- **What to do on the Mac:** open the app (double-click **Launch_NFL_DFS** on the Desktop) and click
  **⟳ Refresh data now**. Or in Terminal, in the NFL_DFS folder: `./py run_pipeline.py --stage sunday`
- **On the phone:** **🔄 Get latest** only loads what the Mac has already published. If the time is still old,
  check injuries yourself before entering.

## If something goes wrong
- **A red banner at the top** says which step failed and what to do. Most fix themselves on the next run.
- **"DraftKings returned something other than the salary CSV"**: on draftkings.com open any main-slate
  contest, click **Export to CSV**, then in the Mac app's sidebar use **Upload DKSalaries.csv**.
- **"The Odds API request failed"**: the monthly free limit may be used up (shared with the MLB app). The app
  reuses lines up to 48 hours old automatically.
- **"Results import failed: PermissionError"**: the Mac can't read your Downloads folder — follow step 3 of
  **One-time setup** above, then click **Check for results**.
- **"skipped … (wrong contest?)"**: that results file wasn't from the Sunday main slate (e.g. a showdown or
  another week). It was moved to `data/raw/standings/skipped`. Export last Sunday's **main-slate** contest
  instead.
- **The phone copy didn't update**: check `logs/pipeline.log` on the Mac for the `publish` line.

## Useful commands (Terminal, in the NFL_DFS folder)
- Run a stage now: `./py run_pipeline.py --stage thursday` (or tuesday, sunday, refresh, results, build)
- Start the Mac app: `bash launch.sh`
- Turn the schedule off / on: `bash scripts/uninstall_schedule.sh` / `bash scripts/install_schedule.sh`
- Logs: `tail -50 logs/pipeline.log`, `tail -50 logs/launchagent.log`, `tail -50 logs/streamlit.log`
