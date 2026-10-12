# NFL DFS Lineups — User Manual

## What happens automatically each week
| When | What your Mac does |
|---|---|
| Tuesday 9:00 AM | Downloads this week's DraftKings salaries and last week's NFL stats |
| Thursday 9:00 AM | Gets Vegas lines, builds every contest type's lineups, publishes to your phone |
| Sunday 9:00 AM | Re-checks injuries and lines, rebuilds, publishes |
| Sunday 11:45 AM | Re-checks injuries after inactives are announced, rebuilds, publishes |
| Whenever a results file lands in Downloads | Imports it and updates the report card |

Your Mac must be plugged in. It wakes itself 5 minutes before each run.

## Your 2 minutes on Sunday
1. Open the app — on your phone (the Streamlit link) or on the Mac (double-click **Launch_NFL_DFS** on the Desktop).
2. Pick the **DraftKings contest type** you're entering (top of the page).
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

## If something goes wrong
- **A red banner at the top** says which step failed and what to do. Most fix themselves on the next run.
- **"DraftKings returned something other than the salary CSV"**: on draftkings.com open any main-slate
  contest, click **Export to CSV**, then in the Mac app's sidebar use **Upload DKSalaries.csv**.
- **"The Odds API request failed"**: the monthly free limit may be used up (shared with the MLB app). The app
  reuses lines up to 48 hours old automatically.
- **The phone copy didn't update**: check `logs/pipeline.log` on the Mac for the `publish` line.

## Useful commands (Terminal, in the NFL_DFS folder)
- Run a stage now: `./py run_pipeline.py --stage thursday` (or tuesday, sunday, refresh, results, build)
- Start the Mac app: `bash launch.sh`
- Turn the schedule off / on: `bash scripts/uninstall_schedule.sh` / `bash scripts/install_schedule.sh`
- Logs: `tail -50 logs/pipeline.log`, `tail -50 logs/launchagent.log`, `tail -50 logs/streamlit.log`
