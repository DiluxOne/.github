"""#958 C4: the autopilot's self-review before it finishes keeps to the logic
and the acceptance criteria. What the gate checks (security, documentation:
the security tools and the documentation check of #956/#957, run by `make
pre-pr` through the helper's `check`) is no longer re-read by the model
against the whole review profile: the prompt points to the gate's result."""
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ap = load("autopilot")


def prompt(kind="wordpress-plugin"):
    return ap.prompt_work("o/r", "7", "8", "feat/7-x", "x", [("C1", "a", None)], False, notes=(kind, ()))


def self_review(text):
    m = re.search(r"^1\. Review your own change.*$", text, re.M)
    assert m, "the work prompt has its self-review step"
    return m.group(0)


def test_c4_the_self_review_asks_for_the_logic_and_the_criteria():
    step = self_review(prompt())
    assert "logic" in step and "acceptance criteri" in step, step
    assert 'git diff "$DX_BASE"...HEAD' in step and "local-review.sh" in step


def test_c4_it_points_to_the_gates_result_for_security_and_documentation():
    step = self_review(prompt())
    assert "make pre-pr" in step and "security" in step and "documentation" in step, step
    assert f"{ap.HELPER} check" in step, "the gate's result, as the helper's check prints it"


def test_c4_it_no_longer_names_the_whole_review_profile():
    for kind in ("wordpress-plugin", ""):
        text = prompt(kind)
        assert "review-profiles/general.md" not in text
        assert "review-profile.md" not in text


def test_c4_the_kinds_rules_are_pointed_to_through_their_deterministic_checker():
    step = self_review(prompt())
    assert "review-rules.php --kind wordpress-plugin" in step, step
    assert "review-rules.php" not in self_review(prompt(""))
