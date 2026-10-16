# My Results (Entry Tracker & Player History) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 📒 My Results tab that tracks Nathan's own DraftKings Classic entries (auto-detected from contest-standings exports, money typed on the Mac when not importable) and a week-by-week player history search.

**Architecture:** Two new engine modules — `nfldfs/entries.py` (find Nathan's rows in a standings file by `DK_USERNAME`, link each to the app lineup it came from, upsert/edit entries, totals) and `nfldfs/player_history.py` (per-slate projection rows + actual points/ownership, search). The pipeline archives each slate's lineups and lobby contest info, fills actual points from nflverse on Tuesdays and from standings on import, and publishes `data/history/entries.parquet` + `data/history/player_weeks.parquet` (no usernames). The app gains `view_results.py` (read-only on the phone; edit/add on the Mac) and records My Lineup downloads so entries built in the builder are recognized.

**Tech Stack:** Python 3.14 via `./py`, pandas 3, Streamlit 1.58 (`st.testing.v1.AppTest`), existing `nfldfs`/`nfldfs_app` packages.

**Spec:** `docs/superpowers/specs/2026-10-16-my-results-design.md` · Mockup (layout binding): `docs/mockups/my-results-tab.html`

## Global Constraints

- Run Python only via `./py`. App code must stay Python 3.12-compatible (Streamlit Cloud).
- **No DraftKings username may ever be written to `data/published/` or `data/history/`** (Nathan's or anyone's). `DK_USERNAME` is read only from git-ignored `env.txt` via `config.dk_username()`; never logged, printed or stored.
- No DraftKings login automation. Data arrives only from files Nathan downloads.
- Editing (typed fee/winnings/type, manual entries, recording My Lineup downloads) works only on the Mac app; the hosted copy is read-only.
- Typed values are never overwritten by an import; a blank imported value never erases anything.
- Full-dollar money formatting (`$7,500`, `+$25`, `−$10`); Classic contest labels from `config.CONTEST_TYPES`.
- Atomic writes for every file the app or pipeline reads (`nfldfs.status.atomic_*`).
- Tests: `./py -m pytest -q -W error` green after every task; never run real pipeline stages against the network, `publish()` on the real repo, launch/install scripts, launchctl or pmset in tests.
- Commit trailer: `Co-Authored-By: <model> <noreply@anthropic.com>`.

## Review Focus

1. **A multi-entry contest** (`natergater24 (1/3)`, `(2/3)`, …, any capitalization) must produce one entry per row → Task 1 `test_read_my_entries_multi_entry_case_insensitive`.
2. **A lineup with a late-swapped or unknown player** must still create the entry (DK points, place) with projected blank and "Not from the app" → Task 1 `test_build_entry_rows_unknown_player`.
3. **Re-importing the same contest after typing winnings** must keep the typed winnings and update imported fields → Task 1 `test_upsert_keeps_typed_and_ignores_blanks`.
4. **The cash lineups are identical across H2H/50-50/Double Up**, so a Double Up entry must be labeled "Recommended Double Up", not "Recommended Head-to-Head" → Task 1 `test_lineup_source_prefers_entry_contest_type`.
5. **Privacy end to end:** after a results import containing other users and Nathan, no username appears in any file under `data/history/` or `data/published/` → Task 3 `test_results_import_creates_entries_without_usernames`.

---

## File Structure

```
nfldfs/
  entries.py          NEW  entry detection, lineup matching, upsert/edit/add, totals (Task 1)
  player_history.py   NEW  per-slate player rows, actuals, week mapping, search (Task 2)
  results.py          + standings_text(path) shared reader (Task 1)
  dk_salaries.py      + lobby_contests(lobby, draft_group_id) (Task 1)
  config.py           + dk_username() (Task 1)
run_pipeline.py       salaries saves contests; build archives lineups + player rows; stats fills actuals + week dates;
                      results creates entries + standings actuals (Task 3)
nfldfs_app/
  data.py             AppData.entries / AppData.player_weeks from data/history (Task 4)
  actions.py          record_my_build, save_entry_edit, add_entry (Task 4)
  view_builder.py     My Lineup download records the build on the Mac (Task 4)
  ui.py               + styled_player_history (Task 5)
  view_results.py     NEW  📒 My Results tab (Task 5)
  view_sidebar.py     + DK_USERNAME reminder on the Mac (Task 5)
app.py                + 4th tab (Task 5)
data/history/entries.parquet, player_weeks.parquet        published (no usernames)
data/processed/contests.parquet, slate_lineups/, my_builds.parquet, week_dates.parquet   local
```

---

### Task 1: `entries.py` — find, link, store and total Nathan's entries

**Files:**
- Create: `nfldfs/entries.py`, `tests/test_entries.py`
- Modify: `nfldfs/results.py` (extract `standings_text`), `nfldfs/dk_salaries.py` (`lobby_contests`), `nfldfs/config.py` (`dk_username`), `tests/test_dk_salaries.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `results.standings_text(path) -> str` (the CSV text of a standings zip/csv; `read_standings` uses it); `dk_salaries.lobby_contests(lobby, draft_group_id) -> DataFrame[contest_id(str), contest_name, entry_fee(float), max_entries(int)]`; `config.dk_username() -> str | None`.
- Produces in `entries`: `ENTRY_COLUMNS`, `EDITABLE`, `empty_entries()`, `load_entries(path)`, `contest_id_from(path) -> str`, `guess_contest_type(name, field_size=None) -> str` (a `CONTEST_TYPES` key or `""`), `parse_lineup(text) -> list[(slot, name)]`, `read_my_entries(text, username) -> DataFrame[entry_id, place, points, lineup, field_size]` (no usernames), `match_lineup_ids(pairs, snapshot) -> list[int | None]`, `lineup_source(ids, slate_lineups, my_builds=None, prefer="") -> str`, `build_entry_rows(mine, snapshot, slate_lineups, my_builds, slate_date, contest_id, contest=None) -> DataFrame[ENTRY_COLUMNS]`, `upsert_entries(path, new) -> DataFrame`, `update_entry(path, entry_id, **fields) -> DataFrame`, `add_manual_entry(path, *, slate_date, contest_name, contest_type, entry_fee, winnings, players="", projected=nan, lineup_source="Not from the app") -> DataFrame`, `summary(entries) -> dict`, `summary_by_type(entries) -> list[dict]`.

DraftKings standings rows (entry block): `Rank, EntryId, EntryName, TimeRemaining, Points, Lineup`; `EntryName` is the username, with ` (k/n)` appended for multi-entry; `Lineup` is slot tokens followed by player names, e.g. `DST Panthers FLEX Ashton Jeanty QB Josh Allen RB Jaylen Warren …` (format re-checked against Nathan's real file in Task 6).

- [x] **Step 1: Write the failing tests** — `tests/test_entries.py`:

```python
import math

import numpy as np
import pandas as pd
import pytest

from nfldfs import entries as ent
from tests.conftest import make_pool

LINEUP_A = ("DST BBB DST1 FLEX AAA RB2 QB AAA QB1 RB AAA RB1 RB BBB RB1 TE AAA TE1 "
            "WR AAA WR1 WR AAA WR2 WR BBB WR1")
LINEUP_B = ("DST BBB DST1 FLEX AAA RB3 QB AAA QB1 RB AAA RB1 RB BBB RB1 TE AAA TE1 "
            "WR AAA WR1 WR AAA WR2 WR Somebody Else")
CSV = ("Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS\n"
       f"1,9001,someoneelse,0,150.5,{LINEUP_A},,AAA QB1,QB,40.00%,25.1\n"
       f"2,9002,natergater24 (1/2),0,140.1,{LINEUP_A},,AAA WR1,WR,12.50%,18.3\n"
       f"3,9003,NaterGater24 (2/2),0,120.0,{LINEUP_B},,BBB DST1,DST,5.25%,7\n")


def _pool():
    p = make_pool()
    p["median"] = 10.0
    return p


def _ids(p, names):
    return [int(p.loc[p["name"] == n, "dk_id"].iloc[0]) for n in names]


A_NAMES = ["BBB DST1", "AAA RB2", "AAA QB1", "AAA RB1", "BBB RB1", "AAA TE1", "AAA WR1", "AAA WR2", "BBB WR1"]


def test_parse_lineup():
    pairs = ent.parse_lineup(LINEUP_A)
    assert len(pairs) == 9 and pairs[0] == ("DST", "BBB DST1") and pairs[1] == ("FLEX", "AAA RB2")
    assert ent.parse_lineup("") == []


def test_read_my_entries_multi_entry_case_insensitive():
    mine = ent.read_my_entries(CSV, "natergater24")
    assert list(mine.entry_id) == ["9002", "9003"]
    assert list(mine.place) == [2, 3] and mine.field_size.iloc[0] == 3
    assert "natergater24" not in mine.to_csv().lower() and "someoneelse" not in mine.to_csv()
    assert ent.read_my_entries(CSV, "nobody").empty


def test_match_lineup_ids_and_unknown_player():
    p = _pool()
    ids = ent.match_lineup_ids(ent.parse_lineup(LINEUP_A), p)
    assert ids == _ids(p, A_NAMES)
    ids_b = ent.match_lineup_ids(ent.parse_lineup(LINEUP_B), p)
    assert ids_b[-1] is None and all(i is not None for i in ids_b[:-1])


@pytest.mark.parametrize("name,field,key", [
    ("NFL GIANT $25 Double Up [Single Entry]", 2758, "double_up"),
    ("NFL $10 Triple Up", 4100, "multiplier_3x"),
    ("NFL $2.75M Fantasy Football Millionaire", 161764, "large_tournament"),
    ("NFL $25 Head-to-Head", 2, "h2h"),
    ("NFL $400K Spy [Single Entry]", 9000, "single_entry"),
    ("", 2, "h2h"), ("", 50000, "large_tournament"), ("", 500, ""), ("NFL $20K Thunderdome", 900, "tournament")])
def test_guess_contest_type(name, field, key):
    assert ent.guess_contest_type(name, field) == key


def _slate_lineups(p):
    ids = _ids(p, A_NAMES)
    rows = []
    for key in ("h2h", "fifty_fifty", "double_up"):            # cash lineups are identical across cash types
        rows += [{"contest_key": key, "rank": 0, "dk_id": i} for i in ids]
    alt = ids[:-1] + _ids(p, ["CCC WR1"])
    rows += [{"contest_key": "tournament", "rank": 1, "dk_id": i} for i in alt]
    return pd.DataFrame(rows), ids, alt


def test_lineup_source_prefers_entry_contest_type():
    p = _pool()
    lus, ids, alt = _slate_lineups(p)
    assert ent.lineup_source(ids, lus, prefer="double_up") == "Recommended Double Up"
    assert ent.lineup_source(ids, lus) == "Recommended Head-to-Head"
    assert ent.lineup_source(alt, lus) == "Alternate #2 · Tournament"
    builds = pd.DataFrame({"players": [",".join(map(str, _ids(p, ["CCC QB1"] + A_NAMES[1:])))]})
    assert ent.lineup_source(_ids(p, ["CCC QB1"] + A_NAMES[1:]), lus, builds) == "My Lineup build"
    assert ent.lineup_source(ids[:-1] + [None], lus) == "Not from the app"


def test_build_entry_rows_and_unknown_player():
    p = _pool()
    lus, _, _ = _slate_lineups(p)
    mine = ent.read_my_entries(CSV, "natergater24")
    contest = {"contest_name": "NFL GIANT $25 Double Up [Single Entry]", "entry_fee": 25.0}
    rows = ent.build_entry_rows(mine, p, lus, None, "2026-10-18", "123", contest)
    assert list(rows.columns) == ent.ENTRY_COLUMNS
    a, b = rows.iloc[0], rows.iloc[1]
    assert a.contest_type == "double_up" and a.entry_fee == 25.0 and math.isnan(a.winnings)
    assert a.projected == pytest.approx(90.0) and a.lineup_source == "Recommended Double Up"
    assert len(a.players.split(",")) == 9 and a.points == pytest.approx(140.1)
    assert math.isnan(b.projected) and b.lineup_source == "Not from the app" and len(b.players.split(",")) == 8


def test_build_entry_rows_unknown_player():
    p = _pool()
    mine = ent.read_my_entries(CSV, "natergater24").iloc[[1]]
    rows = ent.build_entry_rows(mine, p, None, None, "2026-10-18", "123", None)
    r = rows.iloc[0]
    assert r.entry_id == "9003" and r.place == 3 and math.isnan(r.projected) and r.contest_type == ""


def test_upsert_keeps_typed_and_ignores_blanks(tmp_path):
    path = tmp_path / "entries.parquet"
    p = _pool()
    mine = ent.read_my_entries(CSV, "natergater24")
    first = ent.build_entry_rows(mine, p, None, None, "2026-10-18", "123", None)
    ent.upsert_entries(path, first)
    ent.update_entry(path, "9002", winnings=50.0, contest_type="double_up")
    again = first.copy()
    again.loc[0, "place"] = 1.0
    again.loc[0, "contest_type"] = "tournament"                    # import guess must not beat the typed type
    out = ent.upsert_entries(path, again).set_index("entry_id")
    assert len(out) == 2
    assert out.loc["9002", "winnings"] == 50.0 and out.loc["9002", "contest_type"] == "double_up"
    assert out.loc["9002", "place"] == 1.0
    assert set(out.loc["9002", "typed_fields"].split(",")) == {"winnings", "contest_type"}


def test_update_entry_rejects_unknown_fields(tmp_path):
    path = tmp_path / "entries.parquet"
    ent.upsert_entries(path, ent.build_entry_rows(ent.read_my_entries(CSV, "natergater24"), _pool(), None, None,
                                                  "2026-10-18", "123", None))
    with pytest.raises(ValueError):
        ent.update_entry(path, "9002", points=999.0)
    with pytest.raises(KeyError):
        ent.update_entry(path, "nope", winnings=1.0)


def test_add_manual_entry_and_summary(tmp_path):
    path = tmp_path / "entries.parquet"
    ent.add_manual_entry(path, slate_date="2026-10-11", contest_name="NFL $5 Double Up", contest_type="double_up",
                         entry_fee=5.0, winnings=10.0)
    ent.add_manual_entry(path, slate_date="2026-10-11", contest_name="NFL $10 Triple Up",
                         contest_type="multiplier_3x", entry_fee=10.0, winnings=0.0)
    e = ent.add_manual_entry(path, slate_date="2026-10-18", contest_name="NFL $20 Tournament",
                             contest_type="tournament", entry_fee=20.0, winnings=np.nan)
    assert len(e) == 3 and e.entry_id.str.startswith("manual-").all() and e.entry_id.is_unique
    s = ent.summary(e)
    assert (s["entries"], s["settled"], s["cashed"], s["waiting"]) == (3, 2, 1, 1)
    assert s["fees"] == 15.0 and s["winnings"] == 10.0 and s["profit"] == -5.0
    assert s["cash_rate"] == pytest.approx(0.5) and s["roi"] == pytest.approx(-5 / 15)
    by = {r["contest_type"]: r for r in ent.summary_by_type(e)}
    assert by["double_up"]["label"] == "Double Up" and by["double_up"]["profit"] == 5.0
    empty = ent.summary(ent.empty_entries())
    assert empty["entries"] == 0 and empty["cash_rate"] is None and empty["roi"] is None
```

Append to `tests/test_dk_salaries.py`:

```python
def test_lobby_contests_filters_by_draft_group():
    lobby = {"Contests": [
        {"id": 196653900, "n": "NFL $2.75M Fantasy Football Millionaire", "a": 20, "m": 161764, "dg": 154941},
        {"id": 1, "n": "NFL Showdown", "a": 5, "m": 100, "dg": 999}]}
    c = dk_salaries.lobby_contests(lobby, 154941)
    assert list(c.columns) == ["contest_id", "contest_name", "entry_fee", "max_entries"]
    assert c.to_dict("records") == [{"contest_id": "196653900", "contest_name": "NFL $2.75M Fantasy Football Millionaire",
                                     "entry_fee": 20.0, "max_entries": 161764}]
    assert dk_salaries.lobby_contests({}, 1).empty
```

Append to `tests/test_config.py`:

```python
def test_dk_username_from_env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("DK_USERNAME", raising=False)
    assert config.dk_username() is None
    (tmp_path / "env.txt").write_text("DK_USERNAME= someone \n")
    assert config.dk_username() == "someone"
    monkeypatch.delenv("DK_USERNAME", raising=False)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_entries.py tests/test_dk_salaries.py tests/test_config.py -v`
Expected: ImportError for `nfldfs.entries`; `lobby_contests` / `dk_username` missing.

- [x] **Step 3: Implement**

`nfldfs/config.py` — add below `odds_api_key`:

```python
def dk_username() -> str | None:
    """Nathan's DraftKings username, read only from env.txt (never stored or published)."""
    load_dotenv(ROOT / "env.txt")
    value = os.getenv("DK_USERNAME", "").strip()
    return value or None
```

`nfldfs/results.py` — split the reader (no behavior change for `read_standings`):

```python
def standings_text(path) -> str:
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            members = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not members:
                raise ValueError(f"{path.name} has no CSV inside — is it a DraftKings contest standings export?")
            return z.read(members[0]).decode("utf-8-sig")
    return path.read_text(encoding="utf-8-sig")
```
and make `read_standings` start with `df = pd.read_csv(io.StringIO(standings_text(path)), dtype=str, keep_default_na=False)`.

`nfldfs/dk_salaries.py` — add:

```python
CONTEST_COLUMNS = ["contest_id", "contest_name", "entry_fee", "max_entries"]


def lobby_contests(lobby: dict, draft_group_id) -> pd.DataFrame:
    """Contests on one draft group, from the lobby JSON (names and entry fees for the results tracker)."""
    rows = [{"contest_id": str(c["id"]), "contest_name": str(c.get("n", "")),
             "entry_fee": float(c.get("a") or 0), "max_entries": int(c.get("m") or 0)}
            for c in lobby.get("Contests", []) if str(c.get("dg")) == str(draft_group_id)]
    return pd.DataFrame(rows, columns=CONTEST_COLUMNS)
```

`nfldfs/entries.py`:

```python
"""Nathan's own DraftKings Classic entries: find them in a contest-standings export, link each to the app
lineup it came from, and keep money and results.

Standings files list every user in the contest. Only rows whose EntryName is Nathan's username are kept, and the
username itself is never stored or returned."""
from __future__ import annotations

import datetime as dt
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CONTEST_TYPES
from .status import atomic_write_parquet
from .teams import normalize_name

ENTRY_COLUMNS = ["entry_id", "contest_id", "slate_date", "contest_name", "contest_type", "entry_fee", "winnings",
                 "place", "field_size", "points", "players", "projected", "lineup_source", "typed_fields"]
NUMERIC = ("entry_fee", "winnings", "place", "field_size", "points", "projected")
EDITABLE = ("entry_fee", "winnings", "contest_type", "contest_name")
ENTRY_SOURCE_COLUMNS = ("EntryId", "EntryName", "Rank", "Points", "Lineup")
SLOT_POSITIONS = {"QB": ("QB",), "RB": ("RB",), "WR": ("WR",), "TE": ("TE",), "FLEX": ("RB", "WR", "TE"),
                  "DST": ("DST",)}
TYPE_KEYWORDS = (("head-to-head", "h2h"), ("h2h", "h2h"), ("50/50", "fifty_fifty"), ("double up", "double_up"),
                 ("triple up", "multiplier_3x"), ("quintuple", "multiplier_5x"), ("10x", "multiplier_10x"),
                 ("millionaire", "large_tournament"), ("single entry", "single_entry"),
                 ("3 entry max", "single_entry"), ("3-max", "single_entry"))
LARGE_FIELD = 20_000
_SLOT = re.compile(r"(?:^|\s)(QB|RB|WR|TE|FLEX|DST)\s+")
_CONTEST_ID = re.compile(r"contest-standings-(\d+)")


def empty_entries() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="float64" if c in NUMERIC else "object") for c in ENTRY_COLUMNS})


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ENTRY_COLUMNS:
        if c in NUMERIC:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
        else:
            df[c] = df[c].fillna("").astype(str)
    return df[ENTRY_COLUMNS]


def load_entries(path) -> pd.DataFrame:
    path = Path(path)
    return _coerce(pd.read_parquet(path)) if path.exists() else empty_entries()


def contest_id_from(path) -> str:
    m = _CONTEST_ID.search(Path(path).name)
    return m.group(1) if m else ""


def guess_contest_type(name: str, field_size=None) -> str:
    n = (name or "").lower()
    for keyword, key in TYPE_KEYWORDS:
        if keyword in n:
            return key
    if field_size is not None and not pd.isna(field_size):
        if int(field_size) == 2:
            return "h2h"
        if int(field_size) >= LARGE_FIELD:
            return "large_tournament"
    return "tournament" if n else ""


def parse_lineup(text) -> list[tuple[str, str]]:
    parts = _SLOT.split(" " + str(text or "").strip())
    it = iter(parts[1:])
    return [(slot, name.strip()) for slot, name in zip(it, it)]


def read_my_entries(text: str, username: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    missing = [c for c in ENTRY_SOURCE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"This contest standings file is missing columns {missing}")
    rows = df[df["EntryId"].str.strip() != ""]
    base = rows["EntryName"].str.split(" (", n=1, regex=False).str[0].str.strip().str.lower()
    mine = rows[base == username.strip().lower()]
    return pd.DataFrame({"entry_id": mine["EntryId"].str.strip().to_numpy(),
                         "place": pd.to_numeric(mine["Rank"], errors="coerce").to_numpy(),
                         "points": pd.to_numeric(mine["Points"], errors="coerce").to_numpy(),
                         "lineup": mine["Lineup"].to_numpy(),
                         "field_size": np.full(len(mine), float(len(rows)))})


def match_lineup_ids(pairs, snapshot: pd.DataFrame) -> list:
    keys = snapshot["name"].map(normalize_name)
    ids = []
    for slot, name in pairs:
        hit = snapshot[(keys == normalize_name(name)) & snapshot["position"].isin(SLOT_POSITIONS.get(slot, ()))]
        ids.append(int(hit["dk_id"].iloc[0]) if len(hit) else None)
    return ids


def lineup_source(ids, slate_lineups, my_builds=None, prefer: str = "") -> str:
    if not ids or any(i is None for i in ids):
        return "Not from the app"
    target = frozenset(int(i) for i in ids)
    if slate_lineups is not None and len(slate_lineups):
        groups = list(slate_lineups.groupby(["contest_key", "rank"], sort=False))
        groups.sort(key=lambda g: (g[0][0] != prefer, int(g[0][1])))
        for (key, rank), g in groups:
            if frozenset(int(x) for x in g["dk_id"]) == target:
                label = CONTEST_TYPES.get(key, {}).get("label", key)
                return f"Recommended {label}" if int(rank) == 0 else f"Alternate #{int(rank) + 1} · {label}"
    if my_builds is not None and len(my_builds):
        for players in my_builds["players"]:
            if frozenset(int(x) for x in str(players).split(",") if x) == target:
                return "My Lineup build"
    return "Not from the app"


def build_entry_rows(mine: pd.DataFrame, snapshot: pd.DataFrame, slate_lineups, my_builds, slate_date: str,
                     contest_id: str, contest: dict | None = None) -> pd.DataFrame:
    contest = contest or {}
    name = str(contest.get("contest_name") or "")
    fee = contest.get("entry_fee")
    medians = snapshot.set_index("dk_id")["median"]
    rows = []
    for r in mine.itertuples(index=False):
        ids = match_lineup_ids(parse_lineup(r.lineup), snapshot)
        complete = len(ids) == 9 and all(i is not None for i in ids)
        ctype = guess_contest_type(name, r.field_size)
        rows.append({
            "entry_id": str(r.entry_id), "contest_id": str(contest_id), "slate_date": str(slate_date),
            "contest_name": name, "contest_type": ctype,
            "entry_fee": float(fee) if fee is not None and not pd.isna(fee) else np.nan, "winnings": np.nan,
            "place": float(r.place), "field_size": float(r.field_size), "points": float(r.points),
            "players": ",".join(str(i) for i in ids if i is not None),
            "projected": float(medians.reindex(ids).sum()) if complete else np.nan,
            "lineup_source": lineup_source(ids, slate_lineups, my_builds, prefer=ctype),
            "typed_fields": ""})
    return _coerce(pd.DataFrame(rows, columns=ENTRY_COLUMNS)) if rows else empty_entries()


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or v == ""


def upsert_entries(path, new: pd.DataFrame) -> pd.DataFrame:
    """Add new entries; update existing ones (by entry_id). Typed values are never replaced by an import, and
    a blank imported value never erases anything."""
    rows = load_entries(path).to_dict("records")
    index = {str(r["entry_id"]): i for i, r in enumerate(rows)}
    for rec in _coerce(new).to_dict("records"):
        i = index.get(str(rec["entry_id"]))
        if i is None:
            rows.append(rec)
            index[str(rec["entry_id"])] = len(rows) - 1
            continue
        typed = set(filter(None, str(rows[i].get("typed_fields") or "").split(",")))
        for c in ENTRY_COLUMNS:
            if c in ("entry_id", "typed_fields") or c in typed or _blank(rec.get(c)):
                continue
            rows[i][c] = rec[c]
    out = _coerce(pd.DataFrame(rows, columns=ENTRY_COLUMNS)) if rows else empty_entries()
    atomic_write_parquet(out, path)
    return out


def update_entry(path, entry_id: str, **fields) -> pd.DataFrame:
    bad = set(fields) - set(EDITABLE)
    if bad:
        raise ValueError(f"These fields can't be edited: {sorted(bad)}")
    cur = load_entries(path)
    match = cur.index[cur["entry_id"] == str(entry_id)]
    if not len(match):
        raise KeyError(f"No entry {entry_id}")
    i = match[0]
    typed = set(filter(None, cur.at[i, "typed_fields"].split(",")))
    for k, v in fields.items():
        cur.at[i, k] = v
        typed.add(k)
    cur.at[i, "typed_fields"] = ",".join(sorted(typed))
    cur = _coerce(cur)
    atomic_write_parquet(cur, path)
    return cur


def add_manual_entry(path, *, slate_date, contest_name, contest_type, entry_fee, winnings, players="",
                     projected=np.nan, lineup_source="Not from the app") -> pd.DataFrame:
    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S%f")
    row = {"entry_id": f"manual-{stamp}", "contest_id": "", "slate_date": str(slate_date),
           "contest_name": contest_name, "contest_type": contest_type, "entry_fee": entry_fee, "winnings": winnings,
           "place": np.nan, "field_size": np.nan, "points": np.nan, "players": players, "projected": projected,
           "lineup_source": lineup_source, "typed_fields": "contest_name,contest_type,entry_fee,winnings"}
    return upsert_entries(path, pd.DataFrame([row], columns=ENTRY_COLUMNS))


def summary(entries: pd.DataFrame) -> dict:
    e = _coerce(entries) if len(entries) else empty_entries()
    done = e[e["winnings"].notna()]
    fees, won = float(done["entry_fee"].fillna(0).sum()), float(done["winnings"].sum())
    cashed = int((done["winnings"] > 0).sum())
    scored = e[e["points"].notna() & e["projected"].notna()]
    return {"entries": int(len(e)), "settled": int(len(done)), "cashed": cashed,
            "cash_rate": cashed / len(done) if len(done) else None, "fees": fees, "winnings": won,
            "profit": won - fees, "roi": (won - fees) / fees if fees else None,
            "avg_points": float(e["points"].mean()) if e["points"].notna().any() else None,
            "avg_vs_projected": float((scored["points"] - scored["projected"]).mean()) if len(scored) else None,
            "waiting": int(len(e) - len(done))}


def type_label(key: str) -> str:
    return CONTEST_TYPES.get(key, {}).get("label") or ("Type not set" if not key else key)


def summary_by_type(entries: pd.DataFrame) -> list[dict]:
    if not len(entries):
        return []
    e = _coerce(entries)
    return [{"contest_type": key, "label": type_label(key), **summary(g)}
            for key, g in e.groupby("contest_type", sort=False)]
```

- [x] **Step 4: Run tests to verify they pass**

Run: `./py -m pytest tests/test_entries.py tests/test_dk_salaries.py tests/test_config.py tests/test_results.py -v && ./py -m pytest -q -W error`
Expected: all pass.

- [x] **Step 5: Commit**

```bash
git add nfldfs/entries.py nfldfs/results.py nfldfs/dk_salaries.py nfldfs/config.py tests/test_entries.py tests/test_dk_salaries.py tests/test_config.py
git commit -m "Add entry tracking core: find my entries, link to app lineups, totals" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 2: `player_history.py` — week-by-week player rows, actuals and search

**Files:**
- Create: `nfldfs/player_history.py`, `tests/test_player_history.py`

**Interfaces:**
- Consumes: built pool columns (`dk_id, name, position, team, opp, salary, median, floor, ceiling, own_pct, playable, mu_label, mu_color`); normalized nflverse player-weeks (`name, team, position, season, week, dk_pts`); raw nflverse schedule (`season, week, game_type, gameday`); entries frame (Task 1).
- Produces: `PW_COLUMNS`, `empty()`, `load(path)`, `slate_rows(pool, slate_date)`, `upsert_slate(path, rows)` (keeps existing actuals for that slate), `set_actuals(path, slate_date, actuals) -> int` (actuals: `dk_id` plus `actual_pts` and/or `actual_own`; non-null values overwrite), `nflverse_actuals(slate_rows, stats_week) -> DataFrame[dk_id, actual_pts]` (non-DST only), `week_dates(sched_raw) -> DataFrame[season, week, gameday]`, `week_for(week_dates, slate_date) -> (season, week) | None`, `search(pw, entries, name, mine_only=False) -> (dict, DataFrame)`.

- [x] **Step 1: Write the failing tests** — `tests/test_player_history.py`:

```python
import math

import numpy as np
import pandas as pd
import pytest

from nfldfs import player_history as ph
from tests.conftest import make_pool


def _pool():
    p = make_pool()
    p["median"], p["floor"], p["ceiling"], p["own_pct"] = 10.0, 5.0, 20.0, 8.0
    p["mu_label"], p["mu_color"] = "Good", "#2a7"
    p.loc[p["name"] == "AAA WR6", "playable"] = False
    return p


def test_slate_rows_and_upsert_keeps_actuals(tmp_path):
    path = tmp_path / "pw.parquet"
    rows = ph.slate_rows(_pool(), "2026-10-18")
    assert list(rows.columns) == ph.PW_COLUMNS and "AAA WR6" not in set(rows["name"])
    ph.upsert_slate(path, rows)
    qb = int(rows.loc[rows["name"] == "AAA QB1", "dk_id"].iloc[0])
    assert ph.set_actuals(path, "2026-10-18", pd.DataFrame({"dk_id": [qb], "actual_pts": [25.1]})) == 1
    again = rows.copy()
    again["median"] = 11.0                                     # a rebuild of the same slate
    out = ph.upsert_slate(path, again)
    r = out[(out.slate_date == "2026-10-18") & (out.dk_id == qb)].iloc[0]
    assert r["median"] == 11.0 and r["actual_pts"] == 25.1 and len(out) == len(rows)
    ph.upsert_slate(path, ph.slate_rows(_pool(), "2026-10-11"))
    assert ph.load(path)["slate_date"].nunique() == 2


def test_set_actuals_own_only_keeps_points(tmp_path):
    path = tmp_path / "pw.parquet"
    rows = ph.slate_rows(_pool(), "2026-10-18")
    ph.upsert_slate(path, rows)
    qb = int(rows.loc[rows["name"] == "AAA QB1", "dk_id"].iloc[0])
    ph.set_actuals(path, "2026-10-18", pd.DataFrame({"dk_id": [qb], "actual_pts": [25.1]}))
    ph.set_actuals(path, "2026-10-18", pd.DataFrame({"dk_id": [qb], "actual_own": [40.0], "actual_pts": [np.nan]}))
    r = ph.load(path).set_index("dk_id").loc[qb]
    assert r["actual_pts"] == 25.1 and r["actual_own"] == 40.0


def test_nflverse_actuals_matches_offense_only():
    rows = ph.slate_rows(_pool(), "2026-10-18")
    stats = pd.DataFrame({"name": ["AAA QB1", "AAA WR1", "Not On Slate"], "team": ["AAA", "AAA", "AAA"],
                          "position": ["QB", "WR", "WR"], "season": 2026, "week": 7, "dk_pts": [22.0, 15.5, 3.0]})
    a = ph.nflverse_actuals(rows, stats).merge(rows[["dk_id", "name"]], on="dk_id").set_index("name")
    assert a.loc["AAA QB1", "actual_pts"] == 22.0 and a.loc["AAA WR1", "actual_pts"] == 15.5
    assert len(a) == 2


def test_week_dates_and_lookup():
    sched = pd.DataFrame({"season": [2026, 2026, 2026], "week": [7, 7, 8], "game_type": ["REG"] * 3,
                          "gameday": ["2026-10-15", "2026-10-18", "2026-10-25"]})
    wd = ph.week_dates(sched)
    assert ph.week_for(wd, "2026-10-18") == (2026, 7) and ph.week_for(wd, "2026-12-01") is None


def test_search_with_entries():
    pw = pd.concat([ph.slate_rows(_pool(), "2026-10-11"), ph.slate_rows(_pool(), "2026-10-18")], ignore_index=True)
    qb = int(pw.loc[pw["name"] == "AAA QB1", "dk_id"].iloc[0])
    pw.loc[(pw.dk_id == qb) & (pw.slate_date == "2026-10-18"), "actual_pts"] = 30.0
    entries = pd.DataFrame({"entry_id": ["1"], "slate_date": ["2026-10-18"], "contest_name": ["NFL $25 Double Up"],
                            "players": [str(qb)], "entry_fee": [25.0], "winnings": [50.0]})
    summary, table = ph.search(pw, entries, "aaa qb1")
    assert summary["slates"] == 2 and summary["times_played"] == 1
    assert summary["avg_projected"] == 10.0 and summary["avg_actual"] == 30.0
    assert list(table["Slate"]) == ["2026-10-18", "2026-10-11"]
    assert table.iloc[0]["My entry"] == "NFL $25 Double Up · ✅ +$25" and table.iloc[1]["My entry"] == "—"
    _, mine = ph.search(pw, entries, "AAA QB1", mine_only=True)
    assert len(mine) == 1
    s, t = ph.search(pw, entries, "Nobody")
    assert s["slates"] == 0 and t.empty
```

- [x] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_player_history.py -v` → ImportError.

- [x] **Step 3: Implement `nfldfs/player_history.py`**

```python
"""Week-by-week history of every player the app projected: projection, matchup, ownership and actual result."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .status import atomic_write_parquet
from .teams import normalize_name

PW_COLUMNS = ["slate_date", "dk_id", "name", "position", "team", "opp", "salary", "median", "floor", "ceiling",
              "own_pct", "mu_label", "mu_color", "actual_pts", "actual_own"]
NUMERIC = ("salary", "median", "floor", "ceiling", "own_pct", "actual_pts", "actual_own")
TABLE_COLUMNS = ["Slate", "Matchup", "Salary", "Projected", "Actual", "+/−", "Own est.", "Own actual", "My entry",
                 "mu_color"]


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in PW_COLUMNS:
        if c == "dk_id":
            df[c] = df[c].astype("int64")
        elif c in NUMERIC:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
        else:
            df[c] = df[c].fillna("").astype(str)
    return df[PW_COLUMNS]


def empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="int64" if c == "dk_id" else "float64" if c in NUMERIC else "object")
                         for c in PW_COLUMNS})


def load(path) -> pd.DataFrame:
    path = Path(path)
    return _coerce(pd.read_parquet(path)) if path.exists() else empty()


def slate_rows(pool: pd.DataFrame, slate_date: str) -> pd.DataFrame:
    p = pool[pool["playable"]].copy()
    if "mu_label" not in p.columns:
        p["mu_label"] = "Neutral"
    if "mu_color" not in p.columns:
        p["mu_color"] = "#8a8a3d"
    p["slate_date"] = str(slate_date)
    p["actual_pts"] = np.nan
    p["actual_own"] = np.nan
    return _coerce(p.reset_index(drop=True))


def upsert_slate(path, rows: pd.DataFrame) -> pd.DataFrame:
    cur = load(path)
    if not len(rows):
        return cur
    date = rows["slate_date"].iloc[0]
    kept = cur[cur["slate_date"] == date][["dk_id", "actual_pts", "actual_own"]]
    fresh = rows.drop(columns=["actual_pts", "actual_own"]).merge(kept, on="dk_id", how="left")
    out = _coerce(pd.concat([cur[cur["slate_date"] != date], fresh], ignore_index=True))
    atomic_write_parquet(out, path)
    return out


def set_actuals(path, slate_date: str, actuals: pd.DataFrame) -> int:
    cur = load(path)
    on_slate = cur["slate_date"] == str(slate_date)
    updated = 0
    for col in ("actual_pts", "actual_own"):
        if col not in actuals.columns:
            continue
        values = actuals.dropna(subset=[col]).drop_duplicates("dk_id").set_index("dk_id")[col]
        hit = on_slate & cur["dk_id"].isin(values.index)
        cur.loc[hit, col] = cur.loc[hit, "dk_id"].map(values)
        updated = max(updated, int(hit.sum()))
    atomic_write_parquet(_coerce(cur), path)
    return updated


def nflverse_actuals(rows: pd.DataFrame, stats_week: pd.DataFrame) -> pd.DataFrame:
    """DK points from nflverse for the slate's non-DST players (name+team+position, then name+position)."""
    stats = stats_week.assign(key=stats_week["name"].map(normalize_name))
    by_team = stats.drop_duplicates(["key", "team", "position"]).set_index(["key", "team", "position"])["dk_pts"]
    by_pos = stats.drop_duplicates(["key", "position"]).set_index(["key", "position"])["dk_pts"]
    out = []
    for r in rows[rows["position"] != "DST"].itertuples(index=False):
        key = normalize_name(r.name)
        pts = by_team.get((key, r.team, r.position), by_pos.get((key, r.position)))
        if pts is not None and not pd.isna(pts):
            out.append({"dk_id": int(r.dk_id), "actual_pts": float(pts)})
    return pd.DataFrame(out, columns=["dk_id", "actual_pts"])


def week_dates(sched_raw: pd.DataFrame) -> pd.DataFrame:
    s = sched_raw[sched_raw["game_type"] == "REG"]
    return (s[["season", "week", "gameday"]].assign(gameday=s["gameday"].astype(str))
            .drop_duplicates().reset_index(drop=True))


def week_for(week_dates_df: pd.DataFrame, slate_date: str):
    hit = week_dates_df[week_dates_df["gameday"] == str(slate_date)]
    return (int(hit["season"].iloc[0]), int(hit["week"].iloc[0])) if len(hit) else None


def _entry_label(e) -> str:
    name = e.get("contest_name") or "Contest"
    won, fee = e.get("winnings"), e.get("entry_fee")
    if won is None or pd.isna(won):
        return f"{name} · 💲 winnings not entered"
    profit = float(won) - float(fee or 0)
    return f"{name} · {'✅' if won > 0 else '✗'} {'+' if profit >= 0 else '−'}${abs(profit):,.0f}"


def search(pw: pd.DataFrame, entries: pd.DataFrame, name: str, mine_only: bool = False):
    rows = pw[pw["name"].str.lower() == str(name).strip().lower()].sort_values("slate_date", ascending=False)
    played = {}
    for e in (entries.to_dict("records") if entries is not None and len(entries) else []):
        for pid in str(e.get("players") or "").split(","):
            if pid:
                played.setdefault((str(e["slate_date"]), int(pid)), _entry_label(e))
    table = pd.DataFrame([{
        "Slate": r.slate_date, "Matchup": f"vs {r.opp} · {r.mu_label}", "Salary": r.salary, "Projected": r.median,
        "Actual": r.actual_pts, "+/−": (r.actual_pts - r.median) if not pd.isna(r.actual_pts) else np.nan,
        "Own est.": r.own_pct, "Own actual": r.actual_own,
        "My entry": played.get((r.slate_date, int(r.dk_id)), "—"), "mu_color": r.mu_color}
        for r in rows.itertuples(index=False)], columns=TABLE_COLUMNS)
    summary = {"slates": int(len(rows)),
               "avg_projected": float(rows["median"].mean()) if len(rows) else None,
               "avg_actual": float(rows["actual_pts"].mean()) if rows["actual_pts"].notna().any() else None,
               "times_played": int((table["My entry"] != "—").sum()) if len(table) else 0}
    if mine_only:
        table = table[table["My entry"] != "—"].reset_index(drop=True)
    return summary, table
```

- [x] **Step 4: Run tests** — `./py -m pytest tests/test_player_history.py -v && ./py -m pytest -q -W error` → all pass.

- [x] **Step 5: Commit**

```bash
git add nfldfs/player_history.py tests/test_player_history.py
git commit -m "Add week-by-week player history with actuals and search" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 3: Pipeline wiring — contests, lineup archive, player rows, actuals, entries

**Files:**
- Modify: `run_pipeline.py`, `tests/test_run_pipeline.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces (files): `data/processed/contests.parquet` (merged across runs, unique `contest_id`), `data/processed/slate_lineups/<slate_date>_<dg>.parquet` (a copy of that build's `lineups.parquet`; a **separate folder** so `results.latest_slate_snapshot`'s pattern never matches it), `data/processed/week_dates.parquet`, `data/history/player_weeks.parquet`, `data/history/entries.parquet`. Helper `fill_nflverse_actuals(player_weeks_stats, week_dates_df) -> int` in `run_pipeline`.

- [x] **Step 1: Write the failing tests** — append to `tests/test_run_pipeline.py` (reuse the existing `_paths`, `_snapshot_file`, `_standings_zip` helpers and `make_pool` import; extend `_paths` to also patch nothing new — the new files live under `PROCESSED`/`HISTORY` which `_paths` already redirects):

```python
def _standings_zip_with_me(path):
    lineup = ("DST BBB DST1 FLEX AAA RB2 QB AAA QB1 RB AAA RB1 RB BBB RB1 TE AAA TE1 "
              "WR AAA WR1 WR AAA WR2 WR BBB WR1")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("contest-standings-555.csv",
                   "Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS\n"
                   f"1,1,someoneelse,0,150,{lineup},,AAA QB1,QB,30.00%,22.0\n"
                   f"2,2,natergater24,0,140,{lineup},,AAA WR1,WR,12.00%,18.0\n")
    return path


def test_results_import_creates_entries_without_usernames(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    _snapshot_file(tmp_path)
    monkeypatch.setattr(config, "dk_username", lambda: "natergater24")
    pd.DataFrame([{"contest_id": "555", "contest_name": "NFL GIANT $25 Double Up", "entry_fee": 25.0,
                   "max_entries": 2758}]).to_parquet(tmp_path / "processed" / "contests.parquet", index=False)
    z = _standings_zip_with_me(tmp_path / "Downloads" / "contest-standings-555.zip")
    import os
    monday = dt.datetime(2026, 10, 19, 9, 0).timestamp()
    os.utime(z, (monday, monday))
    msg = run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert "1 of your entries" in msg
    e = pd.read_parquet(tmp_path / "history" / "entries.parquet")
    assert len(e) == 1 and e.iloc[0]["contest_type"] == "double_up" and e.iloc[0]["entry_fee"] == 25.0
    for folder in ("history", "published"):
        for f in (tmp_path / folder).rglob("*"):
            if f.is_file():
                blob = f.read_bytes().lower()
                assert b"natergater24" not in blob and b"someoneelse" not in blob, f


def test_results_import_without_username_says_how_to_enable(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    _snapshot_file(tmp_path)
    monkeypatch.setattr(config, "dk_username", lambda: None)
    z = _standings_zip_with_me(tmp_path / "Downloads" / "contest-standings-555.zip")
    import os
    monday = dt.datetime(2026, 10, 19, 9, 0).timestamp()
    os.utime(z, (monday, monday))
    msg = run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert "DK_USERNAME" in msg and not (tmp_path / "history" / "entries.parquet").exists()


def test_fill_nflverse_actuals(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    from nfldfs import player_history as ph
    pool = make_pool()
    pool["median"], pool["floor"], pool["ceiling"], pool["own_pct"] = 10.0, 5.0, 20.0, 8.0
    ph.upsert_slate(tmp_path / "history" / "player_weeks.parquet", ph.slate_rows(pool, "2026-10-18"))
    stats = pd.DataFrame({"name": ["AAA QB1"], "team": ["AAA"], "position": ["QB"], "season": [2026], "week": [7],
                          "dk_pts": [21.5]})
    wd = pd.DataFrame({"season": [2026], "week": [7], "gameday": ["2026-10-18"]})
    assert run_pipeline.fill_nflverse_actuals(stats, wd) == 1
    pw = ph.load(tmp_path / "history" / "player_weeks.parquet")
    assert pw.loc[pw["name"] == "AAA QB1", "actual_pts"].iloc[0] == 21.5


def test_salaries_step_saves_lobby_contests(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    from pathlib import Path as _P
    csv_text = (_P(__file__).parent / "fixtures" / "dk_salaries_sample.csv").read_bytes().decode("utf-8")
    lobby = {"DraftGroups": [{"DraftGroupId": 154941, "ContestTypeId": 21, "GameTypeId": 1, "GameCount": 10,
                              "StartDateEst": "2026-10-18T13:00:00.0000000", "DraftGroupTag": "Featured"}],
             "Contests": [{"id": 777, "n": "NFL $5 Double Up", "a": 5, "m": 100, "dg": 154941}]}
    monkeypatch.setattr(run_pipeline.dk_salaries, "fetch_lobby", lambda: lobby)
    monkeypatch.setattr(run_pipeline.dk_salaries, "fetch_salary_csv", lambda slate: csv_text)
    run_pipeline.step_salaries(dt.date(2026, 10, 12), SimpleNamespace(salary_csv=None))
    c = pd.read_parquet(tmp_path / "processed" / "contests.parquet")
    assert c.to_dict("records") == [{"contest_id": "777", "contest_name": "NFL $5 Double Up", "entry_fee": 5.0,
                                     "max_entries": 100}]
```

If `_paths` doesn't create `tmp_path / "history"`, the atomic writers create parent folders automatically.

- [x] **Step 2: Run tests to verify they fail** — `./py -m pytest tests/test_run_pipeline.py -v` → the 4 new tests fail.

- [x] **Step 3: Implement in `run_pipeline.py`**

Imports: add `entries` and `player_history` to the `from nfldfs import ...` line.

`step_salaries` — fetch the lobby once and save its contests:

```python
    else:
        lobby = dk_salaries.fetch_lobby()
        slate = dk_salaries.find_main_slate(lobby, today)
        text = dk_salaries.fetch_salary_csv(slate)
        slate["source"] = "draftkings"
        _save_contests(dk_salaries.lobby_contests(lobby, slate["draft_group_id"]))
```

and add:

```python
def _save_contests(new: pd.DataFrame) -> None:
    path = config.PROCESSED / "contests.parquet"
    cur = pd.read_parquet(path) if path.exists() else new.iloc[0:0]
    merged = pd.concat([cur, new], ignore_index=True).drop_duplicates("contest_id", keep="last")
    atomic_write_parquet(merged.reset_index(drop=True), path)
```

`step_stats` — after writing `schedule_rows.parquet`:

```python
    wd = player_history.week_dates(sched)
    atomic_write_parquet(wd, config.PROCESSED / "week_dates.parquet")
    filled = fill_nflverse_actuals(pw, wd)
```
append `f"; actual points filled for {filled} player-slates"` to the returned message, and add:

```python
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
```

`step_build` — after archiving the slate snapshot:

```python
    dg_tag = slate.get("draft_group_id") or "upload"
    atomic_write_parquet(res["lineups"], config.PROCESSED / "slate_lineups" / f"{slate_date}_{dg_tag}.parquet")
    player_history.upsert_slate(config.HISTORY / "player_weeks.parquet",
                                player_history.slate_rows(res["pool"], slate_date))
```
(reuse `dg_tag` in the existing snapshot path line).

`step_results` — inside the per-file `try`, right after the `results.append_history(...)` call and **before** `shutil.move`:

```python
            matched = results.match_to_slate(standings, snap_df, slate_date, dg)   # (reuse the value passed above)
            player_history.set_actuals(config.HISTORY / "player_weeks.parquet", slate_date,
                                       matched[["dk_id", "actual_pts", "actual_own"]])
            user = config.dk_username()
            if user:
                mine = entries.read_my_entries(results.standings_text(f), user)
                if len(mine):
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
                    entry_notes.append(f"{len(rows)} of your entries")
                else:
                    entry_notes.append("no entries of yours in this contest")
            else:
                entry_notes.append("add DK_USERNAME to env.txt to track your entries")
```
Compute `matched` once and pass it to `append_history` (no duplicate work). Initialize `entry_notes = []` with the other lists, and append `"; " + "; ".join(sorted(set(entry_notes)))` to `msg` when non-empty (before the `skipped` check).

- [x] **Step 4: Run tests** — `./py -m pytest tests/test_run_pipeline.py -v && ./py -m pytest -q -W error` → all pass.

- [x] **Step 5: Offline check on real data** — `./py run_pipeline.py --stage build` then confirm `data/history/player_weeks.parquet` has this slate's rows and `data/processed/slate_lineups/` has one file. Do **not** commit data files.

- [x] **Step 6: Commit**

```bash
git add run_pipeline.py tests/test_run_pipeline.py
git commit -m "Track entries and player actuals in the pipeline" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 4: App data, Mac-side actions, and recording My Lineup downloads

**Files:**
- Modify: `nfldfs_app/data.py`, `nfldfs_app/actions.py`, `nfldfs_app/view_builder.py`, `tests/test_app_data.py`, `tests/test_actions.py`

**Interfaces:**
- Produces: `AppData.entries` and `AppData.player_weeks` (DataFrames; empty frames when the history files are missing), loaded from `<published>/../history/`; `data.stamp` includes those two files. `actions.record_my_build(ids, slate_date, path=None) -> None` (appends to `data/processed/my_builds.parquet`, de-duplicated by slate + player set), `actions.save_entry_edit(entry_id, **fields) -> (ok, message)`, `actions.add_entry(**fields) -> (ok, message)` — both write `data/history/entries.parquet` then call `publish.publish(config.ROOT, ["data/history"], ...)` and never raise.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_app_data.py`:

```python
def test_load_reads_history_when_present(published_dir, tmp_path):
    import shutil
    import pandas as pd
    root = tmp_path / "data"
    shutil.copytree(published_dir, root / "published")
    (root / "history").mkdir()
    pd.DataFrame({"entry_id": ["1"]}).to_parquet(root / "history" / "entries.parquet", index=False)
    d = data.load(root / "published")
    assert len(d.entries) == 1 and d.player_weeks.empty
    assert any("entries.parquet" in str(k) for k, _ in data.stamp(root / "published"))


def test_load_without_history_gives_empty_frames(published_dir):
    d = data.load(published_dir)
    assert d.entries.empty and d.player_weeks.empty
```

Append to `tests/test_actions.py`:

```python
def test_record_my_build_dedupes(tmp_path):
    import pandas as pd
    path = tmp_path / "my_builds.parquet"
    actions.record_my_build([3, 1, 2], "2026-10-18", path=path)
    actions.record_my_build([1, 2, 3], "2026-10-18", path=path)
    actions.record_my_build([1, 2, 4], "2026-10-18", path=path)
    b = pd.read_parquet(path)
    assert len(b) == 2 and set(b["players"]) == {"1,2,3", "1,2,4"}


def test_save_entry_edit_and_add_entry(tmp_path, monkeypatch):
    from nfldfs import config, entries
    monkeypatch.setattr(config, "HISTORY", tmp_path / "history")
    monkeypatch.setattr(actions, "_publish", lambda message: "skipped: test")
    ok, msg = actions.add_entry(slate_date="2026-10-18", contest_name="NFL $5 Double Up", contest_type="double_up",
                                entry_fee=5.0, winnings=10.0)
    assert ok and "Saved" in msg
    e = entries.load_entries(tmp_path / "history" / "entries.parquet")
    ok, msg = actions.save_entry_edit(e.entry_id.iloc[0], winnings=0.0)
    assert ok and entries.load_entries(tmp_path / "history" / "entries.parquet").winnings.iloc[0] == 0.0
    ok, msg = actions.save_entry_edit("nope", winnings=1.0)
    assert not ok and "Couldn't save" in msg
```

- [x] **Step 2: Run tests to verify they fail** — `./py -m pytest tests/test_app_data.py tests/test_actions.py -v`.

- [x] **Step 3: Implement**

`nfldfs_app/data.py`:
- add `HISTORY_FILES = ("entries.parquet", "player_weeks.parquet")`.
- `stamp(pub)`: append `tuple((f"history/{f}", (Path(pub).parent / "history" / f).stat().st_mtime if (Path(pub).parent / "history" / f).exists() else 0.0) for f in HISTORY_FILES)` to the returned tuple.
- `AppData`: add fields `entries: pd.DataFrame = dc_field(default_factory=pd.DataFrame)` and `player_weeks: pd.DataFrame = dc_field(default_factory=pd.DataFrame)` (before `row_of`).
- `load(pub)`: compute `hist = pub.parent / "history"` and pass `entries=entries.load_entries(hist / "entries.parquet")`, `player_weeks=player_history.load(hist / "player_weeks.parquet")` (import `from nfldfs import entries as entries_mod, player_history` to avoid shadowing).

`nfldfs_app/actions.py` — add:

```python
from nfldfs import config, entries, publish


def record_my_build(ids, slate_date, path=None) -> None:
    """Remember a My Lineup download (Mac only) so a matching DraftKings entry is labeled 'My Lineup build'."""
    import datetime as dt
    import pandas as pd
    from nfldfs.status import atomic_write_parquet
    path = Path(path) if path else config.PROCESSED / "my_builds.parquet"
    players = ",".join(str(i) for i in sorted(int(i) for i in ids))
    cur = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["saved_at", "slate_date", "players"])
    if ((cur["slate_date"] == str(slate_date)) & (cur["players"] == players)).any():
        return
    row = pd.DataFrame([{"saved_at": dt.datetime.now().isoformat(timespec="seconds"),
                         "slate_date": str(slate_date), "players": players}])
    atomic_write_parquet(pd.concat([cur, row], ignore_index=True), path)


def _publish(message: str) -> str:
    return publish.publish(config.ROOT, ["data/history"], message)


def save_entry_edit(entry_id: str, **fields) -> tuple[bool, str]:
    try:
        entries.update_entry(config.HISTORY / "entries.parquet", entry_id, **fields)
    except Exception as e:
        return False, f"Couldn't save ({type(e).__name__}: {e})"
    return True, f"Saved. {_publish(f'Edit entry {entry_id}')}"


def add_entry(**fields) -> tuple[bool, str]:
    try:
        entries.add_manual_entry(config.HISTORY / "entries.parquet", **fields)
    except Exception as e:
        return False, f"Couldn't save ({type(e).__name__}: {e})"
    return True, f"Saved. {_publish('Add entry by hand')}"
```

`nfldfs_app/view_builder.py` — on the My Lineup download button, add (Mac only):

```python
    hosted = data.is_hosted()
    st.download_button("⬇ Download My Lineup (DraftKings CSV)", csv, file_name="dk_classic_my_lineup.csv",
                       mime="text/csv", disabled=not status["valid"], key="dl_mine",
                       on_click=None if hosted else actions.record_my_build,
                       args=None if hosted else (status["picked"], d.meta.get("slate_date", "")))
```
(import `actions` and `data` from `nfldfs_app`).

- [x] **Step 4: Run tests** — `./py -m pytest tests/test_app_data.py tests/test_actions.py tests/test_view_builder.py tests/test_app_smoke.py -v && ./py -m pytest -q -W error`.

- [x] **Step 5: Commit**

```bash
git add nfldfs_app/data.py nfldfs_app/actions.py nfldfs_app/view_builder.py tests/test_app_data.py tests/test_actions.py
git commit -m "Load entry history in the app; record My Lineup downloads; Mac-side entry edits" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 5: 📒 My Results tab (per the approved mockup) + sidebar reminder

**Files:**
- Create: `nfldfs_app/view_results.py`, `tests/test_view_results.py`
- Modify: `app.py` (4th tab), `nfldfs_app/ui.py` (`styled_player_history`), `nfldfs_app/view_sidebar.py` (username reminder), `tests/conftest.py` (history fixture)

**Interfaces:**
- Consumes: `AppData.entries/player_weeks`, `entries.summary/summary_by_type/type_label`, `player_history.search`, `actions.save_entry_edit/add_entry`.
- Produces: `view_results.filter_entries(e, season, type_key, source) -> DataFrame`, `view_results.render(d, hosted)`. Widget keys: `res_season`, `res_type`, `res_source`, `ph_player`, `ph_scope`, `add_entry_form`, `edit_<entry_id>`.

Layout order (binding, from the mockup): season totals (+ by-contest-type lines) → filters + ➕ Add entry by hand (Mac only) → Player history → entry log.

- [x] **Step 1: Add a history fixture to `tests/conftest.py`**

```python
@pytest.fixture(scope="session")
def results_root(tmp_path_factory, published_dir):
    """A data/ folder with published files plus a small entry and player history (sample values)."""
    import shutil
    import pandas as pd
    from nfldfs import entries as ent, player_history as ph
    root = tmp_path_factory.mktemp("data")
    shutil.copytree(published_dir, root / "published")
    pool = pd.read_parquet(published_dir / "player_pool.parquet")
    rows = ph.slate_rows(pool, "2026-10-18")
    ph.upsert_slate(root / "history" / "player_weeks.parquet", rows)
    lus = pd.read_parquet(published_dir / "lineups.parquet")
    ids = lus[(lus.contest_key == "double_up") & (lus["rank"] == 0)].dk_id.astype(int).tolist()
    ph.set_actuals(root / "history" / "player_weeks.parquet", "2026-10-18",
                   pd.DataFrame({"dk_id": ids, "actual_pts": [12.0] * 9, "actual_own": [20.0] * 9}))
    e = pd.DataFrame([
        {"entry_id": "9002", "contest_id": "555", "slate_date": "2026-10-18", "contest_name": "NFL GIANT $25 Double Up",
         "contest_type": "double_up", "entry_fee": 25.0, "winnings": 50.0, "place": 412.0, "field_size": 2758.0,
         "points": 108.0, "players": ",".join(map(str, ids)), "projected": 100.0,
         "lineup_source": "Recommended Double Up", "typed_fields": "winnings"},
        {"entry_id": "9003", "contest_id": "556", "slate_date": "2026-10-18", "contest_name": "NFL $20 Tournament",
         "contest_type": "tournament", "entry_fee": 20.0, "winnings": float("nan"), "place": 1890.0,
         "field_size": 11890.0, "points": 101.0, "players": ",".join(map(str, ids)), "projected": 100.0,
         "lineup_source": "My Lineup build", "typed_fields": ""}])
    ent.upsert_entries(root / "history" / "entries.parquet", e)
    return root
```

- [x] **Step 2: Write the failing tests** — `tests/test_view_results.py`:

```python
import pandas as pd

from nfldfs_app import actions, data, view_results


def test_filter_entries(results_root):
    d = data.load(results_root / "published")
    e = d.entries
    assert len(view_results.filter_entries(e, "2026", "all", "All lineups")) == 2
    assert list(view_results.filter_entries(e, "2026", "double_up", "All lineups").entry_id) == ["9002"]
    assert list(view_results.filter_entries(e, "2026", "all", "App lineups").entry_id) == ["9002"]
    assert list(view_results.filter_entries(e, "2026", "all", "My builds").entry_id) == ["9003"]
    assert view_results.filter_entries(e, "2025", "all", "All lineups").empty


def test_tab_hosted_is_read_only(make_app, results_root):
    at = make_app(results_root / "published", hosted="1")
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert "Profit" in labels and "Cashed" in labels
    assert any("Edit on your Mac" in c.value for c in at.caption)
    assert not [f for f in at.get("form") if "edit_" in str(getattr(f, "key", ""))]


def test_tab_local_edit_saves(make_app, results_root, monkeypatch):
    calls = []
    monkeypatch.setattr(actions, "save_entry_edit", lambda entry_id, **f: calls.append((entry_id, f)) or (True, "Saved."))
    at = make_app(results_root / "published", hosted="0")
    assert not at.exception
    at.number_input(key="win_9003").set_value(30.0)
    at.button(key="save_9003").click().run()
    assert calls and calls[0][0] == "9003" and calls[0][1]["winnings"] == 30.0


def test_player_history_search(make_app, results_root):
    at = make_app(results_root / "published", hosted="1")
    d = data.load(results_root / "published")
    name = d.player_weeks["name"].iloc[0]
    at.selectbox(key="ph_player").set_value(name).run()
    assert not at.exception
    assert any("Slates projected" == m.label for m in at.metric)


def test_tab_with_no_entries(make_app, published_dir):
    at = make_app(published_dir, hosted="1")
    assert not at.exception
    assert any("No entries yet" in i.value for i in at.info)
```

(Implementation note: `make_app` sets `NFLDFS_PUBLISHED` to the given folder; `data.load` reads `history/` next to it, which `results_root` provides.)

- [x] **Step 3: Run tests to verify they fail** — `./py -m pytest tests/test_view_results.py -v`.

- [x] **Step 4: Implement**

`nfldfs_app/ui.py` — add:

```python
def styled_player_history(table: pd.DataFrame):
    view = table.drop(columns=["mu_color"])
    return (view.style.apply(_matchup_css(table["mu_color"].tolist()), subset=["Matchup"])
            .format({"Salary": "${:,.0f}", "Projected": "{:.1f}", "Actual": "{:.1f}", "+/−": "{:+.1f}",
                     "Own est.": "{:.0f}%", "Own actual": "{:.0f}%"}, na_rep="—"))


def signed_money(v) -> str:
    v = float(v)
    return f"{'+' if v >= 0 else '−'}${abs(v):,.0f}"
```

`nfldfs_app/view_results.py`:

```python
"""📒 My Results tab: season totals, filters, player history and the entry log (read-only on the phone)."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from nfldfs import entries as ent
from nfldfs import player_history as ph
from nfldfs.config import CONTEST_TYPES
from nfldfs_app import actions, ui

SOURCES = ("All lineups", "App lineups", "My builds")


def filter_entries(e: pd.DataFrame, season: str, type_key: str, source: str) -> pd.DataFrame:
    out = e[e["slate_date"].astype(str).str[:4] == str(season)]
    if type_key != "all":
        out = out[out["contest_type"] == type_key]
    if source == "App lineups":
        out = out[out["lineup_source"].str.startswith(("Recommended", "Alternate"))]
    elif source == "My builds":
        out = out[out["lineup_source"] == "My Lineup build"]
    return out


def _pct(v) -> str:
    return "—" if v is None else f"{v:.0%}"


def _totals(e: pd.DataFrame) -> None:
    s = ent.summary(e)
    c = st.columns(4)
    c[0].metric("Entries", s["entries"])
    c[1].metric("Cashed", f"{s['cashed']} ({_pct(s['cash_rate'])})")
    c[2].metric("Profit", ui.signed_money(s["profit"]),
                f"ROI {s['roi']:+.0%}" if s["roi"] is not None else None, delta_color="normal")
    c[3].metric("Avg score vs projected",
                "—" if s["avg_points"] is None else f"{s['avg_points']:.1f}",
                None if s["avg_vs_projected"] is None else f"{s['avg_vs_projected']:+.1f}")
    st.caption(f"Fees {ui.money(s['fees'])} · Winnings {ui.money(s['winnings'])}"
               + (f" · 💲 {s['waiting']} waiting on winnings" if s["waiting"] else ""))
    for t in ent.summary_by_type(e):
        st.caption(f"**{t['label']}**: {t['entries']} entries · {t['cashed']} cashed · {ui.signed_money(t['profit'])}")


def _add_form() -> None:
    with st.expander("➕ Add entry by hand"):
        with st.form("add_entry_form", clear_on_submit=True):
            day = st.date_input("Slate date", value=dt.date.today())
            name = st.text_input("Contest name")
            keys = list(CONTEST_TYPES)
            ctype = st.selectbox("Classic contest type", keys, format_func=ent.type_label)
            fee = st.number_input("Entry fee ($)", min_value=0.0, step=1.0)
            won = st.number_input("Winnings ($)", min_value=0.0, step=1.0)
            if st.form_submit_button("Save entry"):
                st.session_state.flash = actions.add_entry(slate_date=str(day), contest_name=name, contest_type=ctype,
                                                           entry_fee=float(fee), winnings=float(won))
                st.cache_resource.clear()
                st.rerun()


def _player_history(pw: pd.DataFrame, e: pd.DataFrame) -> None:
    st.subheader("Player history")
    if pw.empty:
        st.caption("Player history starts with the first slate this app builds after this update.")
        return
    names = sorted(pw["name"].unique())
    c = st.columns([3, 2])
    name = c[0].selectbox("Player", ["—"] + names, key="ph_player")
    scope = c[1].radio("Show", ["Every slate the app projected", "Only my entries"], key="ph_scope",
                       horizontal=True)
    if name == "—":
        st.caption("Pick a player to see projected vs. actual points, ownership and your results with him.")
        return
    summary, table = ph.search(pw, e, name, mine_only=scope == "Only my entries")
    m = st.columns(3)
    m[0].metric("Slates projected", summary["slates"])
    avg_p, avg_a = summary["avg_projected"], summary["avg_actual"]
    m[1].metric("Avg projected → actual", "—" if avg_p is None else
                f"{avg_p:.1f} → {'—' if avg_a is None else f'{avg_a:.1f}'}")
    m[2].metric("In my lineups", summary["times_played"])
    if table.empty:
        st.caption(f"You haven't played {name} yet.")
    else:
        st.dataframe(ui.styled_player_history(table), hide_index=True, width="stretch")


def _box_score(row, pw: pd.DataFrame) -> None:
    ids = [int(x) for x in str(row["players"]).split(",") if x]
    week = pw[(pw["slate_date"] == row["slate_date"]) & pw["dk_id"].isin(ids)]
    if week.empty:
        st.caption("Player details appear once this slate's history is available.")
        return
    t = pd.DataFrame({"Pos": week["position"], "Player": week["name"], "Team": week["team"],
                      "Salary": week["salary"], "Projected": week["median"], "Actual": week["actual_pts"],
                      "+/−": week["actual_pts"] - week["median"], "Own est.": week["own_pct"],
                      "Own actual": week["actual_own"]})
    st.dataframe(t.style.format({"Salary": "${:,.0f}", "Projected": "{:.1f}", "Actual": "{:.1f}", "+/−": "{:+.1f}",
                                 "Own est.": "{:.0f}%", "Own actual": "{:.0f}%"}, na_rep="—"),
                 hide_index=True, width="stretch")


def _entry(row, pw: pd.DataFrame, hosted: bool) -> None:
    won, fee = row["winnings"], row["entry_fee"]
    icon = "💲" if pd.isna(won) else ("✅" if won > 0 else "✗")
    name = row["contest_name"] or f"Contest {row['contest_id'] or ''}".strip()
    with st.expander(f"{icon} {row['slate_date']} · {name} · Classic · {ent.type_label(row['contest_type'])}"):
        money = ("Fee " + (ui.money(fee) if not pd.isna(fee) else "—") + " → "
                 + ("winnings not entered yet" if pd.isna(won) else f"Won {ui.money(won)} "
                    f"({ui.signed_money(won - (0 if pd.isna(fee) else fee))})"))
        place = "" if pd.isna(row["place"]) else f" · {int(row['place']):,} of {int(row['field_size']):,}"
        score = ("" if pd.isna(row["points"]) else f" · Actual {row['points']:.1f}"
                 + ("" if pd.isna(row["projected"]) else
                    f" vs projected {row['projected']:.1f} ({row['points'] - row['projected']:+.1f})"))
        st.markdown(money.replace("$", "\\$") + place + score)
        st.caption(f"Lineup: {row['lineup_source']}")
        _box_score(row, pw)
        if hosted:
            st.caption("Edit on your Mac.")
            return
        eid = row["entry_id"]
        c = st.columns(4)
        new_fee = c[0].number_input("Entry fee ($)", min_value=0.0, step=1.0, key=f"fee_{eid}",
                                    value=0.0 if pd.isna(fee) else float(fee))
        new_won = c[1].number_input("Winnings ($)", min_value=0.0, step=1.0, key=f"win_{eid}",
                                    value=0.0 if pd.isna(won) else float(won))
        keys = list(CONTEST_TYPES)
        new_type = c[2].selectbox("Contest type", keys, format_func=ent.type_label, key=f"type_{eid}",
                                  index=keys.index(row["contest_type"]) if row["contest_type"] in keys else 0)
        c[3].write("")
        if c[3].button("Save", key=f"save_{eid}"):
            st.session_state.flash = actions.save_entry_edit(eid, entry_fee=float(new_fee), winnings=float(new_won),
                                                             contest_type=new_type)
            st.cache_resource.clear()
            st.rerun()


def render(d, hosted: bool) -> None:
    e, pw = d.entries, d.player_weeks
    seasons = sorted({str(s)[:4] for s in e["slate_date"]} | {str(dt.date.today().year)}, reverse=True)
    if e.empty:
        st.info("No entries yet. After a contest ends, export its standings from DraftKings (📥 in the sidebar) "
                "and your entries appear here." + ("" if hosted else " You can also add one by hand below."))
    season = st.session_state.get("res_season", seasons[0])
    _totals(filter_entries(e, season, "all", "All lineups") if len(e) else e)
    c = st.columns([1, 2, 2, 2], vertical_alignment="bottom")
    season = c[0].selectbox("Season", seasons, key="res_season")
    type_keys = ["all"] + list(CONTEST_TYPES)
    type_key = c[1].selectbox("Contest type", type_keys, key="res_type",
                              format_func=lambda k: "All types" if k == "all" else ent.type_label(k))
    source = c[2].selectbox("Lineup source", SOURCES, key="res_source")
    if not hosted:
        with c[3]:
            _add_form()
    _player_history(pw, e)
    st.subheader("Entries")
    shown = filter_entries(e, season, type_key, source) if len(e) else e
    if len(e) and shown.empty:
        st.caption("No entries match these filters.")
    for _, row in shown.sort_values(["slate_date", "place"], ascending=[False, True]).iterrows():
        _entry(row, pw, hosted)
```

`app.py`: import `view_results`; change the tabs line to
`tab_rec, tab_mine, tab_pool, tab_res = st.tabs(["⭐ Recommended", "🛠 My Lineup", "📋 Player pool", "📒 My Results"])`
and add `with tab_res: view_results.render(d, hosted)`.

`nfldfs_app/view_sidebar.py` — inside `render`, after the results message and only when not hosted:

```python
        if not hosted and config.dk_username() is None:
            st.info("To track your own entries in 📒 My Results, add a line `DK_USERNAME=your DraftKings "
                    "username` to env.txt (see the user manual).")
```

- [x] **Step 5: Run tests** — `./py -m pytest tests/test_view_results.py tests/test_app_smoke.py tests/test_view_sidebar.py -v && ./py -m pytest -q -W error`. If an AppTest accessor used above differs in Streamlit 1.58 (e.g. `at.get("form")`), adapt the test to an equivalent check and note it in the report.

- [x] **Step 6: Commit**

```bash
git add nfldfs_app/view_results.py nfldfs_app/ui.py nfldfs_app/view_sidebar.py app.py tests/test_view_results.py tests/conftest.py
git commit -m "Add the My Results tab: totals, filters, player history, entry log" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

- [x] **Step 7: Browser check (controller)** — run the local app and the hosted simulation; confirm layout order matches the mockup, filters change totals, player search shows a table, Mac edit saves and updates totals, phone view shows "Edit on your Mac".

---

### Task 6: Username, docs, and the real-data check after Sunday (controller + Nathan)

**Files:** `env.txt` (local, never committed), `USER_MANUAL.md`, `README.md`, `claude-context.txt`, `claude-prompts.txt`, possibly `nfldfs/entries.py` + tests if the real format differs.

- [ ] **Step 1: Username (controller, with Nathan's earlier OK):** append `DK_USERNAME=natergater24` to `env.txt` without printing the file; confirm `git check-ignore env.txt`.
- [x] **Step 2: Docs:** USER_MANUAL — a "📒 My Results" section (what fills in automatically, typing winnings on the Mac, player search, the phone is read-only, DK_USERNAME line); README feature list; claude-context dated section incl. rulings; claude-prompts entry. Commit and push (with the code) after the final review.
- [ ] **Step 3 (after Sun Oct 18 games): real file.** Nathan exports his Double Up standings (sidebar guide). Verify: entry created with the right place/points/lineup source; `parse_lineup` handled DK's real `Lineup` format; usernames absent from `data/history`. If the format differs, fix `parse_lineup`/`read_my_entries` with a test built from the real (redacted) row.
- [ ] **Step 4 (after Sunday): HISTORY page screenshot.** If DraftKings offers an entry-history CSV, write a follow-up plan to import fees/winnings from it; otherwise winnings stay typed. Finalize the sidebar import guide wording from the screenshots.

---

## Self-Review Notes

- **Spec coverage:** §4 data model → Tasks 1–3 (entries.parquet columns, player_weeks.parquet); §5 flows 1–3, 5, 6 → Tasks 3–5; flow 4 (entry-history import) intentionally deferred to Task 6 Step 4 pending the screenshot (spec says "if it exists"); §6 tab layout → Task 5; §7 errors → Task 1 (unknown players, upsert rules) and Task 3 (no username, no entries); §8 tests → each task + browser check; §9 open items → Task 6.
- **Deviation from spec:** spec §4 says `results.parquet` is folded into `player_weeks.parquet`. This plan keeps `results.parquet` (report card + ownership model keep working unchanged) and adds `player_weeks.parquet` alongside, filled from the same import — less risk, same data for the user.
- **Deviation from spec:** spec §5 flow 1 archives lineups as `slates/<date>_<dg>_lineups.parquet`; that name would match `results.latest_slate_snapshot`'s pattern (`\w+` matches `_`), so lineups go to a separate `processed/slate_lineups/` folder. Spec §4's `source_flags` is named `typed_fields`, and an unknown contest type is stored as `""` (shown as "Type not set") instead of `other`.
- **Placeholder scan:** commit trailers use `<model>` deliberately (each implementer names itself). No TBDs.
- **Type consistency:** `players` is a comma-joined string of dk_ids everywhere (entries, my_builds, search); `slate_date` is an ISO date string everywhere; `contest_type` is a `CONTEST_TYPES` key or `""`.

## Build notes

Fixes made during review (all on branch `my-results`, suite green with `-W error`):

- Totals follow every filter (season, contest type, lineup source), not just the season.
- Missing numbers in player history and box scores show "—" by pre-formatting them as strings
  (`ui.display_numbers`), since Streamlit's column formats render NaN as "None".
- "My entry" in player history lists every one of Nathan's entries that week (multi-entry), not just the first.
- Final review wave:
  - Edit row offers "Type not set" and leaves blank fee/winnings empty; Save sends only changed fields, so blanks
    are never silently turned into Head-to-Head / $0 and marked typed.
  - `processed/slate_lineups/` appends every build with `built_at` (identical lineups de-duplicated);
    `entries.lineup_source` prefers the entry's contest type, then the latest build; older files without
    `built_at` still work.
  - Contest-list save, player-history upsert, lineup archive (now after `write_published`) and the nflverse
    actual-points fill can't stop a live stage — a failure becomes "; WARNING: … failed (<ExcType>)" on the step,
    and the app banner shows any step message containing "WARNING".
  - Results import: reading Nathan's entries and saving player-history actuals each fail soft ("entries not read
    (<ExcType>)" / a WARNING note); the file still imports and moves to done.
  - Season filter uses the NFL season (`config.season_for`), so January weeks 17-18 count toward the prior season.
  - Entry expander labels escape `$`; a save whose publish failed shows a yellow warning instead of green success.
  - `tuesday` stage now publishes so actual points reach the phone.
  - `_save_contests` skips empty frames (no pandas concat FutureWarning); `record_my_build` never breaks a download.
