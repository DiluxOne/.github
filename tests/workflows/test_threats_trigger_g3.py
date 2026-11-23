"""#958 C3: a deterministic trigger for threats. When a change or its Spec
touches an input, a permission, authentication, a secret or a workflow
(policy/threats.yml, and the kind's `threats:` in its surface.yml), G3 needs
the `Spec: threats` section whatever the issue's Type, and says why;
otherwise the schema is as it was. The draft's G3 passes the kind, and the
auto-merge decision checks it again on the Spec and on the change."""
import importlib.util
import json
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
