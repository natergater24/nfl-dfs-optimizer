import plistlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "scripts" / "launchagents"
EXPECTED = {"tuesday": (2, 9, 0), "thursday": (4, 9, 0), "sunday": (0, 9, 0), "sunday_late": (0, 11, 45)}


def _render(name):
    text = (TEMPLATES / f"com.nfldfs.{name}.plist.template").read_text()
    return plistlib.loads(text.replace("__PROJECT__", "/p").replace("__HOME__", "/h").encode())


@pytest.mark.parametrize("name", list(EXPECTED))
def test_calendar_agents(name):
    p = _render(name)
    assert p["Label"] == f"com.nfldfs.{name}"
    assert p["ProgramArguments"] == ["/bin/bash", "/p/scripts/run_stage.sh", name]
    sci = p["StartCalendarInterval"]
    assert (sci["Weekday"], sci["Hour"], sci["Minute"]) == EXPECTED[name]


def test_results_agent_watches_downloads():
    p = _render("results")
    assert p["WatchPaths"] == ["/h/Downloads"] and p["ProgramArguments"][-1] == "results"
    assert "StartCalendarInterval" not in p


@pytest.mark.parametrize("script", ["scripts/run_stage.sh", "scripts/install_schedule.sh",
                                    "scripts/uninstall_schedule.sh", "scripts/make_desktop_launcher.sh", "launch.sh"])
def test_scripts_parse_and_are_executable(script):
    path = ROOT / script
    assert path.stat().st_mode & 0o111
    subprocess.run(["bash", "-n", str(path)], check=True)


def test_sunday_agent_abandons_process_group():
    # run_stage.sh leaves a background caffeinate running through the 11:45 run;
    # launchd must not kill it when the 9:00 job exits.
    assert _render("sunday")["AbandonProcessGroup"] is True


def test_scheduled_stages_declare_user_active():
    # Without -u a battery dark wake goes back to sleep mid-run (Oct 2026: builds took hours).
    text = (ROOT / "scripts/run_stage.sh").read_text()
    assert "caffeinate -dimsu" in text
    for stage in ("sunday)", "tuesday|thursday|sunday_late)"):
        assert stage in text
