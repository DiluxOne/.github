"""About eight labels a person sees (#564, C1): labels.yml holds only the
labels that are a decision or a warning, and no workflow or script adds,
creates, removes or reads a label outside them. Counters and the steps in
between live in the board's state (scripts/receipts.py `state`)."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# What a person sees: the decision, G1, the autopilot and its hand-over, a
# claim, a vulnerability, the review's verdict, and the records the
# maintainer kept (#564's answer: the lanes and what a policy decided, the
# review's type and complexity, the release's version, Dependabot's, the
# weekly run's).
ALLOWED = {
    "accepted", "awaiting-acceptance", "incomplete", "autopilot", "needs-human", "claimed", "security",
    "risk:low", "risk:medium", "risk:high",
    "lane:platform", "lane:bugfix-reproduced", "lane:org-sync", "lane:adopt", "lane:release", "lane:maintainer-bug",
    "accepted-by:policy", "merged-by:policy",
    "run:runner-image", "run:autonomy-digest", "run:claims", "run:waiting", "run:flow-numbers",
    "complexity:low", "complexity:medium", "complexity:high",
    "type:breaking", "type:feat", "type:fix", "type:perf", "type:refactor", "type:style", "type:docs",
    "type:test", "type:ci", "type:build", "type:chore", "type:revert",
    "version:major", "version:minor", "version:patch",
    "dependencies", "github-actions", "npm", "composer", "docker", "ci:weekly",
}

# The security repository's own queue (security-fix.yml, security-patch.yml,
# nightly-review.yml, advisory.py): never in labels.yml nor in any other
# repository. Its patch:* steps are a finding of #564, left to their own
# issue.
SECURITY_QUEUE = {"security:intake", "security:unvetted", "patch:ready", "patch:go", "patch:failed", "patch:pushed", "patch:released", "patch:not-released", "lane:security-carry"}


def labels():
    return yaml.safe_load((ROOT / "labels.yml").read_text(encoding="utf-8"))


def sources():
    files = list((ROOT / ".github/workflows").glob("*.yml")) + [p for p in (ROOT / "scripts").iterdir() if p.is_file()]
    files += list((ROOT / "workflow-templates").glob("*.yml"))
    return [(p, p.read_text(encoding="utf-8")) for p in files]


def test_labels_yml_holds_only_the_allowed_set():
    live = {str(l["name"]) for l in labels() if "retired" not in l}
    assert live == ALLOWED


def test_every_retired_label_is_listed_with_what_it_carries():
    retired = {str(l["name"]): l["retired"] for l in labels() if "retired" in l}
    for name in ("autopilot:run-*", "autopilot:free-*", "autopilot:round-*", "autopilot:continue", "autopilot:answered",
                 "bug:unconfirmed", "repro:no-way", "needs:maintainer", "good first issue", "review:full", "claim:long", "spike"):
        assert name in retired, name
    assert all(isinstance(v, dict) for v in retired.values())
    assert not set(retired) & ALLOWED


def retired_names():
    return [str(l["name"]) for l in labels() if "retired" in l and "*" not in str(l["name"])]


def test_no_counter_label_anywhere():
    # run-N, free-N and round-N are the board's state, never a label.
    for path, text in sources():
        if path.name == "sync-repos.py":
            continue
        for prefix in ("autopilot:run-", "autopilot:free-", "autopilot:round-"):
            assert prefix not in text, f"{path.relative_to(ROOT)} still names {prefix}"


def test_no_workflow_or_script_adds_creates_or_reads_a_retired_label():
    for path, text in sources():
        if path.name == "sync-repos.py":
            continue
        for name in retired_names():
            n = re.escape(name)
            q = rf"""['"]{n}['"]"""
            patterns = [
                rf"--(add|remove)-label[= ]+['\"]?{n}(?![\w:-])",
                rf"label create ['\"]?{n}(?![\w:-])",
                rf"--label[= ]+['\"]?{n}(?![\w:-])",
                rf"labels\.\*\.name, {q}",
                rf"\.name ?== ?{q}",
                rf"index\({q}\)",
                rf"in labels\b.*{q}|{q} in (labels|names|label_names)",
                rf"has_label {q}|has_label {n}\b",
            ]
            for line in text.split("\n"):
                for pat in patterns:
                    assert not re.search(pat, line), f"{path.relative_to(ROOT)}: {name!r} as a label: {line.strip()[:160]}"


def test_every_label_a_workflow_adds_is_allowed():
    for path, text in sources():
        if path.name == "sync-repos.py":
            continue
        for m in re.finditer(r"--(?:add|remove)-label[= ]+(['\"]?)([A-Za-z][\w:.-]*)\1", text):
            name = m.group(2)
            if name.endswith(":") or name.endswith("-"):
                continue
            assert name in ALLOWED | SECURITY_QUEUE, f"{path.relative_to(ROOT)} adds or removes {name!r}"
        for m in re.finditer(r"gh label create (['\"]?)([A-Za-z][\w:.-]*)\1", text):
            assert m.group(2) in ALLOWED | SECURITY_QUEUE, f"{path.relative_to(ROOT)} creates {m.group(2)!r}"
