"""A test that fails once and passes on its retry (#479 C4): the E2E job runs
Playwright's own command with one retry and its JSON report, a run whose only
failure passed on its retry passes (the pull request stays in the queue), and
the test is reported as flaky with its spec and line. The report is a fixture
of Playwright's JSON reporter; npx is stood in."""
import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/workflows/fixtures/playwright-flaky-report.json"


def e2e_steps():
    wf = yaml.safe_load((ROOT / ".github/workflows/plugin-tests-wp.yml").read_text(encoding="utf-8"))
    return wf["jobs"]["e2e"]["steps"]


def report_in(tmp_path):
    """The fixture, as Playwright writes it from this checkout."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["config"]["rootDir"] = str(tmp_path / "tests" / "e2e")
    return data


def test_a_flaky_test_is_listed_with_its_spec_and_line(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report_in(tmp_path)))
    out = subprocess.run(["python3", str(ROOT / "scripts/flaky.py"), "list", str(path)], cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0
    assert [json.loads(l) for l in out.stdout.splitlines()] == [{"spec": "tests/e2e/login.spec.ts", "line": 14, "title": "a member logs in"}]


def test_the_run_passes_and_the_job_reports_it(tmp_path):
    # Playwright with one retry: the test failed, then passed, so it exits 0
    # and writes its report where PLAYWRIGHT_JSON_OUTPUT_NAME says.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "fixture.json").write_text(json.dumps(report_in(tmp_path)))
    (bin_dir / "npx").write_text('#!/bin/sh\necho "npx $*" >> calls.log\ncp fixture.json "$PLAYWRIGHT_JSON_OUTPUT_NAME"\nexit 0\n')
    (bin_dir / "npx").chmod(0o755)
    run = next(s for s in e2e_steps() if s.get("name") == "Run the suite")
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", RUN="npx playwright test", TARGETED="", SITE="single",
               CENTRAL=str(ROOT), FLAKY_REPORT=run["env"]["FLAKY_REPORT"])
    ran = subprocess.run(["bash", str(ROOT / "scripts/e2e-run.sh"), "run"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr
    assert "--retries=1 --reporter=list,json" in (tmp_path / "calls.log").read_text()
    summary = tmp_path / "summary.md"
    flaky = next(s for s in e2e_steps() if s.get("name") == "The flaky tests")
    assert run["env"]["FLAKY_REPORT"] in flaky["run"] and flaky["if"].startswith("always()")
    out = subprocess.run(["python3", str(ROOT / "scripts/flaky.py"), "annotate", run["env"]["FLAKY_REPORT"]], cwd=tmp_path,
                         env=dict(os.environ, GITHUB_STEP_SUMMARY=str(summary)), capture_output=True, text=True)
    assert out.returncode == 0
    assert out.stdout.startswith("::warning file=tests/e2e/login.spec.ts,line=14,title=Flaky test::a member logs in failed, then passed on its retry")
    assert "`tests/e2e/login.spec.ts:14` a member logs in" in summary.read_text()


def test_the_flaky_step_never_fails_the_job_and_runs_after_the_suite():
    steps = e2e_steps()
    names = [s.get("name") for s in steps]
    assert names.index("Run the suite") < names.index("The flaky tests")
    flaky = steps[names.index("The flaky tests")]
    assert "continue-on-error" not in flaky  # flaky.py exits 0 on any report
    assert "test ! -f .dx-central/scripts/flaky.py ||" in flaky["run"]
