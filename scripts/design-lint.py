#!/usr/bin/env python3
"""The CSS a pull request changes, against its repository's design system
(#152), with stylelint and the system's pattern rules.

  design-lint.py plan  --repo NAME [--base REV] [--head REV]
        say whether there is anything to check: the system repos.yml gives
        the repository (`design-system:`) and the CSS changed from base to
        head; writes `run=true|false` to $GITHUB_OUTPUT when it is set.
  design-lint.py check --repo NAME [--base REV] [--head REV]
        run stylelint on that CSS, whole files, and annotate: a finding of
        an `error` rule on a line the change adds or changes is an error and
        fails; every other finding (a `warning` rule, or a line the change
        did not touch) is a warning, so no repository goes red for what it
        already had.
  design-lint.py --test   self-test (needs `npm ci --prefix scripts/stylelint`)

Run from the checkout of the repository under check; base and head default
to HEAD^1 and HEAD (a pull request's merge commit and its base). The system:

- a system of design-systems/ here: its dist/stylelint.json, which
  scripts/design-tokens.py writes from its rules.yml (never edited by hand);
- `local`: the repository's own docs/design-system/, read at base so a pull
  request cannot loosen what checks it: its rules.yml and tokens.json, added
  to those of the system its README.md extends (`Extends: <name>`);
- not listed: nothing to check.

The CSS is every *.css the change adds, modifies or renames, but minified
files and what is under vendor/ or node_modules/ (someone else's). Stylelint
runs with the configuration given and nothing of the repository's own: no
.stylelintrc, no .stylelintignore, no `stylelint-disable` comment, so a pull
request cannot exempt itself; an exception is a change to the rules.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CENTRAL = os.path.normpath(os.path.join(HERE, ".."))
STYLELINT = os.path.join(HERE, "stylelint", "node_modules", "stylelint", "bin", "stylelint.mjs")
RULE = "diluxone/design-system"

_spec = importlib.util.spec_from_file_location("design_tokens", os.path.join(HERE, "design-tokens.py"))
dt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dt)


def git(*args, check=True):
    out = subprocess.run(["git", "-c", "core.quotePath=false", *args], capture_output=True, text=True)
    if check and out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out.stderr.strip()}")
    return out


def system_of(repo, repos_yml):
    return ((dt.read_yaml(repos_yml) or {}).get("design-system") or {}).get(repo)


def is_ours(path):
    parts = path.split("/")
    return path.endswith(".css") and not path.endswith(".min.css") and not {"vendor", "node_modules"} & set(parts[:-1])


def changed_css(base, head):
    out = git("diff", "--name-only", "--diff-filter=AMR", "-M", base, head, "--", "*.css").stdout
    return [p for p in out.splitlines() if p and is_ours(p)]


def added_lines(diff):
    """{path: {line numbers}} that a `git diff -U0` adds or changes, on the
    new side."""
    out, path = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:]
            path = name[2:] if name.startswith("b/") else None
            if path is not None:
                out.setdefault(path, set())
        elif line.startswith("@@") and path is not None:
            m = re.match(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@", line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
                out[path].update(range(start, start + count))
    return out


def show(rev, path):
    out = git("show", f"{rev}:{path}", check=False)
    return out.stdout if out.returncode == 0 else None


def local_config(base, tmp):
    """(the configuration of a `local` system, as a file, or None; what is
    wrong with it, as lines). Read at base."""
    problems, rules, tokens = [], [], {}
    readme = show(base, "docs/design-system/README.md") or ""
    m = re.search(r"^\s*Extends:\s*`?([a-z0-9-]+)`?", readme, re.M | re.I)
    if m:
        central = os.path.join(dt.SYSTEMS, m.group(1), "dist", "stylelint.json")
        if os.path.isfile(central):
            with open(central, encoding="utf-8") as fh:
                rules += json.load(fh)["rules"][RULE][1]["rules"]
        else:
            problems.append(f"docs/design-system/README.md extends {m.group(1)}, which is no system of design-systems/")
    text = show(base, "docs/design-system/tokens.json")
    if text is not None:
        try:
            tree = json.loads(text)
            if m and os.path.isfile(os.path.join(dt.SYSTEMS, m.group(1), "tokens.json")):
                with open(os.path.join(dt.SYSTEMS, m.group(1), "tokens.json"), encoding="utf-8") as fh:
                    tokens = dt.flatten(json.load(fh))
            tokens.update(dt.flatten(tree))
            dt.validate(tokens)
        except (dt.Invalid, ValueError) as exc:
            problems.append(f"docs/design-system/tokens.json: {exc}; no token is suggested")
            tokens = {}
    text = show(base, "docs/design-system/rules.yml")
    if text is not None:
        path = os.path.join(tmp, "rules.yml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        own = dt.read_yaml(path)
        found = dt.check_rules(own, tokens or None)
        if found:
            problems += [f"docs/design-system/rules.yml: {p}; its rules are left out" for p in found]
        else:
            rules += dt.stylelint_rules(own, tokens)
    if not rules:
        return None, problems
    conf = os.path.join(tmp, "stylelint.json")
    with open(conf, "w", encoding="utf-8") as fh:
        json.dump({"plugins": ["./scripts/stylelint/design-system.mjs"],
                   "rules": {RULE: [True, {"system": "local", "rules": rules}]}}, fh)
    return conf, problems


def config_for(system, base, tmp):
    if system == "local":
        return local_config(base, tmp)
    conf = os.path.join(dt.SYSTEMS, system, "dist", "stylelint.json")
    if not os.path.isfile(conf):
        return None, [f"design-systems/{system}/dist/stylelint.json is not there: the design system has no pattern rules for CSS yet"]
    return conf, []


def escape(text, prop=False):
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if prop else text


def classify(results, added, root):
    """[(level, path, line, end line, column, text, the change's own)] from
    stylelint's JSON."""
    out = []
    for result in results:
        path = os.path.relpath(result["source"], root).replace(os.sep, "/")
        mine = added.get(path, set())
        for w in result.get("warnings") or []:
            line, end = w.get("line") or 1, w.get("endLine") or w.get("line") or 1
            text = re.sub(r"\s*\(" + re.escape(w.get("rule") or "") + r"\)$", "", w.get("text") or "")
            touched = any(n in mine for n in range(line, end + 1))
            if w.get("rule") == RULE:
                level = "error" if touched and w.get("severity") == "error" else "warning"
            else:
                level, text = "warning", f"{w.get('rule')}: {text} (stylelint could not read this; nothing of the design system was checked here)"
            out.append((level, path, line, end, w.get("column") or 1, text, touched))
    return out


def plan(repo, base, head, repos_yml):
    system = system_of(repo, repos_yml)
    if not system:
        return None, [], f"{repo} declares no design system in repos.yml (`design-system:`): nothing to check."
    files = changed_css(base, head)
    if not files:
        return system, [], f"{repo} follows {system}; the change touches no CSS of its own: nothing to check."
    return system, files, f"{repo} follows {system}; the CSS changed: {', '.join(files)}."


def stylelint(conf, files, root):
    with tempfile.TemporaryDirectory() as tmp:
        report, empty = os.path.join(tmp, "report.json"), os.path.join(tmp, "ignore")
        open(empty, "w").close()
        run = subprocess.run(["node", STYLELINT, "--config", conf, "--config-basedir", CENTRAL, "--ignore-disables",
                              "--ignore-path", empty, "--allow-empty-input", "--formatter", "json", "--output-file", report,
                              "--", *files], cwd=root, capture_output=True, text=True)
        if run.returncode not in (0, 2) or not os.path.isfile(report):
            raise RuntimeError(f"stylelint exited {run.returncode}: {(run.stderr or run.stdout).strip()[:2000]}")
        with open(report, encoding="utf-8") as fh:
            results = json.load(fh)
    broken = [w.get("text") for r in results for w in r.get("invalidOptionWarnings") or []]
    if broken:
        raise RuntimeError("the configuration is not valid: " + "; ".join(broken))
    return results


def check(repo, base, head, repos_yml, out=print):
    system, files, why = plan(repo, base, head, repos_yml)
    out(why)
    if not files:
        return 0
    root = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        conf, problems = config_for(system, base, tmp)
        for p in problems:
            out(f"::warning::{escape(p)}")
        if not conf:
            out("No pattern rules to run: nothing to check.")
            return 0
        found = classify(stylelint(conf, files, root), added_lines(git("diff", "-U0", "-M", base, head, "--", *files).stdout), root)
    # GitHub shows ten annotations of a level per step: the change's own first.
    found.sort(key=lambda f: (f[0] != "error", not f[6], f[1], f[2]))
    for level, path, line, end, col, text, _ in found:
        out(f"::{level} file={escape(path, True)},line={line},endLine={end},col={col},title={escape('Design system (' + system + ')', True)}::{escape(text)}")
    errors = sum(1 for f in found if f[0] == "error")
    own = [f for f in found if f[6]]
    out(f"{errors} error(s) on lines this change adds or changes; {len(own) - errors} warning(s) there, "
        f"and {len(found) - len(own)} on the lines it did not touch (what the files already had).")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and found:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### Design system ({system})\n\n")
            if own:
                fh.write("On the lines this change adds or changes:\n\n| | Where | What |\n| --- | --- | --- |\n")
                for level, path, line, _, _, text, _ in own:
                    fh.write(f"| {'❌' if level == 'error' else '⚠️'} | `{path}:{line}` | {text.replace('|', '&#124;')} |\n")
            fh.write(f"\n{len(found) - len(own)} warning(s) on the lines it did not touch, in the step's log: not this change's to fix.\n")
    return 1 if errors else 0


def args(argv):
    opts = {"--repo": None, "--base": "HEAD^1", "--head": "HEAD", "--repos-yml": os.path.join(CENTRAL, "repos.yml")}
    rest = list(argv)
    while rest:
        key = rest.pop(0)
        if key not in opts or not rest:
            return None
        opts[key] = rest.pop(0)
    return opts if opts["--repo"] else None


def self_test():
    failed = 0

    def ok(name, cond, detail=""):
        nonlocal failed
        print(("ok   " if cond else "FAIL ") + name + ("" if cond else f": {detail}"))
        failed += 0 if cond else 1

    diff = ("diff --git a/a.css b/a.css\n--- a/a.css\n+++ b/a.css\n@@ -2 +2,2 @@\n-x\n+y\n+z\n@@ -9,0 +11 @@\n+w\n"
            "diff --git a/gone.css b/gone.css\n--- a/gone.css\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n@@ -5,2 +6,0 @@\n")
    got = added_lines(diff)
    ok("added lines: a hunk's new side, one line when no count, none for a deletion", got == {"a.css": {2, 3, 11}}, got)
    ok("which CSS is ours", [is_ours(p) for p in ("assets/a.css", "a.min.css", "assets/vendor/x.css", "node_modules/y/z.css", "a.scss")]
       == [True, False, False, False, False], "")
    results = [{"source": "/r/a.css", "warnings": [
        {"line": 2, "endLine": 2, "column": 3, "rule": RULE, "severity": "error", "text": "colour-from-tokens: x (diluxone/design-system)"},
        {"line": 1, "endLine": 1, "column": 3, "rule": RULE, "severity": "error", "text": "colour-from-tokens: y"},
        {"line": 3, "endLine": 3, "column": 3, "rule": RULE, "severity": "warning", "text": "space-from-tokens: z"},
        {"line": 10, "endLine": 12, "column": 1, "rule": RULE, "severity": "error", "text": "no-important: w"},
        {"line": 4, "column": 1, "rule": "CssSyntaxError", "severity": "error", "text": "Unclosed block (CssSyntaxError)"}]}]
    got = classify(results, {"a.css": {2, 3, 11}}, "/r")
    ok("classify: an error rule on an added line fails, with the rule's name trimmed", got[0] == ("error", "a.css", 2, 2, 3, "colour-from-tokens: x", True), got[0])
    ok("classify: on a line the change did not touch, a warning (C2)", got[1][0] == "warning", got[1])
    ok("classify: a warning rule on an added line stays a warning", got[2][0] == "warning", got[2])
    ok("classify: a finding over several lines is the change's when one of them is", got[3][0] == "error", got[3])
    ok("classify: a file stylelint cannot read warns, never fails", got[4][0] == "warning" and "could not read" in got[4][5], got[4])
    ok("escape: annotations keep their newlines and their properties their commas", escape("a\nb%") == "a%0Ab%25" and escape("a,b:c", True) == "a%2Cb%3Ac", "")
    ok("args: --repo is required, the rest has defaults", args([]) is None and args(["--repo", "r"])["--base"] == "HEAD^1" and args(["--bogus", "x"]) is None, "")

    if not os.path.isfile(STYLELINT):
        print("FAIL stylelint is not installed: npm ci --prefix scripts/stylelint --ignore-scripts")
        return 1
    # Every fixture of every system, through stylelint and the generated
    # configuration: what rules.yml says it catches, stylelint catches (C4).
    for name in dt.systems():
        conf = os.path.join(dt.SYSTEMS, name, "dist", "stylelint.json")
        rules = dt.read_yaml(os.path.join(dt.SYSTEMS, name, "rules.yml"))
        with tempfile.TemporaryDirectory() as tmp:
            cases = []
            for rule in rules.get("rules") or []:
                if rule.get("type") != "pattern" or rule.get("applies-to") not in ("css", "any"):
                    continue
                for kind in ("fail", "pass"):
                    for i, code in enumerate(rule["fixtures"][kind]):
                        path = os.path.join(tmp, f"{rule['id']}.{kind}.{i}.css")
                        with open(path, "w", encoding="utf-8") as fh:
                            fh.write(code + "\n")
                        cases.append((rule["id"], kind, code, path))
            results = {r["source"]: r for r in stylelint(conf, [c[3] for c in cases], tmp)}
            wrong = []
            for rid, kind, code, path in cases:
                hits = [w for w in results[path]["warnings"] if w["rule"] == RULE and w["text"].startswith(rid + ":")]
                if bool(hits) != (kind == "fail"):
                    wrong.append(f"{rid} {kind}: {code!r}")
            ok(f"design-systems/{name}: stylelint agrees with every CSS fixture of rules.yml ({len(cases)})", not wrong, wrong)

    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "repo")
        os.makedirs(os.path.join(repo, "assets"))
        repos_yml = os.path.join(tmp, "repos.yml")
        with open(repos_yml, "w", encoding="utf-8") as fh:
            fh.write("design-system:\n  plugin: wordpress-admin\n  app: local\n")

        def sh(*cmd):
            subprocess.run(cmd, cwd=repo, check=True, capture_output=True)

        def write(path, text):
            os.makedirs(os.path.dirname(os.path.join(repo, path)), exist_ok=True)
            with open(os.path.join(repo, path), "w", encoding="utf-8") as fh:
                fh.write(text)

        sh("git", "init", "-q", "-b", "main")
        sh("git", "config", "user.email", "t@t")
        sh("git", "config", "user.name", "t")
        sh("git", "config", "commit.gpgsign", "false")
        write("assets/admin.css", ".diluxone-x-admin .card { color: #646970; }\n")
        write("assets/vendor/lib.css", ".a { color: #000; }\n")
        write("docs/design-system/README.md", "# App\n\nExtends: wordpress-admin\n")
        sh("git", "add", "-A")
        sh("git", "commit", "-q", "-m", "base")
        write("assets/admin.css", ".diluxone-x-admin .card { color: #646970; }\n"
                                  "/* stylelint-disable */\n.diluxone-x-admin .tab { color: #2271b1; }\n"
                                  ".diluxone-x-admin .row { padding: 20px; }\n")
        write("assets/vendor/lib.css", ".a { color: #111; }\n")
        write("assets/admin.min.css", ".a{color:#222}\n")
        sh("git", "add", "-A")
        sh("git", "commit", "-q", "-m", "change")
        cwd = os.getcwd()
        os.chdir(repo)
        try:
            lines = []
            code = check("plugin", "HEAD^1", "HEAD", repos_yml, out=lines.append)
            text = "\n".join(lines)
            ok("C1: a colour the change adds fails on its line and names the token", code == 1 and re.search(
                r"^::error file=assets/admin.css,line=3,.*`#2271b1` is `var\(--dx-color-accent\)`", text, re.M), text)
            ok("C2: what the lines it did not touch already had is a warning", re.search(r"^::warning file=assets/admin.css,line=1,.*`#646970` is `var\(--dx-color-text-muted\)`", text, re.M), text)
            ok("a rule that only warns stays a warning on an added line", re.search(r"^::warning file=assets/admin.css,line=4,.*space-from-tokens", text, re.M), text)
            ok("a stylelint-disable comment exempts nothing", "line=3" in text and "::error" in text, text)
            ok("minified and vendor CSS are not checked", "vendor" not in text.split("CSS changed:")[1].split("\n")[0] and "admin.min.css" not in text, text)
            lines = []
            code = check("other", "HEAD^1", "HEAD", repos_yml, out=lines.append)
            ok("C3: a repository with no design-system in repos.yml: nothing runs", code == 0 and lines == [
                "other declares no design system in repos.yml (`design-system:`): nothing to check."], lines)
            lines = []
            code = check("app", "HEAD^1", "HEAD", repos_yml, out=lines.append)
            ok("local: the system its README extends, read at base", code == 1 and any("`var(--dx-color-accent)`" in line for line in lines), lines)
            write("docs/design-system/README.md", "# App\n\nExtends: wordpress-admin\n")
            write("docs/design-system/rules.yml", "rules:\n  - id: no-red\n    type: pattern\n    severity: error\n    applies-to: css\n"
                                                  "    message: m\n    source: s\n    pattern: 'color:\\s*red'\n"
                                                  "    fixtures:\n      fail: ['.a { color: red; }']\n      pass: ['.a { color: blue; }']\n")
            write("assets/admin.css", ".a { color: red; }\n")
            sh("git", "add", "-A")
            sh("git", "commit", "-q", "-m", "local rules, and red")
            lines = []
            check("app", "HEAD^1", "HEAD", repos_yml, out=lines.append)
            ok("local: rules a pull request adds do not check that pull request", not any("no-red" in line for line in lines), lines)
            write("assets/admin.css", ".b { color: red; }\n")
            sh("git", "add", "-A")
            sh("git", "commit", "-q", "-m", "red again")
            lines = []
            code = check("app", "HEAD^1", "HEAD", repos_yml, out=lines.append)
            ok("local: its own rules add to the extended system's", code == 1 and any(line.startswith("::error") and "no-red" in line for line in lines), lines)
            write("docs/design-system/README.md", "# App\n")
            sh("git", "rm", "-q", "docs/design-system/rules.yml")
            sh("git", "add", "-A")
            sh("git", "commit", "-q", "-m", "no rules")
            write("assets/admin.css", ".a { color: #2271b1; }\n")
            sh("git", "add", "-A")
            sh("git", "commit", "-q", "-m", "blue")
            lines = []
            code = check("app", "HEAD^1", "HEAD", repos_yml, out=lines.append)
            ok("local: no rules and nothing extended, nothing to run", code == 0 and lines[-1] == "No pattern rules to run: nothing to check.", lines)
            lines = []
            code = check("plugin", "HEAD~1", "HEAD~1", repos_yml, out=lines.append)
            ok("no CSS changed: nothing runs", code == 0 and "touches no CSS" in lines[0], lines)
        finally:
            os.chdir(cwd)
    if not failed:
        print("all tests passed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv[:1] in (["plan"], ["check"]) and (opts := args(argv[1:])):
        if argv[0] == "plan":
            _, files, why = plan(opts["--repo"], opts["--base"], opts["--head"], opts["--repos-yml"])
            print(why)
            if os.environ.get("GITHUB_OUTPUT"):
                with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
                    fh.write(f"run={'true' if files else 'false'}\n")
            return 0
        try:
            return check(opts["--repo"], opts["--base"], opts["--head"], opts["--repos-yml"])
        except RuntimeError as exc:
            print(f"::error::{escape(str(exc))}")
            return 1
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
