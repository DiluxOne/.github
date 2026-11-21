"""#924 C2: a long thread never stops a round before the model starts.

Prep's work branch writes a prompt that holds only the deciders' comments
since the autopilot's last end, as `<answers>` documents inside a bound,
and the work job hands the action a short pointer to that file instead of
its text, so the `prompt` input stays far under the system's limit on one
environment variable (about 128 KiB, "Argument list too long", #830)."""
import json
import re
import subprocess

from steps import run, step

STOP = "<!-- dx-autopilot-stop -->"
KIB = 1024
LIMIT = 128 * KIB
BODY = """### Problem

The greeting is missing.

### Acceptance criteria

- C1: Given the page, when it loads, then it greets.

### Criticality

Low
"""
PR_BODY = """## 📝 What changes

The greeting.

## 🎯 Acceptance criteria

<!-- dx-checklist -->
- [ ] **C1** Given the page, when it loads, then it greets.
  Test: tests/test_greeting.py
<!-- /dx-checklist -->
"""
# More than 200 KiB of the decider's comments before the bot's last end,
# one answer after it.
OLD = [{"body": f"OLD-{i} " + "x" * (10 * KIB), "createdAt": f"2026-11-20T0{i // 10}:{i % 10:02d}:00Z", "author": {"login": "boss"}}
       for i in range(21)]
COMMENTS = OLD + [
    {"body": f"{STOP}\nThe autopilot stopped.", "createdAt": "2026-11-20T09:00:00Z", "author": {"login": "dilux-bot"}},
    {"body": "NEW: use greeting.txt.", "createdAt": "2026-11-20T10:00:00Z", "author": {"login": "boss"}},
]
assert sum(len(c["body"]) for c in OLD) > 200 * KIB

GH = """exec python3 "$DX_GH" "$@"
"""
FAKE_GH = r'''import json, sys
args = sys.argv[1:]
comments = json.load(open(sys.argv[0].rsplit("/", 1)[0] + "/comments.json"))
def jq(value):
    if "--jq" in args:
        expr = args[args.index("--jq") + 1]
        if expr == ".comments":
            value = value["comments"]
        elif expr == ".body":
            print(value["body"]); return
        elif expr == ".headRefOid":
            print("abc"); return
    print(json.dumps(value))
if args[:2] == ["pr", "view"]:
    jq({"body": PR_BODY, "comments": comments, "isDraft": True, "headRefOid": "abc", "labels": [], "number": 8})
elif args[:2] == ["issue", "view"]:
    jq({"body": BODY, "comments": [], "author": {"login": "boss"}, "url": "https://github.com/o/r/issues/7", "labels": []})
elif args[:1] == ["api"] and "events" in args[1]:
    print("2026-11-19T08:00:00Z")
elif args[:1] == ["api"]:
    print("[]")
else:
    print("{}")
'''


def prep(tmp_path):
    (tmp_path / "temp").mkdir(parents=True, exist_ok=True)
    (tmp_path / "temp" / "body.md").write_text(BODY, encoding="utf-8")
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "comments.json").write_text(json.dumps(COMMENTS), encoding="utf-8")
    (fake / "gh.py").write_text(f"PR_BODY = {PR_BODY!r}\nBODY = {BODY!r}\n" + FAKE_GH, encoding="utf-8")
    fixture, org_yml = tmp_path / "deciders.json", tmp_path / "org.yml"
    fixture.write_text(json.dumps({"roles": {"boss": "admin"}}), encoding="utf-8")
    org_yml.write_text("who-decides: writers\n", encoding="utf-8")
    ran = run(step("autopilot.yml", "task", "prep"), tmp_path, stubs={"gh": GH},
              env={"MODE": "work", "NUMBER": "7", "PR": "8", "BRANCH": "fix/7-greeting", "LANE": "standard", "BASE": "main",
                   "DX_GH": str(fake / "gh.py"), "DECIDERS_FIXTURE": str(fixture), "DX_ORG_YML": str(org_yml)})
    assert ran.code == 0, ran.stderr + ran.stdout
    return (tmp_path / "work" / ".dx-io" / "prompt.md").read_text(encoding="utf-8")


def test_the_work_prompt_holds_only_the_comments_since_the_last_end_inside_the_bound(tmp_path):
    prompt = prep(tmp_path)
    new, old, size = "NEW: use greeting.txt." in prompt, "OLD-" in prompt, len(prompt.encode("utf-8"))
    assert (new, old) == (True, False), f"a prompt of {size} bytes"
    docs = re.findall(r'<document author="boss" at="([^"]+)">\n(.*?)\n</document>', prompt, re.S)
    assert docs == [("2026-11-20T10:00:00Z", "NEW: use greeting.txt.")], docs
    assert size < 64 * KIB


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_the_action_gets_a_short_pointer_not_the_prompt(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "start")
    git(work, "update-ref", "refs/remotes/origin/main", "HEAD")
    big = "a long task " * (20 * KIB) + "\n"
    ran = run(step("autopilot.yml", "task", "work"), tmp_path, env={"DEFAULT": "main"}, files={".dx-io/prompt.md": big})
    assert ran.code == 0, ran.stderr
    pointer = ran.output["prompt"]
    size = len(pointer.encode("utf-8"))
    assert size < 4 * KIB < LIMIT, f"a prompt input of {size} bytes"
    assert ".dx-io/prompt.md" in pointer and "a long task" not in pointer
    action = step("autopilot.yml", "work", "work")
    assert action["with"]["prompt"] == "${{ steps.task.outputs.prompt }}"


def test_the_spec_job_gets_the_pointer_too(tmp_path):
    ran = run(step("autopilot.yml", "task", "spec"), tmp_path, files={".dx-io/prompt.md": "x" * (200 * KIB) + "\n"})
    assert ran.code == 0, ran.stderr
    pointer = ran.output["prompt"]
    size = len(pointer.encode("utf-8"))
    assert size < 4 * KIB and ".dx-io/prompt.md" in pointer, f"a prompt input of {size} bytes"
