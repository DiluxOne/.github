#!/usr/bin/env python3
"""The documentation check (#957), part of the security gate.

`security-gate.py run` loads it, as it loads policy.py, and merges its
findings into the same result (`tool: docs`, status `new`), so they are
ordered, cut, suppressed, blocked and counted as the gate's own. It needs no
tool and no model: it reads git between the merge base and HEAD.

  docs/stale-name  a line of the docs (policy/security-gate.yml `docs.docs`)
                   or of a workflow's header comment (`docs.headers`) that
                   still names, as a whole token, an identifier the change
                   removed or renamed: a workflow_call input, output or
                   secret, a job or step id, a script's flag or command, an
                   environment variable, a label, a file path. Removed means
                   the head's whole tree no longer has it in that class.

  docs/map         a changed path that an entry of the docs map ties to
                   docs (`docs-map: [{paths: [glob], docs: [path or glob]}]`,
                   the kind's pack's, then the repository's own in
                   .github/review-policy.yml, both read at the merge base)
                   while none of those docs changed: one finding per entry.
                   None when the description's What changes has a line
                   `Docs: none, <why>` with a why, which goes into the
                   result (`exempt`); it never exempts a stale name

  docs-check.py --test    self-test
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CENTRAL = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import policy as pol  # noqa: E402  the globs (scripts/policy.py)

DEFAULTS = {"severity": "high", "min-length": 4,
            "docs": ["README*", "docs/**", "CONTRIBUTING.md", "AGENTS.md", "kinds/**"],
            "headers": [".github/workflows/*.yml", ".github/workflows/*.yaml", "workflow-templates/*.yml"]}
WORKFLOWS = [".github/workflows/*.yml", ".github/workflows/*.yaml", "workflow-templates/*.yml", "workflow-templates/*.yaml"]
LABELS = ["labels.yml", ".github/labels.yml"]
# The classes, in the order a name met in two of them is told by.
CLASSES = ("input", "output", "secret", "job id", "step id", "flag", "command", "environment variable", "label", "file")


def settings(conf):
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (conf or {}).items() if v not in (None, "")})
    return out


# --- reading -----------------------------------------------------------------

def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=check).stdout


def show(repo, rev, path):
    """PATH at REV as text, None when it is no file there."""
    got = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"], capture_output=True)
    return got.stdout.decode("utf-8", "replace") if got.returncode == 0 else None


def parse_yaml(text):
    """YAML text as data (safe_load; yq where PyYAML is missing), None when
    it is not YAML."""
    try:
        import yaml
    except ImportError:
        yaml = None
    try:
        if yaml is not None:
            return yaml.safe_load(text)
        if shutil.which("yq"):
            out = subprocess.run(["yq", "-o=json", ".", "-"], input=text, capture_output=True, text=True, check=True).stdout
            return json.loads(out or "null")
    except Exception:  # noqa: BLE001  a file that is not YAML defines nothing
        return None
    return None


def header_lines(text):
    """The line numbers (1-based) of a workflow's header comment: the
    leading `#` block, past its `name:` and blank lines. Pure."""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("#"):
            out.append(i)
        elif s and not re.match(r"name\s*:", s):
            break
    return out


def without_header(text):
    """TEXT with its header comment blanked, so what a header says is never
    read as a definition. Pure."""
    drop = set(header_lines(text))
    return "\n".join("" if i in drop else line for i, line in enumerate(text.splitlines(), 1))


# --- the identifiers ---------------------------------------------------------

FLAG = re.compile(r"(?<![\w-])(--[A-Za-z][A-Za-z0-9-]*[A-Za-z0-9])(?![\w-])")
COMMAND = [re.compile(r"""argv\[\s*:\s*1\s*\]\s*==\s*\[\s*["']([\w-]+)["']\s*\]"""),
           re.compile(r"""add_parser\(\s*["']([\w-]+)["']""")]
CASE_ARM = re.compile(r"^\s*\(?\s*([A-Za-z][\w-]*(?:\s*\|\s*[A-Za-z][\w-]*)*)\s*\)")
ENV = [re.compile(r"""os\.environ\[\s*["']([A-Za-z_]\w*)["']\s*\]"""),
       re.compile(r"""(?:environ\.get|getenv)\(\s*["']([A-Za-z_]\w*)["']"""),
       re.compile(r"\$\{([A-Za-z_]\w*):?-")]


def in_case(text):
    """Whether a shell text has a `case` statement. Pure."""
    return bool(re.search(r"^\s*case\s.+\sin\s*$", text, re.M))


def workflow_ids(data):
    """{class: set} of a parsed workflow. Pure."""
    out = {c: set() for c in CLASSES}
    if not isinstance(data, dict):
        return out
    on = data.get("on", data.get(True))
    call = on.get("workflow_call") if isinstance(on, dict) else None
    if isinstance(call, dict):
        for key, cls in (("inputs", "input"), ("outputs", "output"), ("secrets", "secret")):
            if isinstance(call.get(key), dict):
                out[cls].update(str(k) for k in call[key])
    envs = [data.get("env")]
    jobs = data.get("jobs")
    if isinstance(jobs, dict):
        for jid, job in jobs.items():
            out["job id"].add(str(jid))
            if not isinstance(job, dict):
                continue
            envs.append(job.get("env"))
            for st in job.get("steps") or []:
                if isinstance(st, dict):
                    if st.get("id"):
                        out["step id"].add(str(st["id"]))
                    envs.append(st.get("env"))
    for env in envs:
        if isinstance(env, dict):
            out["environment variable"].update(str(k) for k in env)
    return out


def label_names(data):
    """Every `name:` of the label lists of a labels.yml. Pure."""
    out = set()
    lists = [data] if isinstance(data, list) else [v for v in data.values() if isinstance(v, list)] if isinstance(data, dict) else []
    for items in lists:
        out.update(str(i["name"]) for i in items if isinstance(i, dict) and i.get("name"))
    return out


def identifiers(path, text):
    """{class: set} of what PATH (its TEXT) defines or uses: a workflow's
    YAML, a labels.yml's names, any other file's flags, commands and
    environment variables. A workflow's header comment counts for none.
    Pure."""
    out = {c: set() for c in CLASSES}
    if text is None:
        return out
    if pol.matches(path, WORKFLOWS):
        text = without_header(text)
        for c, ids in workflow_ids(parse_yaml(text)).items():
            out[c] |= ids
    if path in LABELS:
        out["label"] |= label_names(parse_yaml(text))
        return out
    out["flag"].update(FLAG.findall(text))
    for rx in COMMAND:
        out["command"].update(n for n in rx.findall(text) if not n.startswith("-"))
    if in_case(text):
        for line in text.splitlines():
            m = CASE_ARM.match(line)
            if m:
                out["command"].update(a.strip() for a in m.group(1).split("|"))
    for rx in ENV:
        out["environment variable"].update(rx.findall(text))
    return out


def bare(name):
    return name.lstrip("-")


def token_re(name):
    """A whole-token match of NAME: no letter, digit, `_` or `-` before or
    after it, and no `.x` after it (`a.py` is not `a`). Pure."""
    return re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])(?!\.\w)")


# --- the change --------------------------------------------------------------

def name_status(repo, base):
    """[(status, old, new)] of `git diff --name-status -M` from BASE."""
    out = []
    parts = git(repo, "diff", "--name-status", "-M", "-z", base, "HEAD").split("\0")
    i = 0
    while i < len(parts) and parts[i]:
        st = parts[i]
        if st[:1] in ("R", "C"):
            out.append((st[:1], parts[i + 1], parts[i + 2]))
            i += 3
        else:
            out.append((st[:1], parts[i + 1], parts[i + 1]))
            i += 2
    return out


def tree(repo, rev="HEAD"):
    return [p for p in git(repo, "ls-tree", "-r", "-z", "--name-only", rev).split("\0") if p]


def removed(repo, base, changes, conf, errors):
    """{name: (class, new name or "")}: what the change removed or renamed,
    of the classes CLASSES, that the head's whole tree no longer has."""
    docs = list(conf["docs"])
    before = {c: set() for c in CLASSES}
    after = {c: set() for c in CLASSES}
    for st, old, new in changes:
        if pol.matches(old, docs) and pol.matches(new, docs):
            continue
        if st != "A":
            for c, ids in identifiers(old, show(repo, base, old)).items():
                before[c] |= ids
        if st != "D":
            text = show(repo, "HEAD", new)
            if text is None and not git(repo, "ls-tree", "HEAD", "--", new, check=False).startswith("160000 "):
                errors.append(f"docs check: {clean(new, 120)} could not be read at HEAD, so nothing read its names")
            for c, ids in identifiers(new, text).items():
                after[c] |= ids
    minimum = int(conf.get("min-length") or 4)
    gone = {}
    for c in CLASSES:
        for name in sorted(before[c] - after[c]):
            if len(bare(name)) >= minimum and name not in gone:
                gone[name] = (c, "")
    if gone:
        # Still in the head's tree, in the same class: not removed.
        files = head_files_naming(repo, list(gone), docs, errors)
        still = {c: set() for c in CLASSES}
        for path in files:
            for c, ids in identifiers(path, show(repo, "HEAD", path)).items():
                still[c] |= ids
        gone = {n: v for n, v in gone.items() if n not in still[v[0]]}
    head = set(tree(repo))
    for st, old, new in changes:
        if st in ("D", "R") and old not in head and len(bare(old)) >= minimum:
            gone[old] = ("file", new if st == "R" else "")
    return gone


def grep(repo, args, names, errors):
    """`git grep ARGS` at HEAD for any of NAMES (fixed strings): its output,
    "" for no match; a grep that failed is an error, never nothing found."""
    argv = ["git", "-C", repo, "grep", "-I", "-F", "-z", *args]
    for n in names:
        argv += ["-e", n]
    got = subprocess.run(argv + ["HEAD", "--"], capture_output=True, text=True)
    if got.returncode > 1:
        errors.append(f"docs check: git grep failed ({clean(got.stderr, 200)})")
    return got.stdout if got.returncode == 0 else ""


def head_files_naming(repo, names, docs, errors):
    """The files at HEAD, docs left out, whose text has one of NAMES."""
    if not names:
        return []
    out = []
    for item in grep(repo, ["-l"], names, errors).split("\0"):
        path = item[len("HEAD:"):] if item.startswith("HEAD:") else item
        if path and not pol.matches(path, docs):
            out.append(path)
    return out


# --- the findings ------------------------------------------------------------

def fingerprint(text):
    return hashlib.sha1(" ".join(str(text).split()).encode()).hexdigest()[:12]


def clean(text, limit=200):
    text = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(text or "")).replace("`", "'").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def stale_findings(gone, lines, severity):
    """The findings of the lines ({(path, n): text}) that name what is GONE
    ({name: (class, new)}). Pure."""
    out = []
    rxs = {n: token_re(n) for n in gone}
    for (path, n), text in sorted(lines.items()):
        for name in sorted(gone):
            if not rxs[name].search(text):
                continue
            cls, new = gone[name]
            fix = (f"Name {new} instead, or remove the mention." if new else
                   f"Update or remove the mention: the change removed or renamed this {cls}.")
            out.append({"tool": "docs", "rule": "docs/stale-name", "file": path, "line": n, "severity": severity, "status": "new",
                        "fingerprint": fingerprint(name + " " + text), "identifier": name, "class": cls,
                        "message": clean(f"Still names the {cls} {name}, which the change removed or renamed."), "fix": clean(fix)})
    return out


def searched_lines(repo, names, conf, errors):
    """{(path, n): text} of the docs' lines and the workflow headers' lines
    at HEAD that have one of NAMES."""
    if not names:
        return {}
    out, headers = {}, {}
    for rec in grep(repo, ["-n"], names, errors).split("\n"):
        parts = rec.split("\0")
        if len(parts) < 3:
            continue
        path = parts[0][len("HEAD:"):] if parts[0].startswith("HEAD:") else parts[0]
        n, text = int(parts[1]), "\0".join(parts[2:])
        if pol.matches(path, conf["docs"]):
            out[(path, n)] = text
        elif pol.matches(path, conf["headers"]):
            if path not in headers:
                headers[path] = set(header_lines(show(repo, "HEAD", path) or ""))
            if n in headers[path]:
                out[(path, n)] = text
    return out


# --- the map -----------------------------------------------------------------

def entries(data):
    """The well-formed entries of a `docs-map` value: [(paths, docs)]. Pure."""
    out = []
    for e in data if isinstance(data, list) else []:
        if isinstance(e, dict):
            paths = [str(p) for p in e.get("paths") or [] if p]
            docs = [str(d) for d in e.get("docs") or [] if d]
            if paths and docs:
                out.append((paths, docs))
    return out


def doc_map(repo, base):
    """The map: the kind's pack's entries, then the repository's own, the
    kind and the repository's file both read at BASE, so a change cannot
    drop its own entries; the pack is the organisation's checkout's."""
    own = parse_yaml(show(repo, base, ".github/review-policy.yml") or "")
    own = own if isinstance(own, dict) else {}
    kind = str(own.get("kind") or "")
    out = []
    pack_file = os.path.join(CENTRAL, "kinds", kind, "pack.yml")
    if kind and pol.KIND_RE.fullmatch(kind) and os.path.isfile(pack_file):
        pack = pol.load_yaml(pack_file)
        out += entries((pack if isinstance(pack, dict) else {}).get("docs-map"))
    return out + entries(own.get("docs-map"))


def map_findings(mapping, changed, severity):
    """One finding per entry of MAPPING a path of CHANGED matches while none
    of its docs changed. Pure."""
    out = []
    for paths, docs in mapping:
        hit = [p for p in changed if pol.matches(p, paths) and not pol.matches(p, docs)]
        if not hit or any(pol.matches(p, docs) for p in changed):
            continue
        listed = ", ".join(docs)
        out.append({"tool": "docs", "rule": "docs/map", "file": hit[0], "line": 0, "severity": severity, "status": "new",
                    "fingerprint": fingerprint("\n".join(sorted(docs)) + "\n\n" + "\n".join(sorted(hit))), "docs": docs,
                    "message": clean(f"Changed {', '.join(hit[:3])}{' and more' if len(hit) > 3 else ''}, which the docs map ties to "
                                     f"{listed}; none of those changed."),
                    "fix": clean(f"Update {listed}, or write `Docs: none, <why>` in the description's What changes.", 300)})
    return out


DOCS_NONE = re.compile(r"^\s*(?:- )?Docs: none,[ \t]*(\S.*?)\s*$")


def exemption(body):
    """The why of the description's `Docs: none, <why>` line, read in its
    What changes section only (from the `## ` heading that names it to the
    next `## `), HTML comments left out; "" for none. Pure."""
    text = re.sub(r"<!--.*?-->", "", str(body or ""), flags=re.S)
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = "What changes" in line
            continue
        m = DOCS_NONE.match(line) if inside else None
        if m:
            return clean(m.group(1), 300)
    return ""


def check(repo, base, conf=None, body=None):
    """The documentation check of the change from BASE (the merge base) to
    HEAD in REPO: {"findings": [...], "errors": [...], "exempt": ""}."""
    conf = settings(conf)
    errors = []
    changes = name_status(repo, base)
    gone = removed(repo, base, changes, conf, errors)
    findings = stale_findings(gone, searched_lines(repo, list(gone), conf, errors), str(conf["severity"]))
    why = exemption(body)
    if not why:
        changed = sorted({p for _, old, new in changes for p in (old, new)})
        findings += map_findings(doc_map(repo, base), changed, str(conf["severity"]))
    return {"findings": findings, "errors": errors, "exempt": why}


# --- self-test ---------------------------------------------------------------

def self_test():
    fails = []

    def ok(name, got, want):
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        if got != want:
            fails.append(name)

    flow = ("name: x\n\n# Header: --old and in-put.\n\non:\n  workflow_call:\n    inputs:\n      in-put: {type: string}\n"
            "    outputs:\n      result: {value: x}\n    secrets:\n      token: {}\njobs:\n  build:\n    env: {JOB_ENV: 1}\n"
            "    steps:\n      - id: step-one\n        run: x --new\n")
    got = identifiers(".github/workflows/x.yml", flow)
    ok("a workflow's inputs, outputs, secrets, jobs, steps and env", (got["input"], got["output"], got["secret"], got["job id"],
                                                                     got["step id"], got["environment variable"]),
       ({"in-put"}, {"result"}, {"token"}, {"build"}, {"step-one"}, {"JOB_ENV"}))
    ok("a workflow's header defines nothing", got["flag"], {"--new"})
    ok("the header: past name: and blank lines, up to the first key", header_lines(flow), [3])
    script = ('import os\nif argv[:1] == ["serve"]:\n    os.environ["A_VAR"]\nos.environ.get("B_VAR")\nos.getenv("C_VAR")\n'
              'p.add_parser("build")\nx = "--flag-one"\n')
    got = identifiers("s.py", script)
    ok("a script's commands, flags and environment", (got["command"], got["flag"], got["environment variable"]),
       ({"serve", "build"}, {"--flag-one"}, {"A_VAR", "B_VAR", "C_VAR"}))
    sh = 'case "$1" in\n  start|stop) x ;;\n  --help) y ;;\n  *) z ;;\nesac\necho "${HOME_DIR:-/}"\n'
    got = identifiers("s.sh", sh)
    ok("a shell case's arms and ${X:-}", (got["command"], got["environment variable"]), ({"start", "stop"}, {"HOME_DIR"}))
    ok("a labels.yml's names", identifiers("labels.yml", "labels:\n  - name: one\nretired:\n  - name: two\n")["label"], {"one", "two"})
    rx = token_re("--base")
    ok("a whole token only", [bool(rx.search(t)) for t in ("use --base x", "use --base-ref", "x--base", "(--base).", "--base.py")],
       [True, False, False, True, False])
    found = stale_findings({"--old": ("flag", ""), "a/b.py": ("file", "a/c.py")},
                           {("README.md", 2): "run --old", ("docs/x.md", 1): "see a/b.py.", ("docs/y.md", 1): "--older"}, "high")
    ok("a finding per line that names one, with its fix", [(f["file"], f["line"], f["class"]) for f in found],
       [("README.md", 2, "flag"), ("docs/x.md", 1, "file")])
    ok("a renamed file's fix names its new path", "a/c.py" in found[1]["fix"], True)
    m = entries([{"paths": ["src/**"], "docs": ["docs/api.md"]}, {"paths": []}, "x"])
    ok("a map's well-formed entries", m, [(["src/**"], ["docs/api.md"])])
    ok("a mapped path changed and its docs not: one finding naming them",
       [(f["rule"], f["file"], "docs/api.md" in f["message"]) for f in map_findings(m, ["src/a.py", "src/b.py"], "high")],
       [("docs/map", "src/a.py", True)])
    ok("its docs changed too, or no mapped path changed: none",
       (map_findings(m, ["src/a.py", "docs/api.md"], "high"), map_findings(m, ["lib/a.py"], "high")), ([], []))
    page = "## 📝 What changes\n\nx\n- Docs: none, it keeps the API\n\n## 💡 Why\n\nDocs: none, elsewhere\n"
    ok("Docs: none with its why, in What changes only, never in a comment or with no why",
       (exemption(page), exemption(page.replace("- Docs: none, it keeps the API", "Docs: none,")),
        exemption("## What changes\n<!--\nDocs: none, a comment\n-->\n"), exemption(None)),
       ("it keeps the API", "", "", ""))
    ok("the policy's settings over the defaults", settings({"min-length": 6})["min-length"], 6)
    print("all tests passed" if not fails else f"{len(fails)} failed")
    return 1 if fails else 0


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
