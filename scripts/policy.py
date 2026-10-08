#!/usr/bin/env python3
"""Deterministic review policy: the ceiling no reviewer can lower.

Reads the organisation defaults (policy/review-policy.default.yml in this
repository) and the calling repository's .github/review-policy.yml, matches
the pull request's changed files against them, and writes to $GITHUB_OUTPUT:

  floor     low | medium | high   the minimum risk this PR can be rated
  trusted   true | false          the author may have a PR auto-merged
  reasons   one line saying why the floor is what it is
  model     the model for this floor (the repository's choice, else the default)
  effort    the reasoning effort for this floor
  budget    the most one review run may spend, in USD
  auto_merge  true | false     whether qualifying pull requests merge on their own
  paid_repository, paid_owner, paid_name, paid_path   the private roadmap of the paid add-on
            (`paid-roadmap:` in the repository's policy), which the issue
            triage reads to classify and never quotes; empty when none

With POLICY_LEVEL=low|medium|high set, the floor is that level (a job that
has no diff, such as the issue triage, asks for the reviewer of a level).

With POLICY_MODE=changes it answers a different question from the same
files and writes instead:

  code          true | false   a changed file matches a `code` pattern
  plugin_check  true | false   a changed file matches a `plugin-check` pattern
  reasons       one line saying which files decided it

That is what the slow suites and Plugin Check are gated on.

The repository says what kind of project it is with `kind:` (a directory of
kinds/ in this repository, e.g. `kind: wordpress-plugin`): the review then
adds that kind's review profile, and the kind's checks read its rules and
settings. Every mode writes `kind` (empty when the repository declares
none); a kind that does not exist fails. With POLICY_MODE=kind it writes,
for the checks of a kind:

  kind      the repository's kind, else KIND_DEFAULT (the workflow's own);
            both given and different fails: the workflow runs another
            kind's battery
  rules     kinds/<kind>/rules.yml, relative to this repository
  profile   kinds/<kind>/review-profile.md
  settings  the pack's `settings` (kinds/<kind>/pack.yml) as compact JSON,
            with the repository's `kind-settings` added: a list in it is
            appended to the pack's, a map merged key by key; a single value
            cannot replace the pack's (a repository adds exceptions, it does
            not turn a gate off), and says so

With POLICY_MODE=issue-gate it writes, for the conventions check:

  required  true | false   a pull request must close an accepted issue
  label     the label that accepts an issue
  trusted   true | false   PR_AUTHOR is a trusted author
  max_lines the most lines PR_AUTHOR's pull request may change; empty when
            the author is trusted or there is no limit

The organisation's `issue-gate` decides both; a repository can set
`required: false` only when the organisation's says `optional: true`.

`policy.py --profile <name>` prints the review profile a workflow's
`profile:` names, relative to this repository: `general`, a kind, an alias
a pack declares (`plugin-wp` is the wordpress-plugin kind), or a file left
in review-profiles/. `policy.py --test`
checks these rules against the organisation's default policy. When no file
could be listed the answer is true for both: an unknown change runs
everything.

Every review setting lives in these two files and nowhere else: `review:`
(`{low|medium|high: {model, effort}}`), `budget-usd:` and `auto-merge:`. The
repository's value wins key by key; what it leaves out stays as the default.

Rules, in order:
  1. Any changed file matching a `high-risk` pattern  -> floor high.
  2. Every changed file matching a `low-risk-eligible` pattern -> floor low.
  3. Anything else -> floor medium.

The model's rating can raise the floor, never lower it. Nothing here reads
the PR title, body or code: only paths and the author's login.
"""
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys


def load_yaml(path):
    if not os.path.exists(path):
        return {}
    # yq on the runners; PyYAML where yq is not installed (a contributor's
    # machine, through scripts/local-review.sh). Both read the same files;
    # PyYAML reads YAML 1.1 (yes/no/on/off are booleans), so the policy files
    # write booleans as true/false only.
    if shutil.which("yq"):
        out = subprocess.run(["yq", "-o=json", ".", path], check=True, capture_output=True, text=True).stdout
        return json.loads(out or "{}") or {}
    try:
        import yaml
    except ImportError:
        sys.exit("policy.py needs yq or PyYAML to read " + path)
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


CENTRAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
KIND_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def pack_path(kind):
    return os.path.join(CENTRAL, "kinds", kind, "pack.yml")


def check_kind(kind):
    """The kind as a string, '' for none; None (after an error) when it is not one."""
    if kind in (None, ""):
        return ""
    kind = str(kind)
    if not KIND_RE.fullmatch(kind) or not os.path.isfile(pack_path(kind)):
        known = sorted(d for d in os.listdir(os.path.join(CENTRAL, "kinds")) if os.path.isfile(pack_path(d))) if os.path.isdir(os.path.join(CENTRAL, "kinds")) else []
        print(f"::error::kind '{kind}' is not a kind of project this organisation knows ({', '.join(known) or 'none'}); see kinds/README.md.")
        return None
    return kind


def merge_settings(pack, repo, where="kind-settings"):
    """The pack's settings with the repository's additions: lists append, maps merge, single values stay the pack's."""
    out = dict(pack or {})
    for key, value in (repo or {}).items():
        if key not in out:
            if isinstance(value, (list, dict)):
                out[key] = value
            else:
                print(f"::warning::{where}.{key}: a single value cannot be set by a repository; ignored.")
        elif isinstance(out[key], list) and isinstance(value, list):
            out[key] = out[key] + [v for v in value if v not in out[key]]
        elif isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = merge_settings(out[key], value, f"{where}.{key}")
        else:
            print(f"::warning::{where}.{key}: a repository can add to the pack's lists, not replace its values; ignored.")
    return out


def kind_mode(repo):
    declared = check_kind(repo.get("kind"))
    fallback = check_kind(os.environ.get("KIND_DEFAULT", ""))
    if declared is None or fallback is None:
        return 1
    if declared and fallback and declared != fallback:
        print(f"::error::the repository declares kind '{declared}', and this workflow runs the checks of '{fallback}'. Call the workflows its pack names (kinds/{declared}/pack.yml).")
        return 1
    kind = declared or fallback
    if not kind:
        print("::error::no kind: the repository declares none (kind: in .github/review-policy.yml) and the workflow names none.")
        return 1
    pack = load_yaml(pack_path(kind))
    settings = merge_settings(pack.get("settings") or {}, repo.get("kind-settings") or {})
    with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
        fh.write(f"kind={kind}\nrules=kinds/{kind}/rules.yml\nprofile=kinds/{kind}/review-profile.md\nsettings={json.dumps(settings, separators=(',', ':'), sort_keys=True)}\n")
    print(f"kind={kind} settings={json.dumps(settings, sort_keys=True)}")
    return 0


LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 :._/-]{0,49}")


def issue_gate(defaults, repo):
    org = defaults.get("issue-gate") or {}
    mine = repo.get("issue-gate") or {}
    required = org.get("required", False) is True
    if mine.get("required") is False and required:
        if org.get("optional") is True:
            required = False
        else:
            print("::warning::issue-gate.required: the organisation does not let a repository turn the gate off; ignored.")
    label = str(org.get("label") or "accepted")
    if not LABEL_RE.fullmatch(label):
        print(f"::error::issue-gate.label '{label}' is not a label name.")
        return 1
    if "label" in mine and mine.get("label") != label:
        print("::warning::issue-gate.label is the organisation's; a repository cannot change it, ignored.")
    trusted = os.environ.get("PR_AUTHOR", "") in repo.get("trusted-authors", defaults.get("trusted-authors", []))
    max_lines = ""
    try:
        org_max = int(defaults.get("max-changed-lines-untrusted", 0) or 0)
        mine_max = int(repo.get("max-changed-lines-untrusted", org_max) or 0)
    except (TypeError, ValueError):
        print("::warning::max-changed-lines-untrusted is not a number; the organisation's value is used.")
        org_max = int(defaults.get("max-changed-lines-untrusted", 0) or 0)
        mine_max = org_max
    if org_max > 0:
        limit = mine_max if 0 < mine_max < org_max else org_max
        if mine_max != limit and "max-changed-lines-untrusted" in repo:
            print("::warning::max-changed-lines-untrusted: a repository can lower the limit, not raise or remove it; ignored.")
        if not trusted:
            max_lines = str(limit)
    with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
        fh.write(f"required={'true' if required else 'false'}\nlabel={label}\ntrusted={'true' if trusted else 'false'}\nmax_lines={max_lines}\n")
    print(f"issue-gate required={'true' if required else 'false'} label={label}")
    return 0


def profile_path(name):
    """The review profile a `profile:` names, relative to this repository, or None."""
    if name == "general":
        return "review-profiles/general.md"
    if KIND_RE.fullmatch(name or ""):
        if os.path.isfile(os.path.join(CENTRAL, "kinds", name, "review-profile.md")):
            return f"kinds/{name}/review-profile.md"
        kinds_dir = os.path.join(CENTRAL, "kinds")
        for kind in sorted(os.listdir(kinds_dir)) if os.path.isdir(kinds_dir) else []:
            if os.path.isfile(pack_path(kind)) and name in (load_yaml(pack_path(kind)).get("aliases") or []):
                return f"kinds/{kind}/review-profile.md"
        if os.path.isfile(os.path.join(CENTRAL, "review-profiles", name + ".md")):
            return f"review-profiles/{name}.md"
    return None


def glob_to_regex(pattern):
    # ** crosses directories, * and ? do not. "docs/**" matches everything under docs/.
    i, out = 0, ""
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile("^" + out + "$")


def matches(path, patterns):
    return any(glob_to_regex(p).match(path) for p in patterns)


def changes(defaults, repo, files):
    code = defaults.get("code", []) + repo.get("code", [])
    plugin_check = defaults.get("plugin-check", []) + repo.get("plugin-check", [])
    if not files:
        hit_code, hit_check = True, True
        reasons = "no changed files could be listed; everything runs"
    else:
        code_hits = [f for f in files if matches(f, code)]
        check_hits = [f for f in files if matches(f, plugin_check)]
        hit_code, hit_check = bool(code_hits), bool(check_hits)
        if code_hits:
            reasons = "code changed: " + ", ".join(code_hits[:5]) + (" …" if len(code_hits) > 5 else "")
        elif check_hits:
            reasons = "no code changed; Plugin Check reads: " + ", ".join(check_hits[:5])
        else:
            reasons = "no code changed"
    with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
        fh.write(f"code={'true' if hit_code else 'false'}\nplugin_check={'true' if hit_check else 'false'}\nreasons={reasons}\n")
    print(f"code={'true' if hit_code else 'false'} plugin_check={'true' if hit_check else 'false'} ({reasons})")
    return 0


def main():
    defaults = load_yaml(os.environ["DEFAULT_POLICY"])
    repo = load_yaml(os.environ.get("REPO_POLICY", ".github/review-policy.yml"))
    files = [f for f in os.environ.get("CHANGED_FILES", "").splitlines() if f.strip()]
    if os.environ.get("POLICY_MODE", "") == "kind":
        return kind_mode(repo)
    kind = check_kind(repo.get("kind"))
    if kind is None:
        return 1
    with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
        fh.write(f"kind={kind}\n")
    if os.environ.get("POLICY_MODE", "") == "changes":
        return changes(defaults, repo, files)
    if os.environ.get("POLICY_MODE", "") == "issue-gate":
        return issue_gate(defaults, repo)
    author = os.environ.get("PR_AUTHOR", "")
    forced = os.environ.get("POLICY_LEVEL", "")
    if forced and forced not in ("low", "medium", "high"):
        print(f"::error::POLICY_LEVEL '{forced}' is not low, medium or high.")
        return 1

    high = defaults.get("high-risk", []) + repo.get("high-risk", [])
    low = defaults.get("low-risk-eligible", []) + repo.get("low-risk-eligible", [])
    trusted_authors = repo.get("trusted-authors", defaults.get("trusted-authors", []))

    high_hits = [f for f in files if matches(f, high)]
    if forced:
        floor, reasons = forced, f"level {forced} requested by the caller"
    elif not files:
        floor, reasons = "high", "no changed files could be listed"
    elif high_hits:
        floor = "high"
        shown = ", ".join(high_hits[:5]) + (" …" if len(high_hits) > 5 else "")
        reasons = f"touches high-risk paths: {shown}"
    elif all(matches(f, low) for f in files):
        floor, reasons = "low", "every changed file is low-risk eligible"
    else:
        others = [f for f in files if not matches(f, low)]
        floor = "medium"
        reasons = "changes code outside the low-risk paths: " + ", ".join(others[:5]) + (" …" if len(others) > 5 else "")

    trusted = "true" if author in trusted_authors else "false"
    level = {**((defaults.get("review") or {}).get(floor) or {}), **((repo.get("review") or {}).get(floor) or {})}
    model = str(level.get("model") or "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", model):
        print(f"::error::review.{floor}.model '{model}' is not a model id.")
        return 1
    effort = str(level.get("effort") or "medium")
    if effort not in ("low", "medium", "high", "xhigh", "max"):
        print(f"::warning::review.{floor}.effort '{effort}' is not low, medium, high, xhigh or max; using medium.")
        effort = "medium"
    budget = repo.get("budget-usd", defaults.get("budget-usd", 3))
    try:
        value = float(budget)
        if not (0 < value < 1000):
            raise ValueError
        budget = f"{value:g}"
    except (TypeError, ValueError):
        print(f"::warning::budget-usd '{budget}' is not a positive number below 1000; using 3.")
        budget = "3"
    # The organisation's false stops every repository; a repository can only
    # turn auto-merge off for itself, never on when the organisation says no.
    auto_merge = defaults.get("auto-merge", False) is True and repo.get("auto-merge", True) is not False
    auto_merge = "true" if auto_merge else "false"
    paid = repo.get("paid-roadmap") or {}
    paid_repository, paid_path = str(paid.get("repository") or ""), str(paid.get("path") or "docs/roadmap.md")
    if paid_repository and (not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", paid_repository) or not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", paid_path) or ".." in paid_path.split("/")):
        print(f"::error::paid-roadmap '{paid_repository}:{paid_path}' is not an owner/repository and a relative path.")
        return 1
    if not paid_repository:
        paid_path = ""
    with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
        fh.write(f"floor={floor}\ntrusted={trusted}\nreasons={reasons}\nmodel={model}\neffort={effort}\nbudget={budget}\nauto_merge={auto_merge}\npaid_repository={paid_repository}\npaid_owner={paid_repository.split('/')[0] if paid_repository else ''}\npaid_name={paid_repository.split('/')[-1] if paid_repository else ''}\npaid_path={paid_path}\n")
    print(f"floor={floor} trusted={trusted} ({reasons}) model={model} effort={effort} budget={budget} auto-merge={auto_merge}")


def run_case(defaults_path, repo_text, files, **env):
    """main() with this policy and these files; (exit code, outputs)."""
    import contextlib
    import io
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo_path = os.path.join(tmp, "repo.yml")
        with open(repo_path, "w", encoding="utf-8") as fh:
            fh.write(repo_text)
        out_path = os.path.join(tmp, "out")
        open(out_path, "w").close()
        saved = dict(os.environ)
        os.environ.update({"DEFAULT_POLICY": defaults_path, "REPO_POLICY": repo_path, "CHANGED_FILES": "\n".join(files), "GITHUB_OUTPUT": out_path})
        for key in ("PR_AUTHOR", "POLICY_LEVEL", "POLICY_MODE", "KIND_DEFAULT"):
            os.environ.pop(key, None)
        os.environ.update(env)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = main() or 0
        finally:
            os.environ.clear()
            os.environ.update(saved)
        with open(out_path, encoding="utf-8") as fh:
            outputs = dict(line.split("=", 1) for line in fh.read().splitlines() if "=" in line)
        return code, outputs


def self_test():
    """The rules above against the organisation's own default policy."""
    import tempfile
    here = os.path.dirname(os.path.abspath(__file__))
    default = os.path.join(here, "..", "policy", "review-policy.default.yml")
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as fh:
        fh.write("auto-merge: false\nreview:\n  low: {model: claude-sonnet-5-5}\n  medium: {model: claude-sonnet-5-5}\n  high: {model: claude-sonnet-5-5}\n")
        org_off = fh.name
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as fh:
        fh.write("issue-gate:\n  required: true\n  label: accepted\n  optional: true\n")
        gate_optional = fh.name
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as fh:
        fh.write("issue-gate:\n  required: true\n  label: \"$(id)\"\n")
        gate_bad = fh.name
    cases = [
        # (name, defaults, repo policy, files, extra env, expected outputs, expected exit)
        ("docs only is low", default, "", ["docs/a.md", "README.md"], {}, {"floor": "low", "model": "claude-sonnet-5-5"}, 0),
        ("tests and translations only are low", default, "", ["tests/Unit/ATest.php", "languages/x.pot"], {}, {"floor": "low"}, 0),
        ("compiled translations are not low: nobody can read them", default, "", ["languages/x-es_AR.mo"], {}, {"floor": "medium"}, 0),
        ("their sources and template are", default, "", ["languages/x-es_AR.po", "languages/x.pot"], {}, {"floor": "low"}, 0),
        ("code is medium", default, "", ["includes/a.php"], {}, {"floor": "medium", "model": "claude-sonnet-5-5", "effort": "medium"}, 0),
        ("a workflow gets high effort", default, "", [".github/workflows/a.yml"], {}, {"floor": "high", "model": "claude-sonnet-5-5", "effort": "high"}, 0),
        ("docs plus code is medium", default, "", ["docs/a.md", "includes/a.php"], {}, {"floor": "medium"}, 0),
        ("a workflow is high", default, "", [".github/workflows/a.yml"], {}, {"floor": "high"}, 0),
        ("AGENTS.md is high, though it is Markdown", default, "", ["AGENTS.md"], {}, {"floor": "high"}, 0),
        ("the Makefile is high", default, "", ["Makefile", "docs/a.md"], {}, {"floor": "high"}, 0),
        ("a rename out of a high-risk path is high", default, "", ["docs/old-workflow.yml", ".github/workflows/old.yml"], {}, {"floor": "high"}, 0),
        ("no listed files is high", default, "", [], {}, {"floor": "high"}, 0),
        ("the repository adds a high-risk path", default, "high-risk:\n  - \"includes/providers/**\"\n", ["includes/providers/a.php"], {}, {"floor": "high"}, 0),
        ("the repository widens low risk", default, "low-risk-eligible:\n  - \"examples/**\"\n", ["examples/a.php"], {}, {"floor": "low"}, 0),
        ("a trusted author", default, "", ["docs/a.md"], {"PR_AUTHOR": "soydiloreto"}, {"trusted": "true"}, 0),
        ("anyone else is not trusted", default, "", ["docs/a.md"], {"PR_AUTHOR": "someone"}, {"trusted": "false"}, 0),
        ("the repository turns auto-merge off", default, "auto-merge: false\n", ["docs/a.md"], {}, {"auto_merge": "false"}, 0),
        ("the repository cannot turn it on against the organisation", org_off, "auto-merge: true\n", ["docs/a.md"], {}, {"auto_merge": "false"}, 0),
        ("the repository picks the model of a level", default, "review:\n  low: {model: claude-haiku-4-5-20251001}\n", ["docs/a.md"], {}, {"model": "claude-haiku-4-5-20251001", "effort": "low"}, 0),
        ("a model id that is not one fails", default, "review:\n  low: {model: \"rm -rf /\"}\n", ["docs/a.md"], {}, {}, 1),
        ("a budget out of range falls back to 3", default, "budget-usd: 5000\n", ["docs/a.md"], {}, {"budget": "3"}, 0),
        ("a caller can ask for a level", default, "", ["docs/a.md"], {"POLICY_LEVEL": "high"}, {"floor": "high"}, 0),
        ("a level that is not one fails", default, "", ["docs/a.md"], {"POLICY_LEVEL": "huge"}, {}, 1),
        ("changes: PHP is code", default, "", ["includes/a.php"], {"POLICY_MODE": "changes"}, {"code": "true"}, 0),
        ("changes: docs are not code", default, "", ["docs/a.md"], {"POLICY_MODE": "changes"}, {"code": "false"}, 0),
        ("changes: nothing listed runs everything", default, "", [], {"POLICY_MODE": "changes"}, {"code": "true", "plugin_check": "true"}, 0),
        ("no kind declared: kind is empty", default, "", ["docs/a.md"], {}, {"kind": "", "floor": "low"}, 0),
        ("a declared kind is exposed", default, "kind: wordpress-plugin\n", ["docs/a.md"], {}, {"kind": "wordpress-plugin"}, 0),
        ("a declared kind is exposed in changes mode too", default, "kind: wordpress-plugin\n", ["a.php"], {"POLICY_MODE": "changes"}, {"kind": "wordpress-plugin", "code": "true"}, 0),
        ("a kind that does not exist fails", default, "kind: cobol-mainframe\n", ["docs/a.md"], {}, {}, 1),
        ("a kind that is not a name fails", default, "kind: \"../etc\"\n", ["docs/a.md"], {}, {}, 1),
        ("kind: the workflow's kind when the repository declares none", default, "", [], {"POLICY_MODE": "kind", "KIND_DEFAULT": "wordpress-plugin"}, {"kind": "wordpress-plugin", "rules": "kinds/wordpress-plugin/rules.yml", "profile": "kinds/wordpress-plugin/review-profile.md"}, 0),
        ("kind: the declared one, the same as the workflow's", default, "kind: wordpress-plugin\n", [], {"POLICY_MODE": "kind", "KIND_DEFAULT": "wordpress-plugin"}, {"kind": "wordpress-plugin"}, 0),
        ("kind: a declared kind the workflow does not run fails", default, "kind: wordpress-plugin\n", [], {"POLICY_MODE": "kind", "KIND_DEFAULT": "node-app"}, {}, 1),
        ("kind: no kind anywhere fails", default, "", [], {"POLICY_MODE": "kind"}, {}, 1),
        ("paid-roadmap: none by default", default, "", ["docs/a.md"], {}, {"paid_repository": "", "paid_path": ""}, 0),
        ("paid-roadmap: the add-on's roadmap", default, "paid-roadmap:\n  repository: DiluxOne/x-pro-wordpress\n", ["docs/a.md"], {}, {"paid_repository": "DiluxOne/x-pro-wordpress", "paid_owner": "DiluxOne", "paid_name": "x-pro-wordpress", "paid_path": "docs/roadmap.md"}, 0),
        ("paid-roadmap: a path out of the repository fails", default, "paid-roadmap:\n  repository: DiluxOne/x-pro-wordpress\n  path: ../../etc/passwd\n", ["docs/a.md"], {}, {}, 1),
        ("paid-roadmap: a repository that is not one fails", default, "paid-roadmap:\n  repository: \"x; rm -rf /\"\n", ["docs/a.md"], {}, {}, 1),
        ("issue-gate: required with the accepted label by default", default, "", [], {"POLICY_MODE": "issue-gate"}, {"required": "true", "label": "accepted"}, 0),
        ("issue-gate: a repository cannot turn it off", default, "issue-gate:\n  required: false\n", [], {"POLICY_MODE": "issue-gate"}, {"required": "true"}, 0),
        ("issue-gate: nor change the label", default, "issue-gate:\n  label: yes-please\n", [], {"POLICY_MODE": "issue-gate"}, {"label": "accepted"}, 0),
        ("issue-gate: off where the organisation lets it be", gate_optional, "issue-gate:\n  required: false\n", [], {"POLICY_MODE": "issue-gate"}, {"required": "false"}, 0),
        ("issue-gate: a label that is not one fails", gate_bad, "", [], {"POLICY_MODE": "issue-gate"}, {}, 1),
        ("size: an untrusted author gets the organisation's limit", default, "", [], {"POLICY_MODE": "issue-gate", "PR_AUTHOR": "someone"}, {"trusted": "false", "max_lines": "600"}, 0),
        ("size: a trusted author has none", default, "", [], {"POLICY_MODE": "issue-gate", "PR_AUTHOR": "soydiloreto"}, {"trusted": "true", "max_lines": ""}, 0),
        ("size: a repository lowers it", default, "max-changed-lines-untrusted: 200\n", [], {"POLICY_MODE": "issue-gate", "PR_AUTHOR": "someone"}, {"max_lines": "200"}, 0),
        ("size: but cannot raise it", default, "max-changed-lines-untrusted: 5000\n", [], {"POLICY_MODE": "issue-gate", "PR_AUTHOR": "someone"}, {"max_lines": "600"}, 0),
        ("size: nor remove it", default, "max-changed-lines-untrusted: 0\n", [], {"POLICY_MODE": "issue-gate", "PR_AUTHOR": "someone"}, {"max_lines": "600"}, 0),
    ]
    failed = 0
    for name, defaults_path, repo_text, files, env, want, want_code in cases:
        code, outputs = run_case(defaults_path, repo_text, files, **env)
        wrong = {k: (v, outputs.get(k)) for k, v in want.items() if outputs.get(k) != v}
        if code != want_code or wrong:
            failed += 1
            print(f"FAIL {name}: exit {code} (want {want_code}), {wrong or outputs}")
        else:
            print(f"ok   {name}")
    for path in (org_off, gate_optional, gate_bad):
        os.unlink(path)
    failed += settings_tests()
    if not failed:
        print("all tests passed")
    return 1 if failed else 0


def settings_tests():
    """The pack's settings and a repository's additions; the profile names."""
    failed = 0

    def check(name, ok, detail=""):
        nonlocal failed
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
        failed += 0 if ok else 1

    code, out = run_case(os.path.join(CENTRAL, "policy", "review-policy.default.yml"), "kind: wordpress-plugin\nkind-settings:\n  plugin-check:\n    ignore-codes: [one_more_code]\n    strict: false\n", [], POLICY_MODE="kind")
    settings = json.loads(out.get("settings", "{}"))
    pc = settings.get("plugin-check", {})
    check("kind: the pack's Plugin Check settings", code == 0 and pc.get("strict") is True and "stable_tag_mismatch" in pc.get("ignore-codes", []), out)
    check("kind: a repository adds an ignore code", "one_more_code" in pc.get("ignore-codes", []), pc)
    check("kind: a repository cannot turn strict off", pc.get("strict") is True, pc)
    merged = merge_settings({"a": [1], "b": {"c": [2], "d": "x"}}, {"a": [1, 3], "b": {"c": [4], "d": "y"}, "e": [5], "f": "z"})
    check("settings: lists append without repeats, maps merge, single values stay", merged == {"a": [1, 3], "b": {"c": [2, 4], "d": "x"}, "e": [5]}, merged)
    for name, want in (("general", "review-profiles/general.md"), ("wordpress-plugin", "kinds/wordpress-plugin/review-profile.md"), ("plugin-wp", "kinds/wordpress-plugin/review-profile.md"), ("nothing-here", None), ("../AGENTS", None)):
        got = profile_path(name)
        check(f"profile: {name} is {want}", got == want, got)
        if got:
            check(f"profile: {got} exists", os.path.isfile(os.path.join(CENTRAL, got)))
    # This repository's own policy: every tracked file is high risk but its
    # pages (README.md, docs/ but docs/agents.md, profile/), which alone can be low. A new file
    # that no pattern names fails here instead of slipping into low risk.
    own = load_yaml(os.path.join(CENTRAL, ".github", "review-policy.yml"))
    default_policy = load_yaml(os.path.join(CENTRAL, "policy", "review-policy.default.yml"))
    tracked = subprocess.run(["git", "-C", CENTRAL, "ls-files"], capture_output=True, text=True).stdout.split()
    if tracked:
        high = default_policy.get("high-risk", []) + own.get("high-risk", [])
        low = default_policy.get("low-risk-eligible", []) + own.get("low-risk-eligible", [])
        page = lambda f: f == "README.md" or (f.startswith(("docs/", "profile/")) and f != "docs/agents.md")
        loose = [f for f in tracked if not page(f) and not matches(f, high)]
        check("this repository: every file but its pages is high risk", not loose, loose[:10])
        check("this repository: docs/agents.md, what agents follow, is high risk", matches("docs/agents.md", high))
        pages = [f for f in tracked if page(f) and f.endswith(".md")]
        check("this repository: its Markdown pages can be low risk", all(not matches(f, high) and matches(f, low) for f in pages), pages)
    for kind in sorted(os.listdir(os.path.join(CENTRAL, "kinds"))):
        if not os.path.isfile(pack_path(kind)):
            continue
        pack = load_yaml(pack_path(kind))
        check(f"pack {kind}: names its battery, adapters and rules", isinstance(pack.get("workflows"), list) and pack.get("workflows") and isinstance(pack.get("adapters"), list) and os.path.isfile(os.path.join(CENTRAL, "kinds", kind, "rules.yml")), pack)
        for wf in pack.get("workflows") or []:
            check(f"pack {kind}: its workflow {wf} exists", os.path.isfile(os.path.join(CENTRAL, ".github", "workflows", wf)))
        check(f"pack {kind}: its review profile exists", os.path.isfile(os.path.join(CENTRAL, "kinds", kind, "review-profile.md")))
    return failed


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        sys.exit(self_test())
    if len(sys.argv) == 3 and sys.argv[1] == "--profile":
        path = profile_path(sys.argv[2])
        if path is None:
            print(f"No review profile is called '{sys.argv[2]}': general, a kind in kinds/, or an alias a pack declares.", file=sys.stderr)
            sys.exit(1)
        print(path)
        sys.exit(0)
    sys.exit(main())
