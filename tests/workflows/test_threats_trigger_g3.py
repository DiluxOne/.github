"""#958 C3: a deterministic trigger for threats. When a change or its Spec
touches an input, a permission, authentication, a secret or a workflow
(policy/threats.yml, and the kind's `threats:` in its surface.yml), G3 needs
the `Spec: threats` section whatever the issue's Type, and says why;
otherwise the schema is as it was. The draft's G3 passes the kind, and the
auto-merge decision checks it again on the Spec and on the paths the change
touches, with the organisation's entries."""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PRD = """### Problem

The greeting is wrong.

### Scope

- The greeting.

### Out of scope

- Nothing.

### Acceptance criteria

- C1: Given the page, when it loads, then it greets.

### Criticality

Normal
"""


def spec(files, approach="Say hello in the greeting."):
    return PRD + f"""
### Spec: approach

{approach}

### Spec: files

{files}

### Spec: tests

- C1 → tests/workflows/test_greeting.py
"""


QUIET = spec("- `src/greeting.py`")
WORKFLOW = spec("- `src/greeting.py`\n- `.github/workflows/x.yml`")
SECRET = spec("- `src/greeting.py`", "Read the greeting from `secrets.GREETING_TOKEN` in the job's env.")
THREATS = "\n### Spec: threats\n\n- Tampering: the workflow runs no pull request's code.\n"


def g3(body, kind="engine-test", typ="Bug"):
    ran = subprocess.run([sys.executable, str(ROOT / "scripts" / "issue-schema.py"), "check", "--stage", "spec", "--type", typ, "--kind", kind],
                         input=body, capture_output=True, text=True)
    return ran.returncode, json.loads(ran.stdout or "{}")


def test_c3_a_bug_whose_spec_names_a_workflow_needs_its_threats():
    code, out = g3(WORKFLOW)
    assert code == 1, out
    said = " ".join(out["errors"])
    assert "Spec: threats" in said and ".github/workflows/x.yml" in said, said
    assert g3(WORKFLOW + THREATS)[0] == 0


def test_c3_a_bug_whose_spec_reads_a_secret_needs_its_threats():
    code, out = g3(SECRET)
    assert code == 1 and "Spec: threats" in " ".join(out["errors"]), out
    assert g3(SECRET + THREATS)[0] == 0


def test_c3_a_bug_that_touches_none_does_not():
    code, out = g3(QUIET)
    assert code == 0, out


def test_c3_the_kind_adds_its_own():
    php = spec("- `includes/form.php`", "Call `check_admin_referer( 'dx_save' )` before saving.")
    assert g3(php, "wordpress-plugin")[0] == 1
    assert g3(php, "engine-test")[0] == 0, "the organisation's entries alone do not name it"
    assert g3(spec("- `includes/form.php`"), "wordpress-plugin")[0] == 0


def test_c3_callers_that_pass_no_trigger_keep_todays_result():
    schema = load("issue-schema")
    assert schema.check(WORKFLOW, "spec", issue_type="Bug")["ok"] is True
    assert schema.check(WORKFLOW, "spec", issue_type="Bug", threats=["workflow: a GitHub workflow or action, .github/workflows/x.yml"])["ok"] is False


ap = load("autopilot")
POLICY = {"autopilot": True, "lanes": {ap.LANE: {"enabled": True, "merge": {"max-risk": "high", "max-complexity": "high"}}}}
TEST = "tests/workflows/test_greeting.py"


def decide(body, files):
    threats = ap.g3_threats(body, files, "")
    return ap.decide(POLICY, body, "low", "low", "false", "true", files, files, "", issue_type="Bug", threats=threats)


def test_c3_the_decision_refuses_a_bug_whose_change_touches_a_workflow_without_threats():
    ok, why = decide(QUIET, ["src/greeting.py", ".github/workflows/x.yml", TEST])
    assert ok is False and "threats" in why and ".github/workflows/x.yml" in why, why
    ok, why = decide(QUIET + THREATS, ["src/greeting.py", ".github/workflows/x.yml", TEST])
    assert "threats" not in why, why


def test_c3_the_decision_passes_a_bug_that_touches_none():
    ok, why = decide(QUIET, ["src/greeting.py", TEST])
    assert ok is True, why


def test_c3_the_drafts_g3_passes_the_kind():
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "autopilot.yml").read_text(encoding="utf-8"))
    runs = [s.get("run", "") for s in flow["jobs"]["draft"]["steps"] if "issue-schema.py check --stage spec" in s.get("run", "")]
    assert len(runs) == 1
    assert '--kind "$kind"' in runs[0] and "impact.py kind" in runs[0], "G3 at the draft runs the trigger with the repository's kind"


def test_c3_the_review_checks_the_threats_the_trigger_asks_for():
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "claude-review.yml").read_text(encoding="utf-8"))
    run = next(s["run"] for s in flow["jobs"]["review"]["steps"] if "review-brief.sh" in str(s.get("run", "")))
    assert ".dx-central/scripts/impact.py threats --brief" in run, "the brief carries why, and the Spec's threats section"
    profile = (ROOT / "review-profiles" / "general.md").read_text(encoding="utf-8")
    assert "Threats required" in profile, "the general profile says how the review checks it"


def test_c3_the_spec_prompt_names_the_trigger_when_the_prd_does_not_fire():
    # G3 at the draft runs the trigger on the Spec: a PRD that does not fire
    # still tells the model what makes `Spec: threats` required.
    assert ap.prd_threats(PRD, "") == []
    prompt = ap.prompt_spec("o/r", 7, PRD, issue_type="Bug", watch=ap.threat_watch(""))
    assert "### Spec: threats" in prompt and "if your Spec's files or text touch" in prompt
    assert "a GitHub workflow or action" in prompt and "a secret or a token" in prompt
    fallback = ap.prompt_spec("o/r", 7, PRD, issue_type="Bug")
    assert "an input, a permission, authentication, a secret or a workflow" in fallback
    fired = ap.prompt_spec("o/r", 7, PRD, issue_type="Bug", threats=["workflow: a GitHub workflow or action, .github/workflows/x.yml"])
    assert "required here whatever the issue's Type, because it touches workflow" in fired


def test_c3_g7_reads_the_organisations_entries_and_the_spec_alone():
    # auto-merge.yml's decide step exports no KIND nor THREATS: at G7 the
    # trigger is the organisation's entries on the changed paths and on the
    # Spec's text, and the docs say no more than that.
    flow = (ROOT / ".github" / "workflows" / "auto-merge.yml").read_text(encoding="utf-8")
    wired = "export KIND" in flow or "THREATS=" in flow
    for doc in ("docs/agents.md", "kinds/README.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        assert wired or "again at the auto-merge decision" not in text, doc
        assert wired or "not by the auto-merge decision" in text or "nor the diff's lines" in text, doc


def _threats_snippet(run):
    """The brief step's lines from the threat trigger's run to its `fi`."""
    lines = run.splitlines()
    start = next(i for i, l in enumerate(lines) if "threats --brief" in l and "impact.py" in l)
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "fi")
    return "\n".join(lines[start:end + 1])


def test_c3_the_brief_fails_closed_when_the_trigger_cannot_tell(tmp_path):
    # Exit 2 (it cannot tell) puts "Threats required" in the brief, as the
    # decision fails closed; and so does a fire when the map itself is empty.
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    ran = subprocess.run([sys.executable, str(ROOT / "scripts" / "impact.py"), "threats", "--brief", "--base", "nope", "--head", "HEAD", "--kind", ""],
                         cwd=repo, capture_output=True, text=True)
    assert ran.returncode == 2 and ran.stdout.startswith("Threats required: the trigger could not tell")
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "claude-review.yml").read_text(encoding="utf-8"))
    run = next(s["run"] for s in flow["jobs"]["review"]["steps"] if "review-brief.sh" in str(s.get("run", "")))
    local = (ROOT / "scripts" / "local-review.sh").read_text(encoding="utf-8")
    for name, snippet in (("claude-review.yml", _threats_snippet(run)), ("local-review.sh", _threats_snippet(local))):
        for code, out, want in ((2, "", "the trigger could not tell (impact.py exit 2)"), (2, "Threats required: the trigger could not tell (x)", "(x)"),
                                (1, "Threats required: workflow: w", "workflow: w"), (0, "", None)):
            stub = tmp_path / "bin" / ".dx-central" / "scripts"
            stub.mkdir(parents=True, exist_ok=True)
            (stub / "impact.py").write_text(f"import sys\nprint({out!r}, end='')\nsys.exit({code})\n", encoding="utf-8")
            work = tmp_path / "work"
            work.mkdir(exist_ok=True)
            impact = work / "impact.md"
            impact.write_text("", encoding="utf-8")
            env = {"PATH": "/usr/bin:/bin", "RUNNER_TEMP": str(work), "IMPACT": str(impact), "impact": str(impact), "work": str(work),
                   "CENTRAL": str(tmp_path / "bin" / ".dx-central"), "BASE": "a", "HEAD": "b", "kind": "", "KIND": ""}
            subprocess.run(["bash", "-euo", "pipefail", "-c", snippet.replace("python3 ", f"{sys.executable} ").replace('"$CENTRAL/scripts/impact.py"', ".dx-central/scripts/impact.py")], cwd=tmp_path / "bin", env=env, check=True)
            got = impact.read_text(encoding="utf-8")
            if want is None:
                assert got == "", f"{name}: nothing when it does not fire"
            else:
                assert got.startswith("Threats required") and want in got, f"{name}, exit {code}, empty map: {got!r}"


def test_c3_the_profile_needs_no_section_when_there_is_no_spec():
    # A pull request a person claimed has no Spec: the profile does not call
    # the missing section a major there.
    profile = (ROOT / "review-profiles" / "general.md").read_text(encoding="utf-8")
    assert "there is no Spec to read it from" in profile and "there is no\n   section to miss" in profile
    assert "There is no Spec to read it from" in (ROOT / "scripts" / "impact.py").read_text(encoding="utf-8")


def test_c3_the_threats_part_never_reads_and_writes_the_map_in_one_command(tmp_path):
    # `{ [ -s "$IMPACT" ] && echo; cat ...; } >> "$IMPACT"` is shellcheck's
    # SC2094, which fails actionlint (#974, round 2): the test of the map and
    # the append are two commands. A map with lines keeps them, then a blank
    # line, then the threats part.
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "claude-review.yml").read_text(encoding="utf-8"))
    run = next(s["run"] for s in flow["jobs"]["review"]["steps"] if "review-brief.sh" in str(s.get("run", "")))
    local = (ROOT / "scripts" / "local-review.sh").read_text(encoding="utf-8")
    for name, snippet, var in (("claude-review.yml", _threats_snippet(run), "IMPACT"), ("local-review.sh", _threats_snippet(local), "impact")):
        for line in snippet.splitlines():
            head, appends, _ = line.partition(f'>> "${var}"')
            if appends and not head.lstrip().startswith("if "):
                assert f'"${var}"' not in head, f"{name}: one command reads and appends to the map: {line.strip()}"
        if shutil.which("shellcheck"):
            checked = subprocess.run(["shellcheck", "-s", "bash", "-i", "SC2094", "-"], input=snippet, capture_output=True, text=True)
            assert checked.returncode == 0, f"{name}: {checked.stdout}"
        stub = tmp_path / name / ".dx-central" / "scripts"
        stub.mkdir(parents=True)
        (stub / "impact.py").write_text("import sys\nprint('Threats required: workflow: w', end='')\nsys.exit(1)\n", encoding="utf-8")
        work = tmp_path / name / "work"
        work.mkdir()
        impact = work / "impact.md"
        impact.write_text("the map\n", encoding="utf-8")
        env = {"PATH": "/usr/bin:/bin", "RUNNER_TEMP": str(work), "IMPACT": str(impact), "impact": str(impact), "work": str(work),
               "CENTRAL": str(tmp_path / name / ".dx-central"), "BASE": "a", "HEAD": "b", "kind": "", "KIND": ""}
        subprocess.run(["bash", "-euo", "pipefail", "-c", snippet.replace("python3 ", f"{sys.executable} ").replace('"$CENTRAL/scripts/impact.py"', ".dx-central/scripts/impact.py")], cwd=tmp_path / name, env=env, check=True)
        assert impact.read_text(encoding="utf-8") == "the map\n\nThreats required: workflow: w", name
