#!/usr/bin/env python3
"""Weekly pipeline runner.

  ./py run_pipeline.py --stage tuesday     salaries + nflverse stats (+ actual points) + publish
  ./py run_pipeline.py --stage thursday    (salaries/stats if missing) + Vegas + build
  ./py run_pipeline.py --stage sunday      fresh salaries/statuses + Vegas + build
  ./py run_pipeline.py --stage sunday_late fresh salaries + (stale) Vegas + build + publish
  ./py run_pipeline.py --stage refresh     salaries + (missing) stats + (stale) Vegas + build + publish
  ./py run_pipeline.py --stage results     import a DraftKings standings file, report card, publish
  ./py run_pipeline.py --stage nba         NBA: today's DraftKings Classic slates + Vegas + build + publish (daily)
  ./py run_pipeline.py --stage build       rebuild from what's already downloaded
  (thursday and sunday also publish when they finish)
  add --salary-csv PATH to use a manually downloaded DKSalaries.csv
  add --results-file PATH to import one specific standings or entry-history file
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import logging
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

import nbadfs.build
import nbadfs.config as nba_config
from nbadfs import dk as nba_dk
from nbadfs import stats as nba_stats
from nbadfs import vegas as nba_vegas
from nfldfs import (build, config, dk_salaries, entries, nfl_stats, ownership, player_history, publish, results,
                    team_env, vegas)
from nfldfs.build import write_published
from nfldfs.status import RunStatus, atomic_write_parquet, atomic_write_text

log = logging.getLogger("pipeline")
LOCK_WAIT_SECONDS, LOCK_POLL_SECONDS = 15 * 60, 5


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def step_salaries(today, args) -> str:
    if args.salary_csv:
        text = Path(args.salary_csv).read_text(encoding="utf-8-sig")
        slate = {"draft_group_id": None, "contest_type_id": None, "start": None, "source": "upload"}
    else:
        lobby = dk_salaries.fetch_lobby()
        slate = dk_salaries.find_main_slate(lobby, today)
        text = dk_salaries.fetch_salary_csv(slate)
        slate["source"] = "draftkings"
    pool = dk_salaries.parse_salary_csv(text)
    slate.update(game_count=int(pool.game_id.nunique()), players=len(pool), fetched_at=_now())
    atomic_write_text(config.RAW / "dk_salaries.csv", text)
    atomic_write_parquet(pool, config.PROCESSED / "pool_base.parquet")
    atomic_write_text(config.PROCESSED / "slate.json", json.dumps(slate, indent=2))
    msg = f"{len(pool)} players, {slate['game_count']} games ({slate['source']})"
    if not args.salary_csv:
        msg += _optional("saving the contest list",
                         lambda: _save_contests(dk_salaries.lobby_contests(lobby, slate["draft_group_id"])))
    return msg


def _optional(what: str, fn) -> str:
    """Run a bookkeeping helper that must never stop a live stage; a failure becomes a warning on the step."""
    try:
        fn()
    except Exception as e:
        log.exception("%s failed", what)
        return f"; WARNING: {what} failed ({type(e).__name__})"
    return ""


def _save_contests(new: pd.DataFrame) -> None:
    if new is None or not len(new):
        return
    path = config.PROCESSED / "contests.parquet"
    cur = pd.read_parquet(path) if path.exists() else None
    merged = new if cur is None or not len(cur) else pd.concat([cur, new], ignore_index=True)
    atomic_write_parquet(merged.drop_duplicates("contest_id", keep="last").reset_index(drop=True), path)


def _archive_lineups(lineups: pd.DataFrame, path: Path, built_at: str) -> None:
    """Append this build's lineups (tagged built_at) to the slate's archive, skipping lineups already in it, so
    an entry made from any of the slate's builds (Thu, Sun 9:00, Sun 11:45) is still recognized."""
    def keyed(df):
        return {(str(k), int(r), frozenset(int(x) for x in g["dk_id"])): (b, k, r)
                for (b, k, r), g in df.groupby(["built_at", "contest_key", "rank"], sort=False)}

    new = lineups.assign(built_at=built_at)
    if path.exists():
        cur = pd.read_parquet(path)
        if "built_at" not in cur.columns:
            cur = cur.assign(built_at="")
        seen = keyed(cur)
        fresh = [grp for key, grp in keyed(new).items() if key not in seen]
        if not fresh:
            return
        idx = new.set_index(["built_at", "contest_key", "rank"]).index
        new = new[idx.isin(fresh)]
        new = pd.concat([cur, new], ignore_index=True)
    atomic_write_parquet(new.reset_index(drop=True), path)


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
    msg = f"{len(pw)} player-weeks through {pw.season.max()} week {latest}; model fit on {model['n_games']} team-games"
    filled = []

    def fill():
        wd = player_history.week_dates(sched)
        atomic_write_parquet(wd, config.PROCESSED / "week_dates.parquet")
        filled.append(fill_nflverse_actuals(pw, wd))
    warning = _optional("filling actual points", fill)
    return msg + (f"; actual points filled for {filled[0]} player-slates" if filled else "") + warning


def fill_nflverse_actuals(stats: pd.DataFrame, wd: pd.DataFrame) -> int:
    """Fill actual DK points (offense) for every archived slate whose NFL week is in the stats."""
    path = config.HISTORY / "player_weeks.parquet"
    pw = player_history.load(path)
    total = 0
    for slate_date in sorted(pw["slate_date"].unique()):
        week = player_history.week_for(wd, slate_date)
        if week is None:
            continue
        stats_week = stats[(stats["season"] == week[0]) & (stats["week"] == week[1])]
        if stats_week.empty:
            continue
        actuals = player_history.nflverse_actuals(pw[pw["slate_date"] == slate_date], stats_week)
        if len(actuals):
            total += player_history.set_actuals(path, slate_date, actuals)
    return total


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
    dg_tag = slate.get("draft_group_id") or "upload"
    atomic_write_parquet(res["pool"], config.SLATES / f"{slate_date}_{dg_tag}.parquet")
    odds = json.loads((P / "odds_meta.json").read_text()) if (P / "odds_meta.json").exists() else {}
    built_at = _now()
    meta = {**slate, "built_at": built_at,
            "built_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "n_sims": config.N_SIMS, "match_rate": res["match_rate"],
            "unmatched": res["unmatched"], "vegas_fetched_at": odds.get("fetched_at"),
            "odds_requests_remaining": odds.get("requests_remaining"),
            "slate_date": slate_date, "ownership_model_weeks": (model or {}).get("weeks")}
    write_published(res, config.PUBLISHED, meta)
    rec = res["lineups"][res["lineups"]["rank"] == 0]
    msg = (f"{rec.contest_key.nunique()} contest types built; name match rate {res['match_rate']:.0%}"
           + (f"; unmatched: {', '.join(res['unmatched'][:10])}" if res["unmatched"] else ""))
    msg += _optional("saving player history", lambda: player_history.upsert_slate(
        config.HISTORY / "player_weeks.parquet", player_history.slate_rows(res["pool"], slate_date)))
    msg += _optional("archiving lineups", lambda: _archive_lineups(
        res["lineups"], P / "slate_lineups" / f"{slate_date}_{dg_tag}.parquet", built_at))
    return msg


def _set_aside(f: Path, folder: Path) -> None:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(folder / f.name))
    except OSError:
        log.exception("couldn't move %s to %s", f, folder)


def _import_my_entries(f: Path, snap_df: pd.DataFrame, slate_date: str, dg: str) -> str:
    user = config.dk_username()
    if not user:
        return "add DK_USERNAME to env.txt to track your entries"
    mine = entries.read_my_entries(results.standings_text(f), user)
    if not len(mine):
        return "no entries of yours in this contest"
    lu_path = config.PROCESSED / "slate_lineups" / f"{slate_date}_{dg}.parquet"
    builds_path = config.PROCESSED / "my_builds.parquet"
    contests_path = config.PROCESSED / "contests.parquet"
    cid = entries.contest_id_from(f)
    contest = None
    if contests_path.exists():
        c = pd.read_parquet(contests_path)
        c = c[c["contest_id"].astype(str) == cid]
        contest = c.iloc[0].to_dict() if len(c) else None
    rows = entries.build_entry_rows(
        mine, snap_df, pd.read_parquet(lu_path) if lu_path.exists() else None,
        pd.read_parquet(builds_path) if builds_path.exists() else None, slate_date, cid, contest)
    entries.upsert_entries(config.HISTORY / "entries.parquet", rows)
    return f"{len(rows)} of your entries"


def _file_entry_history(f: Path) -> None:
    """Move an imported entry-history file to a unique name (DraftKings reuses the same file name)."""
    folder = config.RAW / "entry_history"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target, n = folder / f"entry-history-{stamp}.csv", 1
    while target.exists():
        n += 1
        target = folder / f"entry-history-{stamp}-{n}.csv"
    shutil.move(str(f), str(target))


def _import_entry_history(files: list[Path]) -> tuple[str, list[str]]:
    """Import DraftKings entry-history files (fees, winnings, place) into entries.parquet. No username needed."""
    path = config.HISTORY / "entries.parquet"
    new = updated = other = 0
    skipped = []
    for f in files:                           # one bad file must not block the others
        try:
            rows, ignored = entries.read_entry_history(f)
            known = set(entries.load_entries(path)["entry_id"])
            ids = set(rows["entry_id"])
            entries.merge_entry_history(path, rows)
            new, updated, other = new + len(ids - known), updated + len(ids & known), other + ignored
            _file_entry_history(f)
        except Exception as e:
            log.exception("entry-history file %s failed", f)
            skipped.append(f"skipped {f.name}: {type(e).__name__}: {e}")
            _set_aside(f, config.RAW / "entry_history" / "skipped")
    msg = f"entry history: {updated} entries updated, {new} new"
    if other:
        msg += f" ({other} non-Classic rows skipped)"
    return msg, skipped


def step_results(today, args) -> str:
    done = config.RAW / "standings"
    if getattr(args, "results_file", None):
        f = Path(args.results_file)
        history_files, files = ([f], []) if entries.is_entry_history(f) else ([], [f])
    else:
        files, history_files = (results.find_new_standings(config.DOWNLOADS, done),
                                entries.find_entry_history(config.DOWNLOADS))
    if not files and not history_files:
        return "skipped: no new contest-standings or entry-history file"
    msgs, problems = [], []
    if files:
        try:
            msgs.append(_import_standings(files, today, done))
        except _StandingsProblem as e:
            msgs.append(e.msg)
            problems += e.skipped
    if history_files:                         # after standings, so players exist before money fills in
        msg, skipped = _import_entry_history(history_files)
        msgs.append(msg)
        problems += skipped
    msg = "; ".join(msgs)
    if problems:
        raise RuntimeError(f"{msg}; " + "; ".join(problems))
    return msg


class _StandingsProblem(Exception):
    def __init__(self, msg, skipped):
        super().__init__(msg)
        self.msg, self.skipped = msg, skipped


def _import_standings(files: list[Path], today, done: Path) -> str:
    done.mkdir(parents=True, exist_ok=True)
    hist, slates, imported, skipped, entry_notes = None, [], [], [], []
    for f in files:                           # one bad file must not block the others
        try:
            downloaded = dt.date.fromtimestamp(f.stat().st_mtime)
            snap = results.latest_slate_snapshot(config.SLATES, min(today, downloaded))
            if snap is None:
                raise RuntimeError(f"No built slate on or before {min(today, downloaded)} to match {f.name} to — "
                                   "results can only be imported for slates this app built.")
            slate_date, dg = results.snapshot_key(snap)
            standings, snap_df = results.read_standings(f), pd.read_parquet(snap)
            share = results.match_share(standings, snap_df)
            if share < results.MIN_STANDINGS_MATCH:
                skipped.append(f"skipped {f.name}: only {share:.0%} of its players are on the {slate_date} slate "
                               "(wrong contest?)")
                _set_aside(f, done / "skipped")
                continue
            matched = results.match_to_slate(standings, snap_df, slate_date, dg)
            hist = results.append_history(config.HISTORY / "results.parquet", matched)
            try:
                player_history.set_actuals(config.HISTORY / "player_weeks.parquet", slate_date,
                                           matched[["dk_id", "actual_pts", "actual_own"]])
            except Exception as e:
                log.exception("player history actuals for %s failed", f)
                entry_notes.append(f"WARNING: actual points not saved to player history ({type(e).__name__})")
            try:
                entry_notes.append(_import_my_entries(f, snap_df, slate_date, dg))
            except Exception as e:
                log.exception("reading your entries from %s failed", f)
                entry_notes.append(f"entries not read ({type(e).__name__})")
            shutil.move(str(f), str(done / f.name))
            slates.append(slate_date)
            imported.append(f"{f.name} ({share:.0%} matched)")
        except Exception as e:
            log.exception("results file %s failed", f)
            skipped.append(f"skipped {f.name}: {type(e).__name__}: {e}")
            _set_aside(f, done / "skipped")
    msg = f"imported {len(imported)} file(s)"
    if hist is not None:
        card = results.report_card(hist)
        atomic_write_text(config.PUBLISHED / "report_card.json", json.dumps(card, indent=2))
        model = ownership.fit_ownership_model(hist)
        if model:
            atomic_write_text(config.PROCESSED / "ownership_model.json", json.dumps(model, indent=2))
        msg += (f" for the {', '.join(sorted(set(slates)))} slate ({', '.join(imported)}); "
                f"{card['weeks']} week(s) of results" + ("; ownership model updated" if model else ""))
    if entry_notes:
        msg += "; " + "; ".join(sorted(set(entry_notes)))
    if skipped:
        raise _StandingsProblem(msg, skipped)
    return msg


def _new_results_waiting() -> bool:
    try:
        return bool(results.find_new_standings(config.DOWNLOADS, config.RAW / "standings")
                    or entries.find_entry_history(config.DOWNLOADS))
    except Exception:
        return True                           # let step_results record the error (e.g. PermissionError) loudly


# ── NBA (separate files under data/*/nba; shares the pipeline lock) ──────────────────────────────────────
NO_NBA_SLATE = "skipped: no NBA Classic slate today"


def _nba_today(args, today) -> dt.date:
    """The slate date is the America/New_York date (the machine clock may be elsewhere)."""
    if args.today:
        return today
    return dt.datetime.now(nba_vegas.ET).date()


def nba_season_years(day: dt.date) -> tuple[int, int]:
    """(current, last) season end years: the season ending next calendar year from July on."""
    cur = day.year + 1 if day.month >= 7 else day.year
    return cur, cur - 1


def _nba_slates() -> list[dict]:
    p = nba_config.PROCESSED_NBA / "slates.json"
    return json.loads(p.read_text()) if p.exists() else []


def _nba_salary_path(day: dt.date, dg) -> Path:
    return nba_config.RAW_NBA / day.isoformat() / f"salaries_{dg}.csv"


_NBA_RUN = {"idle_off_day": False}     # set by the salaries step: no slate today AND none yesterday's run either


def step_nba_salaries(today, args) -> str:
    day = _nba_today(args, today)
    _NBA_RUN["idle_off_day"] = False
    slates = nba_dk.classic_slates(nba_dk.fetch_lobby(), day)
    warnings, ok = "", []
    for s in slates:
        try:
            atomic_write_text(_nba_salary_path(day, s["draft_group_id"]), nba_dk.fetch_salary_csv(s["draft_group_id"]))
            ok.append(s)
        except Exception as e:
            s["downloaded"] = False               # stays listed (published false) so the app knows it exists
            warnings += f"; WARNING: {s['name']} salaries not downloaded ({type(e).__name__})"
    atomic_write_text(nba_config.PROCESSED_NBA / "slates.json", json.dumps(slates, indent=2))
    if not slates:
        pub = nba_config.PUBLISHED_NBA / "slates.json"
        _NBA_RUN["idle_off_day"] = pub.exists() and pub.read_text().strip() in ("[]", "")
        atomic_write_text(pub, "[]")
        return NO_NBA_SLATE
    if slates and not ok:
        raise RuntimeError("no NBA salary file could be downloaded" + warnings)
    return (f"{len(slates)} NBA Classic slate(s): " + ", ".join(f"{s['name']} ({s['games']} games)" for s in slates)
            + warnings)


def _nba_odds_path() -> Path:
    return nba_config.PROCESSED_NBA / "odds.json"


def step_nba_vegas_if_stale(today, args) -> str:
    if not _nba_slates():
        return NO_NBA_SLATE
    path = _nba_odds_path()
    now = dt.datetime.now()
    if nba_vegas.lines_fresh(path, now, nba_config.ODDS_MAX_AGE_MIN):
        age = (now.timestamp() - path.stat().st_mtime) / 60
        return f"skipped: lines fetched {age:.0f} min ago"
    try:
        events, remaining = nba_vegas.fetch_odds(config.odds_api_key())
    except Exception as e:                        # lines are optional: build with cached odds, or league-average
        return f"WARNING: NBA lines not refreshed ({type(e).__name__})"
    atomic_write_text(path, json.dumps({"fetched_at": _now(), "requests_remaining": remaining, "events": events}))
    return f"{len(events)} NBA games listed; Odds API requests remaining: {remaining}"


def step_nba_stats_if_missing(today, args) -> str:
    if not _nba_slates():
        return NO_NBA_SLATE
    cur, last = nba_season_years(_nba_today(args, today))
    stale = []
    for y in (cur, last):
        p = nba_stats.download_season(y, nba_config.RAW_NBA / "stats")
        if isinstance(p, Path) and time.time() - p.stat().st_mtime >= nba_stats.MAX_AGE_H * 3600:
            stale.append(y)
    msg = f"season stats {last} and {cur} ready"
    if stale:
        log.warning("NBA season stats %s could not be refreshed; using cached copies", stale)
        msg += f"; WARNING: season stats {', '.join(map(str, stale))} not refreshed (using the cached copy)"
    return msg


def _nba_rates(year: int) -> pd.DataFrame:
    return nba_stats.player_rates(pd.read_parquet(nba_config.RAW_NBA / "stats" / f"player_season_stats_{year}.parquet"))


def _prune_nba_published(keep) -> None:
    """Delete per-slate folders (all-digit names) whose draft-group id isn't in `keep`; DK ids change daily."""
    keep = {str(k) for k in keep}
    root = nba_config.PUBLISHED_NBA
    if not root.is_dir():
        return
    for d in root.iterdir():
        if d.is_dir() and d.name.isdigit() and d.name not in keep:
            shutil.rmtree(d, ignore_errors=True)


def _built_today(dg, day: dt.date) -> bool:
    """True when this slate's published folder already holds a build made for `day` (e.g. this afternoon's)."""
    p = nba_config.PUBLISHED_NBA / str(dg) / "build_meta.json"
    try:
        return json.loads(p.read_text()).get("slate_date") == day.isoformat()
    except (OSError, ValueError):
        return False


def step_nba_build(today, args) -> str:
    slates = _nba_slates()
    if not slates:
        _prune_nba_published(())
        return NO_NBA_SLATE
    day = _nba_today(args, today)
    odds_p = _nba_odds_path()
    odds = json.loads(odds_p.read_text()) if odds_p.exists() else {"events": [], "requests_remaining": None}
    lines = nba_vegas.team_lines(odds["events"], day)
    cur, last = nba_season_years(day)
    rates_cur, rates_last = _nba_rates(cur), _nba_rates(last)
    flags, warnings, built = [], "", 0
    for s in slates:
        dg = s["draft_group_id"]
        if s.get("downloaded") is False:
            flags.append({**s, "published": _built_today(dg, day)})
            continue
        try:
            res = nbadfs.build.build_slate(_nba_salary_path(day, dg).read_text(encoding="utf-8-sig"), lines,
                                           rates_last, rates_cur)
            res["meta"].update(draft_group_id=dg, name=s["name"], start=s["start"], games=s["games"],
                               odds_remaining=odds.get("requests_remaining"), slate_date=day.isoformat())
            nbadfs.build.write_published(res, nba_config.PUBLISHED_NBA / str(dg))
            flags.append({**s, "published": True})
            built += 1
        except Exception as e:
            log.exception("NBA slate %s failed", s["name"])
            warnings += f"; WARNING: {s['name']} not built ({type(e).__name__})"
            flags.append({**s, "published": _built_today(dg, day)})
    atomic_write_text(nba_config.PUBLISHED_NBA / "slates.json", json.dumps(flags, indent=2))
    _prune_nba_published(s["draft_group_id"] for s in slates)
    return f"{built} of {len(slates)} NBA slate(s) built{warnings}"


def step_publish(today, args) -> str:
    if args.stage == "nba" and _NBA_RUN["idle_off_day"]:
        return "skipped: nothing new to publish"      # still no NBA slate: don't commit run_status.json churn
    return publish.publish(config.ROOT, ["data/published", "data/history"], f"Slate update: {args.stage} {today}")


STAGES = {
    "tuesday": ["salaries", "stats", "publish"],
    "thursday": ["salaries_if_stale", "stats_if_missing", "vegas", "build", "publish"],
    "sunday": ["salaries", "stats_if_missing", "vegas", "build", "publish"],
    "sunday_late": ["salaries", "vegas_if_stale", "build", "publish"],
    "refresh": ["salaries", "stats_if_missing", "vegas_if_stale", "build", "publish"],
    "results": ["results", "publish"],
    "build": ["build"],
    "nba": ["nba_salaries", "nba_vegas_if_stale", "nba_stats_if_missing", "nba_build", "publish"],
}
STEP_FUNCS = {
    "salaries": step_salaries, "salaries_if_stale": step_salaries_if_stale,
    "stats": step_stats, "stats_if_missing": step_stats_if_missing,
    "vegas": step_vegas, "vegas_if_stale": step_vegas_if_stale, "build": step_build,
    "results": step_results, "publish": step_publish,
    "nba_salaries": step_nba_salaries, "nba_vegas_if_stale": step_nba_vegas_if_stale,
    "nba_stats_if_missing": step_nba_stats_if_missing, "nba_build": step_nba_build,
}


def _acquire_lock(wait: bool):
    """Exclusive lock on data/.pipeline.lock so two runs never write the same files at once."""
    config.DATA.mkdir(parents=True, exist_ok=True)
    f = open(config.DATA / ".pipeline.lock", "w")
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except BlockingIOError:
            if not wait or time.monotonic() >= deadline:
                f.close()
                return None
            time.sleep(LOCK_POLL_SECONDS)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--salary-csv", help="use a manually downloaded DKSalaries.csv")
    ap.add_argument("--results-file", help="import one DraftKings contest-standings or entry-history file")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD), for testing")
    args = ap.parse_args(argv)
    if args.stage not in STAGES:
        ap.error(f"--stage must be one of {sorted(STAGES)}")
    config.LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True,
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(config.LOGS / "pipeline.log")])
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    lock = _acquire_lock(wait=args.stage != "results")
    if lock is None:
        if args.stage == "results":
            log.info("results: another pipeline run is in progress — will retry on the next Downloads change")
            return 0
        log.error("Another pipeline run has been going for over %d minutes, so the %s run was not started. "
                  "Try again later.", LOCK_WAIT_SECONDS // 60, args.stage)
        return 1
    try:
        return _run(args, today)
    finally:
        lock.close()


def _run(args, today) -> int:
    if args.stage == "results" and not args.results_file and not _new_results_waiting():
        log.info("results: no new contest-standings or entry-history file — nothing to do")   # keep the last import's status
        return 0
    if args.stage == "nba":                   # NBA never touches the NFL run_status.json
        status_path = nba_config.PUBLISHED_NBA / "run_status.json"
    else:
        status_path = config.PUBLISHED / ("results_status.json" if args.stage == "results" else "run_status.json")
    status = RunStatus(status_path, args.stage)
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
