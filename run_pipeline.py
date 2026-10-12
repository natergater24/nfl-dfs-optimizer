#!/usr/bin/env python3
"""Weekly pipeline runner.

  ./py run_pipeline.py --stage tuesday     salaries + nflverse stats
  ./py run_pipeline.py --stage thursday    (salaries/stats if missing) + Vegas + build
  ./py run_pipeline.py --stage sunday      fresh salaries/statuses + Vegas + build
  ./py run_pipeline.py --stage sunday_late fresh salaries + (stale) Vegas + build + publish
  ./py run_pipeline.py --stage refresh     salaries + (missing) stats + (stale) Vegas + build + publish
  ./py run_pipeline.py --stage results     import a DraftKings standings file, report card, publish
  ./py run_pipeline.py --stage build       rebuild from what's already downloaded
  (thursday and sunday also publish when they finish)
  add --salary-csv PATH to use a manually downloaded DKSalaries.csv
  add --results-file PATH to import one specific standings file
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import shutil
import sys
from pathlib import Path

import pandas as pd

from nfldfs import build, config, dk_salaries, nfl_stats, ownership, publish, results, team_env, vegas
from nfldfs.build import write_published
from nfldfs.status import RunStatus, atomic_write_parquet, atomic_write_text

log = logging.getLogger("pipeline")


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def step_salaries(today, args) -> str:
    if args.salary_csv:
        text = Path(args.salary_csv).read_text(encoding="utf-8-sig")
        slate = {"draft_group_id": None, "contest_type_id": None, "start": None, "source": "upload"}
    else:
        slate = dk_salaries.find_main_slate(dk_salaries.fetch_lobby(), today)
        text = dk_salaries.fetch_salary_csv(slate)
        slate["source"] = "draftkings"
    pool = dk_salaries.parse_salary_csv(text)
    slate.update(game_count=int(pool.game_id.nunique()), players=len(pool), fetched_at=_now())
    atomic_write_text(config.RAW / "dk_salaries.csv", text)
    atomic_write_parquet(pool, config.PROCESSED / "pool_base.parquet")
    atomic_write_text(config.PROCESSED / "slate.json", json.dumps(slate, indent=2))
    return f"{len(pool)} players, {slate['game_count']} games ({slate['source']})"


def _salaries_current(today) -> bool:
    p = config.PROCESSED / "pool_base.parquet"
    return p.exists() and pd.read_parquet(p).kickoff.max().date() >= today


def step_salaries_if_stale(today, args) -> str:
    if not args.salary_csv and _salaries_current(today):
        return "skipped: this week's salaries are already downloaded"
    return step_salaries(today, args)


def step_stats(today, args) -> str:
    season = config.season_for(today)
    raw, sched = nfl_stats.load_raw(list(range(season - config.STATS_SEASONS_BACK, season + 1)))
    pw = nfl_stats.normalize_player_stats(raw)
    tw = nfl_stats.team_week_totals(pw)
    sched_rows = nfl_stats.normalize_schedules(sched)
    model = team_env.fit_team_model(team_env.build_training_frame(tw, sched_rows))
    atomic_write_parquet(pw, config.PROCESSED / "player_weeks.parquet")
    atomic_write_parquet(tw, config.PROCESSED / "team_weeks.parquet")
    atomic_write_parquet(sched_rows, config.PROCESSED / "schedule_rows.parquet")
    atomic_write_text(config.PROCESSED / "team_model.json", json.dumps(model, indent=2))
    latest = pw[pw.season == pw.season.max()].week.max()
    return f"{len(pw)} player-weeks through {pw.season.max()} week {latest}; model fit on {model['n_games']} team-games"


def step_stats_if_missing(today, args) -> str:
    needed = [config.PROCESSED / f for f in ("player_weeks.parquet", "team_weeks.parquet", "team_model.json",
                                                    "schedule_rows.parquet")]
    pw_path = config.PROCESSED / "player_weeks.parquet"
    if all(p.exists() for p in needed):
        # Tuesday is when the week's games are complete and the scheduled refresh runs.
        last_tuesday = today - dt.timedelta(days=(today.weekday() - 1) % 7)
        cutoff = dt.datetime.combine(last_tuesday, dt.time.min).timestamp()
        if pw_path.stat().st_mtime >= cutoff:
            pw = pd.read_parquet(pw_path, columns=["season", "week"])
            season = int(pw.season.max())
            return f"skipped: stats current through {season} week {int(pw[pw.season == season].week.max())}"
    return step_stats(today, args)


def _odds_age_hours() -> float | None:
    p = config.PROCESSED / "odds_meta.json"
    if not p.exists():
        return None
    fetched = json.loads(p.read_text()).get("fetched_at")
    if not fetched:
        return None
    return (dt.datetime.now() - dt.datetime.fromisoformat(fetched)).total_seconds() / 3600


def step_vegas(today, args) -> str:
    try:
        events, remaining = vegas.fetch_odds(config.odds_api_key())
    except RuntimeError as e:
        age = _odds_age_hours()
        if age is not None and age <= config.VEGAS_FALLBACK_HOURS and \
                (config.PROCESSED / "vegas_games.parquet").exists():
            return f"WARNING: {e} Reusing lines fetched {age:.0f}h ago."
        raise
    games = vegas.parse_odds(events)
    atomic_write_parquet(games, config.PROCESSED / "vegas_games.parquet")
    atomic_write_text(config.PROCESSED / "odds_meta.json",
                      json.dumps({"fetched_at": _now(), "requests_remaining": remaining}, indent=2))
    return f"{len(games)} games with lines; Odds API requests remaining: {remaining}"


def step_vegas_if_stale(today, args) -> str:
    age = _odds_age_hours()
    if age is not None and age < config.VEGAS_REUSE_HOURS and (config.PROCESSED / "vegas_games.parquet").exists():
        return f"skipped: lines fetched {age * 60:.0f} min ago"
    return step_vegas(today, args)


def step_build(today, args) -> str:
    P = config.PROCESSED
    sched_path = P / "schedule_rows.parquet"
    model_path = P / "ownership_model.json"
    model = json.loads(model_path.read_text()) if model_path.exists() else None
    res = build.build_slate(
        pd.read_parquet(P / "pool_base.parquet"), pd.read_parquet(P / "player_weeks.parquet"),
        pd.read_parquet(P / "team_weeks.parquet"), json.loads((P / "team_model.json").read_text()),
        pd.read_parquet(P / "vegas_games.parquet"), n_sims=config.N_SIMS, seed=config.SEED,
        n_candidates=config.N_CANDIDATES, field_size=config.FIELD_SIZE,
        schedule_rows=pd.read_parquet(sched_path) if sched_path.exists() else None,
        ownership_model=model)
    slate = json.loads((P / "slate.json").read_text())
    slate_date = str(pd.read_parquet(P / "pool_base.parquet", columns=["kickoff"]).kickoff.min().date())
    atomic_write_parquet(res["pool"], config.SLATES / f"{slate_date}_{slate.get('draft_group_id') or 'upload'}.parquet")
    odds = json.loads((P / "odds_meta.json").read_text()) if (P / "odds_meta.json").exists() else {}
    meta = {**slate, "built_at": _now(),
            "built_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "n_sims": config.N_SIMS, "match_rate": res["match_rate"],
            "unmatched": res["unmatched"], "vegas_fetched_at": odds.get("fetched_at"),
            "odds_requests_remaining": odds.get("requests_remaining"),
            "slate_date": slate_date, "ownership_model_weeks": (model or {}).get("weeks")}
    write_published(res, config.PUBLISHED, meta)
    rec = res["lineups"][res["lineups"]["rank"] == 0]
    return (f"{rec.contest_key.nunique()} contest types built; name match rate {res['match_rate']:.0%}"
            + (f"; unmatched: {', '.join(res['unmatched'][:10])}" if res["unmatched"] else ""))


def step_results(today, args) -> str:
    done = config.RAW / "standings"
    files = ([Path(args.results_file)] if getattr(args, "results_file", None)
             else results.find_new_standings(config.DOWNLOADS, done))
    if not files:
        return "skipped: no new contest-standings file"
    done.mkdir(parents=True, exist_ok=True)
    hist, slates = None, []
    for f in files:
        downloaded = dt.date.fromtimestamp(f.stat().st_mtime)
        snap = results.latest_slate_snapshot(config.SLATES, min(today, downloaded))
        if snap is None:
            raise RuntimeError(f"No built slate on or before {min(today, downloaded)} to match {f.name} to — "
                               "results can only be imported for slates this app built.")
        slate_date, dg = results.snapshot_key(snap)
        rows = results.match_to_slate(results.read_standings(f), pd.read_parquet(snap), slate_date, dg)
        hist = results.append_history(config.HISTORY / "results.parquet", rows)
        shutil.move(str(f), str(done / f.name))
        slates.append(slate_date)
    card = results.report_card(hist)
    atomic_write_text(config.PUBLISHED / "report_card.json", json.dumps(card, indent=2))
    model = ownership.fit_ownership_model(hist)
    if model:
        atomic_write_text(config.PROCESSED / "ownership_model.json", json.dumps(model, indent=2))
    return (f"imported {len(files)} file(s) for the {', '.join(sorted(set(slates)))} slate; "
            f"{card['weeks']} week(s) of results" + ("; ownership model updated" if model else ""))


def step_publish(today, args) -> str:
    return publish.publish(config.ROOT, ["data/published", "data/history"], f"Slate update: {args.stage} {today}")


STAGES = {
    "tuesday": ["salaries", "stats"],
    "thursday": ["salaries_if_stale", "stats_if_missing", "vegas", "build", "publish"],
    "sunday": ["salaries", "stats_if_missing", "vegas", "build", "publish"],
    "sunday_late": ["salaries", "vegas_if_stale", "build", "publish"],
    "refresh": ["salaries", "stats_if_missing", "vegas_if_stale", "build", "publish"],
    "results": ["results", "publish"],
    "build": ["build"],
}
STEP_FUNCS = {
    "salaries": step_salaries, "salaries_if_stale": step_salaries_if_stale,
    "stats": step_stats, "stats_if_missing": step_stats_if_missing,
    "vegas": step_vegas, "vegas_if_stale": step_vegas_if_stale, "build": step_build,
    "results": step_results, "publish": step_publish,
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--salary-csv", help="use a manually downloaded DKSalaries.csv")
    ap.add_argument("--results-file", help="import one DraftKings contest-standings file")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD), for testing")
    args = ap.parse_args(argv)
    if args.stage not in STAGES:
        ap.error(f"--stage must be one of {sorted(STAGES)}")
    config.LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True,
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(config.LOGS / "pipeline.log")])
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    status_file = "results_status.json" if args.stage == "results" else "run_status.json"
    status = RunStatus(config.PUBLISHED / status_file, args.stage)
    ok = True
    steps = STAGES[args.stage]
    for name in [n for n in steps if n != "publish"]:
        log.info("── %s ──", name)
        try:
            with status.step(name) as rec:
                rec["message"] = STEP_FUNCS[name](today, args) or ""
            log.info("%s ok: %s", name, rec["message"])
        except Exception:
            log.exception("%s failed — stopping this run", name)
            ok = False
            break
    status.finish(ok)
    if "publish" in steps:                    # after finish, so the committed status is final (even on failure)
        try:
            msg = STEP_FUNCS["publish"](today, args) or ""
        except Exception as e:
            msg = f"WARNING: publishing failed — {type(e).__name__}"
        log.info("publish: %s", msg)
        status.data["publish"] = msg
        status._write()                       # local-only record of the publish outcome
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
