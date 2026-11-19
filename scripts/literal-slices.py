#!/usr/bin/env python3
"""A test cuts a workflow's text between two literals (#845).

A test that slices a file between two quoted sentences
(`text[text.index("- name: Push"):text.index("- name: Next")]`, or
`text.split("jobs:")[1]`) breaks when a sentence is reworded and passes
when the behaviour between them breaks: it tests the wording, not what
the step does. A workflow's step is tested by running it (find it by name
or id through YAML, run its `run:` with stubs on PATH,
tests/workflows/steps.py), or by calling the script under scripts/ that
holds its logic.

This reads test files with Python's `ast` module and reports
`path:line (function)` for each place where a test cuts text between
literals:

- a slice whose bound calls `.index/.find/.rindex/.rfind("literal")`, or
  is a name assigned from such a call in the same function;
- a fixed index into `.split/.partition/.rpartition("literal")`.

The files that still slice are listed in KNOWN, which can only shrink: a
listed file that no longer slices fails the check too, so it is removed
from the list in the change that fixes it.

    literal-slices.py [dir-or-file ...]   default: tests/workflows tests/repro
    literal-slices.py --test
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINDS = {"index", "find", "rindex", "rfind"}
SPLITS = {"split", "partition", "rpartition", "rsplit"}

# Files that sliced text before the check existed. Only shrinks.
KNOWN = {
    "tests/repro/test_issue_549.py",
    "tests/repro/test_issue_556.py",
    "tests/repro/test_issue_575.py",
    "tests/repro/test_issue_577.py",
    "tests/repro/test_issue_696.py",
    "tests/repro/test_issue_774.py",
    "tests/workflows/test_autopilot_cancelled_review.py",
    "tests/workflows/test_autopilot_commit_cadence.py",
    "tests/workflows/test_autopilot_main_merge.py",
    "tests/workflows/test_autopilot_pre_pr.py",
    "tests/workflows/test_autopilot_rounds.py",
    "tests/workflows/test_autopilot_sweep_draft.py",
    "tests/workflows/test_autopilot_sweep_on_merge.py",
    "tests/workflows/test_battery_doc.py",
    "tests/workflows/test_claim_wiring.py",
    "tests/workflows/test_claimed_bug_wiring.py",
    "tests/workflows/test_configuration_doc.py",
    "tests/workflows/test_confirmed_bug_no_acceptance.py",
    "tests/workflows/test_conventions_fix_round.py",
    "tests/workflows/test_core_queue_one_at_a_time.py",
    "tests/workflows/test_credits_wiring.py",
    "tests/workflows/test_decision_sub_issue_start.py",
    "tests/workflows/test_edit_starts_autopilot.py",
    "tests/workflows/test_flow_label_words.py",
    "tests/workflows/test_hint_without_needs_human.py",
    "tests/workflows/test_issue_803_labels.py",
    "tests/workflows/test_issue_805_labels.py",
    "tests/workflows/test_maintainer_bug_wiring.py",
    "tests/workflows/test_marker_one_check.py",
    "tests/workflows/test_plugin_release_ai.py",
    "tests/workflows/test_policy_floor_files_wiring.py",
    "tests/workflows/test_policy_on_receipts.py",
    "tests/workflows/test_pr_screenshots_wiring.py",
    "tests/workflows/test_queue_drop_fix.py",
    "tests/workflows/test_release_bug_reproduced.py",
    "tests/workflows/test_release_lane_wiring.py",
    "tests/workflows/test_repro_board_state.py",
    "tests/workflows/test_required_checks.py",
    "tests/workflows/test_settled_finding_rerun.py",
    "tests/workflows/test_test_first.py",
    "tests/workflows/test_triage_non_write_users.py",
    "tests/workflows/test_who_decides_wiring.py",
}


def is_literal(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str) or isinstance(node, ast.JoinedStr)


def literal_call(node, names):
    """True when NODE (an expression) calls .index/.find/... on a literal,
    or uses a name in NAMES (assigned from one)."""
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr in FINDS
                and sub.args and is_literal(sub.args[0])):
            return True
        if isinstance(sub, ast.Name) and sub.id in names:
            return True
    return False


def fixed_index(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return True
    return isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and fixed_index(node.operand)


def hits_in(func):
    """[(line, name)] of the literal slices in FUNC's own body (nested
    functions are reported under their own name)."""
    nodes, stack = [], list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        nodes.append(node)
        stack.extend(ast.iter_child_nodes(node))
    names = set()
    changed = True
    while changed:
        changed = False
        for node in nodes:
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and node.value is not None and literal_call(node.value, names):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    for sub in ast.walk(target):
                        if isinstance(sub, ast.Name) and sub.id not in names:
                            names.add(sub.id)
                            changed = True
    out = []
    for node in nodes:
        if not isinstance(node, ast.Subscript):
            continue
        cut = node.slice
        if isinstance(cut, ast.Slice):
            if any(b is not None and literal_call(b, names) for b in (cut.lower, cut.upper)):
                out.append((node.lineno, func.name))
        elif (fixed_index(cut) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
              and node.value.func.attr in SPLITS and node.value.args and is_literal(node.value.args[0])):
            out.append((node.lineno, func.name))
    return out


def scan(source, path="<test>"):
    """[(line, function)] of the literal slices in SOURCE. Pure."""
    tree = ast.parse(source, path)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.extend(hits_in(node))
    return sorted(set(out))


def files_of(args):
    out = []
    for arg in args:
        full = arg if os.path.isabs(arg) else os.path.join(ROOT, arg)
        if os.path.isfile(full):
            out.append(full)
            continue
        for base, dirs, files in os.walk(full):
            dirs[:] = sorted(d for d in dirs if d not in ("fixtures", "__pycache__"))
            out.extend(os.path.join(base, f) for f in sorted(files) if f.startswith("test_") and f.endswith(".py"))
    return out


def check(args, known=None):
    """(exit code, lines to print) for the files under ARGS."""
    known = KNOWN if known is None else known
    lines, seen = [], set()
    for full in files_of(args):
        rel = os.path.relpath(full, ROOT)
        with open(full, encoding="utf-8") as f:
            found = scan(f.read(), rel)
        if not found:
            continue
        seen.add(rel)
        if rel in known:
            continue
        for line, name in found:
            lines.append(f"{rel}:{line} ({name}) cuts text between literals: test what the step does "
                         "(run it, tests/workflows/steps.py, or call its script), not its wording")
    scanned = {os.path.relpath(f, ROOT) for f in files_of(args)}
    for rel in sorted(known & scanned - seen):
        lines.append(f"{rel} no longer cuts text between literals: remove it from KNOWN in scripts/literal-slices.py")
    return (1 if lines else 0), lines


def self_test():
    import tempfile
    cases = [
        ("def test_a():\n    t = open('w').read()\n    s = t[t.index('- name: A'):t.index('- name: B')]\n", [(3, "test_a")]),
        ("def test_a():\n    t = ''\n    i = t.find('x') + 1\n    j = t.index('y', i)\n    return t[i:j]\n", [(5, "test_a")]),
        ("def test_a():\n    return ''.split('jobs:')[1]\n", [(2, "test_a")]),
        ("def test_a():\n    return ''.partition('x')[-1]\n", [(2, "test_a")]),
        ("def test_a(n):\n    return ''.split(n)[1]\n", []),
        ("def test_a():\n    return ''.split()[0]\n", []),
        ("def test_a():\n    t = ''\n    return t[:t.index(f'x {1}')]\n", [(3, "test_a")]),
        ("def test_a():\n    t = 'a b'\n    return t[2:5], t[t.index(' '):]\n", [(3, "test_a")]),
        ("def test_a(t, k):\n    return t[t.index(k):]\n", []),
        ("def step(t):\n    return t[t.index('x'):]\n", [(2, "step")]),
        ("def test_a():\n    i = ''.index('x')\n    def inner(t):\n        return t[i:]\n    return inner\n", []),
        ("def test_a():\n    return 'x' in ''\n", []),
    ]
    bad = 0
    for source, want in cases:
        got = scan(source)
        if got != want:
            bad += 1
            print(f"FAIL scan({source!r}) = {got}, want {want}")
    with tempfile.TemporaryDirectory() as tmp:
        new = os.path.join(tmp, "test_new.py")
        with open(new, "w") as f:
            f.write("def test_new():\n    t = ''\n    return t[t.index('a'):t.index('b')]\n")
        clean = os.path.join(tmp, "test_clean.py")
        with open(clean, "w") as f:
            f.write("def test_clean():\n    assert True\n")
        rel_new, rel_clean = os.path.relpath(new, ROOT), os.path.relpath(clean, ROOT)
        for args, known, want_code, want_in in [
            ([tmp], set(), 1, f"{rel_new}:3 (test_new)"),
            ([tmp], {rel_new}, 0, None),
            ([tmp], {rel_new, rel_clean}, 1, f"{rel_clean} no longer cuts"),
            ([clean], {rel_new}, 0, None),
        ]:
            code, lines = check(args, known)
            if code != want_code or (want_in and not any(want_in in line for line in lines)):
                bad += 1
                print(f"FAIL check({args}, {known}) = {code}, {lines}")
    print("literal-slices: self-test", "failed" if bad else "passed")
    return 1 if bad else 0


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    code, lines = check(argv or ["tests/workflows", "tests/repro"])
    for line in lines:
        print(f"::error::{line}")
    if not code:
        print(f"literal-slices: no new test cuts text between literals ({len(KNOWN)} files still listed in KNOWN)")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
