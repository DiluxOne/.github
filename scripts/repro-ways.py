#!/usr/bin/env python3
"""The ways a repository reproduces a bug (#352): which test, where, with
what, for the layer the bug lives in.

A bug lives in a layer: `logic`, `browser`, `cli`, `api` or `workflow` (a
CI workflow's wiring: its triggers, its steps' order and conditions, #376).
The triage says which (the `layer:<name>` label), knowing nothing of the
repository's tools. The repository says how it reproduces each layer: its
kind's pack gives the default (kinds/<kind>/pack.yml, `repro:`), and its own
.github/review-policy.yml may add a way, change one, or switch one off
(`repro: {ways: {name: false}}`). Nothing about a tool is written here or in
the workflows: a repository whose kind and policy declare no way for a layer
has none, whatever its stack, and `resolve` says why and how to declare one
(`why`) instead of guessing a stack (#376). The organisation's repos.yml
may hold a repository's `repro:` too (#377: `repro:`, under its name), read
between its pack's and its own policy's, so the repository still wins; the
installer proposes one there, from the repository's stack, for a
repository that declares none (policy/repro-stacks.yml, the stacks every
kind shares, recognised by scripts/detect.py).

A way is one entry of `repro.ways`:
  layer     the layer it reproduces, or a list of them; for a layer two
            ways cover, the repository's own comes first, then the pack's
            in the order written
  noun      what the comments call its test ("unit test", "browser test")
  test      the file the agent writes, `{n}` the issue's number
  needs     paths that must exist for the way to work (a trailing / is a folder)
  sandbox   `php-unit`: scripts/repro-sandbox.sh runs it (no network, no
            environment, read-only). Otherwise the way is a command:
  setup     commands, before the test is in the tree, with the network
  theme     a command that installs the theme a report names ({theme})
  run       the command that runs the test ({test}); scripts/repro-run.sh
            runs it with no environment and no network but the machine's own
  junit     the JUnit report `run` writes, which gives the verdict
  case      what that report names the test by (`{n}`), when no test case
            carries the test's file name (Go's TestIssue{n}, a .NET class
            Issue{n}Tests); the test's file name by default
  assertion a regular expression a failure's text matches when it is an
            assertion's and not the test breaking, for a framework whose
            words the built-in one does not know (Go's `file_test.go:9:`,
            .NET's `Assert.`); an exception's failure is never one
  teardown  a command after the verdict, best effort
  minutes   the most setup and run may take together
  context   files the writer reads whole; list: globs it sees by name;
  example   a glob whose first match it reads as the house style
  guide     what the writer must do and avoid, for this way
  shots     for a browser way, the command that runs a pull request's
            affected specs ({tests}) through the screenshot configuration
            (scripts/screenshots.py, #564)
`repro.affected` maps paths to the tests a pull request that touches them
runs (`{paths: [globs], tests: [paths]}`), instead of the whole suite.
`repro.smoke` (#479) lists the few specs a pull request runs beside the
mapped ones where the merge queue runs every suite (scripts/e2e-run.sh,
LEVEL=pr): the pack's, then the repository's.

  repro-ways.py resolve   the way for LAYER (default logic) in the repository
                          at DIR (default .): key=value lines (also to
                          $GITHUB_OUTPUT), way= empty when it declares none,
                          ready=yes|no for its `needs`, why= what keeps it
                          from reproducing (no way, settings not valid,
                          `needs` missing) and how to fix it; empty when ready
  repro-ways.py brief     the way's part of the writer's brief (markdown)
  repro-ways.py lint FILE exit 1, saying why, when FILE reads a stylesheet
                          as text: never a reproduction of how a page looks
  repro-ways.py verdict JUNIT NAME [ASSERTION]
                          reproduced|passed|broken|environment from a JUnit
                          report, for the test file NAME (every case, when
                          no case names it nor any file: node:test's, #501)
  repro-ways.py affected  the tests a pull request runs, from the changed
                          paths on stdin: JSON {"targeted", "tests", "repro",
                          "smoke"}
  repro-ways.py propose   the stack recognised in the repository at DIR and
                          the way it proposes (#377), as `repro:` takes it;
                          exit 1 when no stack is recognised
  repro-ways.py missing   exit 1, saying which way to declare (the one its
                          stack proposes, or the keys to write), when the
                          repository at DIR declares no way for `logic`:
                          neither its kind's pack, nor the organisation's
                          repos.yml, nor its own policy
  repro-ways.py --test    self-test

Environment: DIR, LAYER, NUMBER, CENTRAL (the organisation's checkout, for
`{kind}`: its kinds/<kind>/ folder, and its repos.yml), REPO_POLICY (default
DIR/.github/review-policy.yml), REPO (default GITHUB_REPOSITORY: its name in
repos.yml).
"""
import fnmatch
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import repos_conf  # noqa: E402  repos.yml's one entry per repository (#562)
LAYERS = ("logic", "browser", "cli", "api", "workflow")
KEYS = {"layer", "noun", "test", "needs", "sandbox", "setup", "theme", "run", "junit", "case", "assertion", "teardown",
        "minutes", "context", "list", "example", "guide", "shots"}
SANDBOXES = ("php-unit",)
# How the comments say each layer is reproduced.
WHERE = {"logic": "with a test of the code's logic", "browser": "in a browser", "cli": "through a command's output",
         "api": "through its API", "workflow": "with a test that reads the workflow's file (its triggers, steps and conditions)"}
HOW = ("declare one in `repro.ways` of the repository's .github/review-policy.yml (or of its kind's pack, "
       "kinds/<kind>/pack.yml in DiluxOne/.github): the `layer` it reproduces, the `test` the agent writes "
       "(with `{n}`), the `run` command and the `junit` report it writes; scripts/repro-ways.py says what each key means")


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


schema = _load("issue_schema", "issue-schema.py")


def read(path):
    data = schema.read_yaml(path) if path and os.path.exists(path) else {}
    return data if isinstance(data, dict) else {}


def merged(pack, repo, org=None):
    """The pack's `repro:` with the repository's over it: a way named in both
    is the pack's with the repository's keys over it; `false` switches a way
    off; `affected` is the pack's entries and then the repository's. `org`,
    the organisation's repos.yml `repro:` for the repository (#377), goes
    between the two, the same way."""
    if org:
        pack = {"repro": merged(pack, {"repro": org})}
    base = pack.get("repro") if isinstance(pack.get("repro"), dict) else {}
    mine = repo.get("repro") if isinstance(repo.get("repro"), dict) else {}
    ways = {}
    for name, way in (base.get("ways") or {}).items():
        if isinstance(way, dict):
            ways[name] = dict(way)
    for name, way in (mine.get("ways") or {}).items():
        if way is False:
            ways.pop(name, None)
        elif isinstance(way, dict):
            ways[name] = {**ways.get(name, {}), **way}
    # The repository's ways first: for a layer two ways cover, its own wins.
    # Neither saying anything is no way at all: no stack is assumed (#376).
    own = [n for n in (mine.get("ways") or {}) if n in ways]
    ways = {**{n: ways[n] for n in own}, **{n: w for n, w in ways.items() if n not in own}}
    affected = [a for a in (base.get("affected") or []) + (mine.get("affected") or []) if isinstance(a, dict)]
    # #479: the smoke set, the few specs a pull request runs beside the
    # mapped ones where the merge queue runs every suite: the pack's, then
    # the repository's, each once.
    smoke = []
    for t in (base.get("smoke") or []) + (mine.get("smoke") or []):
        if isinstance(t, str) and t and t not in smoke:
            smoke.append(t)
    return {"ways": ways, "affected": affected, "smoke": smoke}


def problems(conf):
    """What is wrong with a merged `repro:`; empty when it is right."""
    out = []
    for name, way in conf["ways"].items():
        if not re.fullmatch(r"[a-z][a-z0-9-]*", str(name)):
            out.append(f"repro.ways: '{name}' is not a name")
        unknown = set(way) - KEYS
        if unknown:
            out.append(f"repro.ways.{name}: unknown keys {sorted(unknown)}")
        if not layers(way) or any(x not in LAYERS for x in layers(way)):
            out.append(f"repro.ways.{name}.layer: one of {', '.join(LAYERS)}, or a list of them")
        test = str(way.get("test") or "")
        if "{n}" not in test or test.startswith("/") or ".." in test.split("/"):
            out.append(f"repro.ways.{name}.test: a relative path with {{n}}")
        if way.get("sandbox") is not None and way.get("sandbox") not in SANDBOXES:
            out.append(f"repro.ways.{name}.sandbox: one of {', '.join(SANDBOXES)}")
        if way.get("assertion") is not None:
            try:
                re.compile(str(way["assertion"]))
            except re.error:
                out.append(f"repro.ways.{name}.assertion: a regular expression")
        if way.get("sandbox") is None and not (way.get("run") and way.get("junit")):
            out.append(f"repro.ways.{name}: a command way needs `run` and `junit`")
    return out


def pack_of(kinds_dir, conf, name, policy):
    """(kind, its pack) for a repository: the first of its kinds in repos.yml
    (`conf`) with a pack in KINDS_DIR, else the kind its own policy names;
    ("", {}) when none has one."""
    entry = (conf.get("repos") or {}).get(name) if isinstance(conf.get("repos"), dict) else None
    kinds = [k.get("kind") for k in ((entry or {}).get("kinds") or []) if isinstance(k, dict)] or [policy.get("kind")]
    for kind in kinds:
        kind = str(kind or "").strip()
        if re.fullmatch(r"[a-z0-9-]+", kind) and os.path.isfile(os.path.join(kinds_dir, kind, "pack.yml")):
            return kind, read(os.path.join(kinds_dir, kind, "pack.yml"))
    return "", {}


def org_repro(conf, name):
    """The organisation's repos.yml `repro:` for repository NAME (#377), {}
    when it holds none or `false`."""
    entry = repos_conf.value(conf, name, "repro")
    return entry if isinstance(entry, dict) else {}


def by_design(conf, name):
    """repos.yml `repro: {NAME: false}`: the repository has no way by
    design (a disposable one, one with no code of its own); its bugs are
    still not handed to the autopilot, but the audit does not list it."""
    return repos_conf.value(conf, name, "repro") is False


def declares(conf, name, policy, kinds_dir):
    """The ways that reproduce a `logic` bug in repository NAME: its kind's
    pack, the organisation's repos.yml (`conf`) and its own policy, merged.
    Empty is a repository with no way (#377)."""
    _, pack = pack_of(kinds_dir, conf, name, policy)
    return [n for n, w in merged(pack, policy, org_repro(conf, name))["ways"].items() if "logic" in layers(w)]


def repo_name():
    return (os.environ.get("REPO") or os.environ.get("GITHUB_REPOSITORY") or "").split("/")[-1]


def config(root, central, name=None):
    repo = read(os.environ.get("REPO_POLICY") or os.path.join(root, ".github", "review-policy.yml"))
    conf = read(os.path.join(central, "repos.yml"))
    name = repo_name() if name is None else name
    kind, pack = pack_of(os.path.join(central, "kinds"), conf, name, repo)
    return kind, merged(pack, repo, org_repro(conf, name))


# What a stack is recognised by is never under these: what a repository
# installs, builds or keeps of git.
SKIP_DIRS = {".git", "node_modules", "vendor", "build", "bin", "obj"}


def tree_of(root, limit=20000):
    """The repository's files at ROOT, relative, at most LIMIT; never a
    symbolic link, nor what it installs or builds."""
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(base, d)))
        rel = os.path.relpath(base, root)
        for f in sorted(files):
            if not os.path.islink(os.path.join(base, f)):
                out.append(f if rel == "." else f"{rel}/{f}")
            if len(out) >= limit:
                return out
    return out


def propose(root):
    """(stack, the way's name, the way) the repository at ROOT's stack
    proposes (policy/repro-stacks.yml, through scripts/detect.py), checked
    by problems() so it is always a valid way; None when none is."""
    detect = _load("detect", "detect.py")

    def text(path):
        try:
            with open(os.path.join(root, path), encoding="utf-8", errors="replace") as fh:
                return fh.read(65536)
        except OSError:
            return ""
    try:
        found = detect.stack_way(tree_of(root), text)
    except RuntimeError:  # too many files to read: no proposal, never a wrong one
        return None
    if not found or problems({"ways": {found[1]: found[2]}}):
        return None
    return found


def way_yaml(found):
    """A proposal as the `repro:` block that declares it."""
    detect = _load("detect", "detect.py")
    return "repro:\n  ways:\n" + detect.way_yaml(found[1], found[2], 4)


def missing(root, central, name=None):
    """"" when the repository at ROOT declares a way for `logic`; otherwise
    what to declare, with the way its stack proposes (#377)."""
    _, conf = config(root, central, name)
    if any("logic" in layers(w) for w in conf["ways"].values()):
        return ""
    found = propose(root)
    how = (f"its stack ({found[0]}) proposes this one, to correct where it is wrong:\n\n```yaml\n{way_yaml(found)}```" if found
           else f"no stack of policy/repro-stacks.yml is recognised in it; {HOW}")
    return f"this repository declares no way to reproduce a bug; {how}"


def layers(way):
    """The layers a way reproduces: `layer` is one, or a list."""
    value = way.get("layer")
    return [value] if isinstance(value, str) else [x for x in value] if isinstance(value, list) else []


def pick(conf, layer):
    """The first way, in the order declared, for LAYER; None when none."""
    for name, way in conf["ways"].items():
        if layer in layers(way):
            return name, way
    return None, None


def ready(root, needs):
    for path in needs or []:
        p = os.path.join(root, str(path))
        if str(path).endswith("/"):
            if not os.path.isdir(p):
                return False
        elif not os.path.exists(p):
            return False
    return True


def fill(text, number, central, kind, test=""):
    text = str(text).replace("{n}", str(number)).replace("{kind}", os.path.join(central, "kinds", kind))
    return text.replace("{test}", test) if test else text


def resolve(root, central, layer, number):
    layer = layer if layer in LAYERS else "logic"
    kind, conf = config(root, central)
    bad = problems(conf)
    name, way = pick(conf, layer)
    out = {"layer": layer, "way": "", "ready": "no", "problems": "; ".join(bad), "why": "", "proposed": ""}
    if bad:
        out["why"] = f"its reproduction settings are not valid ({out['problems']}); to fix them, {HOW}"
        return out
    if not way:
        covered = sorted({x for w in conf["ways"].values() for x in layers(w)})
        out["why"] = (f"this repository declares no way to reproduce a {layer} bug {WHERE[layer]} (its ways cover "
                      f"{', '.join(covered)}); to add one, {HOW}" if covered else
                      f"this repository declares no way to reproduce a bug; to reproduce one {WHERE[layer]}, {HOW}")
        # What its stack proposes, when it covers the layer (#377).
        found = propose(root)
        if found and layer in layers(found[2]):
            out["why"] += f"; its stack ({found[0]}) proposes the `{found[1]}` way below, in repos.yml `repro:` or its own policy"
            out["proposed"] = way_yaml(found)
        return out
    test = fill(way["test"], number, central, kind)
    is_ready = ready(root, way.get("needs"))
    out.update({
        "way": name,
        "test": test,
        "dir": os.path.dirname(test),
        "noun": str(way.get("noun") or "test"),
        "sandbox": str(way.get("sandbox") or ""),
        "minutes": str(int(way.get("minutes") or 15)),
        "ready": "yes" if is_ready else "no",
        "why": "" if is_ready else (f"its `{name}` way needs {', '.join(str(x) for x in way.get('needs') or [])}, "
                                    "which this repository does not have yet; add them, or switch the way off "
                                    f"(`repro: {{ways: {{{name}: false}}}}`) and declare another"),
        # The command way whole, as JSON, for scripts/repro-run.sh.
        "spec": json.dumps({k: (fill(v, number, central, kind, test) if isinstance(v, str) else [fill(x, number, central, kind, test) for x in v] if isinstance(v, list) else v)
                            for k, v in way.items() if k in ("setup", "theme", "run", "junit", "case", "assertion", "teardown", "minutes", "test")}, separators=(",", ":")),
    })
    return out


def brief(root, central, layer, number):
    kind, conf = config(root, central)
    name, way = pick(conf, layer if layer in LAYERS else "logic")
    if not way:
        return ""
    parts = [f"## How this repository reproduces a {layer} bug: the `{name}` way", "",
             f"Write ONE {way.get('noun') or 'test'} at `{fill(way['test'], number, central, kind)}`.", ""]
    if way.get("guide"):
        parts += [str(way["guide"]).strip(), ""]
    budget = 40000
    for path in way.get("context") or []:
        p = os.path.join(root, path)
        if os.path.isfile(p) and budget > 0:
            text = open(p, encoding="utf-8", errors="replace").read()[:min(budget, 15000)]
            budget -= len(text)
            parts += [f"## Repository file: {path}", "", "```", text, "```", ""]
    files = []
    for dirpath, _, names in os.walk(root):
        # Hidden folders are skipped but .github, where the workflows a
        # `workflow` way reads live (#376).
        if any(p.startswith(".") and p != ".github" for p in dirpath[len(root):].split("/")) or "node_modules" in dirpath or "vendor" in dirpath:
            continue
        for n in names:
            files.append(os.path.relpath(os.path.join(dirpath, n), root))
    files.sort()
    listed = [f for f in files if any(fnmatch.fnmatch(f, g) for g in way.get("list") or [])][:200]
    if listed:
        parts += ["## Test files there", ""] + [f"- {f}" for f in listed] + [""]
    if way.get("example"):
        example = next((f for f in files if fnmatch.fnmatch(f, way["example"]) and "/repro/" not in f), None)
        if example and budget > 0:
            parts += [f"## Example: {example}", "", "```", open(os.path.join(root, example), encoding="utf-8", errors="replace").read()[:min(budget, 12000)], "```", ""]
    return "\n".join(parts)


# A stylesheet read as text: a file-reading call with a .css path, in PHP,
# JavaScript or Python. How a page looks is the browser's to say (#352).
CSS_AS_TEXT = re.compile(
    r"\b(file_get_contents|fopen|file|readFileSync|readFile|open|read_text)\s*\([^;]*?\.css['\"]"
    r"|\bPath\s*\([^;)]*?\.css['\"]\s*\)\s*\.\s*read_(text|bytes)\b"
    r"|\b(Sabberworm|CssParser|csstree|postcss)\b")


def lint(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    m = CSS_AS_TEXT.search(text)
    return f"it reads a stylesheet as text ({m.group(0)[:60]}): how a page looks is reproduced in a browser" if m else ""


# What a failure that is an assertion's says, in the frameworks the packs
# use; a way's `assertion` replaces it.
ASSERTION = r"\bexpect\(|AssertionError|toBe|toEqual|toHave|assert|DID NOT RAISE"

# A classname that names a source file (Playwright's, Vitest's): a path, or
# a file's extension.
SOURCE_FILE = re.compile(r"/|\.(?:[cm]?[jt]sx?|py|php|go|rb|java|cs|rs|kt)$")


def verdict(junit, name, assertion=None):
    """reproduced when a test of NAME failed an assertion; passed when every
    test of NAME ran and passed; environment when the repository's setup
    beside it failed (the site, not the test, whatever became of the test),
    or its teardown failed and the test reached no verdict of its own; broken
    otherwise (no report, no test of NAME, an error that is not an
    assertion). A teardown that fails after the test failed an assertion,
    or passed, does not undo what the test showed."""
    try:
        root = ET.parse(junit).getroot()
    except (OSError, ET.ParseError):
        return "broken"
    cases = list(root.iter("testcase"))
    mine = [c for c in cases if name in " ".join(filter(None, (c.get("classname"), c.get("name"), c.get("file"))))]
    # node:test's junit reporter names no file: the title is `name` and
    # classname is "test" (#501). A report that attributes no case to any
    # file is the test's alone, as the reproduction runs it alone.
    if not mine and not any(c.get("file") or SOURCE_FILE.search(c.get("classname") or "") for c in cases):
        mine = cases
    others = [c for c in cases if c not in mine and (c.find("failure") is not None or c.find("error") is not None)]
    after = [c for c in others if "teardown" in " ".join(filter(None, (c.get("classname"), c.get("name"), c.get("file")))).lower()]
    if len(after) < len(others):
        return "environment"
    own = mine_verdict(mine, assertion)
    return "environment" if after and own == "broken" else own


def mine_verdict(mine, assertion=None):
    if not mine:
        return "broken"
    failed = False
    for c in mine:
        if c.find("error") is not None:
            return "broken"
        f = c.find("failure")
        if f is not None:
            text = " ".join(filter(None, (f.get("message"), f.get("type"), f.text)))
            # An exception that is not an assertion's (pytest's TypeError,
            # ImportError, KeyError) is a test that did not run, whatever
            # `assert` its traceback quotes from the test's source (#376).
            raised = re.match(r"\s*(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*(?:Error|Exception))\b", f.get("message") or "")
            if raised and raised.group(1) not in ("AssertionError", "Error", "AssertionFailedError", "ExpectationFailedException"):
                return "broken"
            # pytest.raises that saw nothing raised is an assertion too.
            if not re.search(assertion or ASSERTION, text):
                return "broken"
            # An element the test never found says its selector is wrong as
            # often as that the bug is there: no verdict. Only Playwright's
            # own words for it: its call log says "waiting for locator" on
            # every failed expect(locator), the element there or not (#366).
            if re.search(r"element\(s\) not found", text):
                return "broken"
            failed = True
        elif c.find("skipped") is not None:
            return "broken"
    return "reproduced" if failed else "passed"


def glob_match(path, pattern):
    """fnmatch where ** spans folders and * stays inside one."""
    rx = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    return re.fullmatch(rx, path) is not None


def repro_tests(conf):
    """What a command way's reproduction test is called, as a pattern: its
    `test` with any issue number."""
    return [re.compile(re.escape(str(w["test"])).replace(r"\{n\}", "[1-9][0-9]*"))
            for w in conf["ways"].values() if w.get("sandbox") is None and w.get("test")]


def affected(conf, paths, root="."):
    """The tests a pull request runs: the reproduction tests it carries (the
    files there now, named as a way names its test), and the tests mapped to
    the paths it touches. Targeted only when every path it touches is one of
    those, or matches an entry of `affected` (one with no tests: what no test
    covers, such as a readme), and there is something to run; otherwise the
    whole suite runs, as before: a path no entry names may break any test."""
    named = repro_tests(conf)
    repro = sorted(p for p in paths if any(rx.fullmatch(p) for rx in named) and os.path.isfile(os.path.join(root, p)))
    tests, covered = [], set(repro)
    for entry in conf["affected"]:
        hit = [p for p in paths if any(glob_match(p, g) for g in entry.get("paths") or [])]
        covered.update(hit)
        if hit:
            tests += [t for t in entry.get("tests") or [] if t not in tests]
    covered.update(p for p in paths if p in tests)
    every = bool(paths) and covered >= set(paths)
    return {"targeted": bool(conf["affected"]) and every and bool(repro or tests), "tests": tests, "repro": repro}


def emit(pairs):
    lines = []
    for k, v in pairs.items():
        v = str(v)
        lines.append(f"{k}<<DX_EOF\n{v}\nDX_EOF" if "\n" in v else f"{k}={v}")
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        ok = got == want
        failed += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": got {got!r}, want {want!r}"))

    central = os.path.dirname(HERE)
    # The repository it runs in is none of repos.yml's, whatever the runner says.
    os.environ["REPO"] = "Acme/none-such"
    with tempfile.TemporaryDirectory() as d:
        def repo(policy, files=()):
            for entry in os.listdir(d):
                shutil.rmtree(os.path.join(d, entry)) if os.path.isdir(os.path.join(d, entry)) else os.remove(os.path.join(d, entry))
            for f in (".github",) + tuple(os.path.dirname(x) for x in files if os.path.dirname(x)):
                os.makedirs(os.path.join(d, f), exist_ok=True)
            with open(os.path.join(d, ".github", "review-policy.yml"), "w") as fh:
                fh.write(policy)
            for f in files:
                if f.endswith("/"):
                    os.makedirs(os.path.join(d, f), exist_ok=True)
                else:
                    open(os.path.join(d, f), "w").write("x")

        wp = "kind: wordpress-plugin\n"
        repo(wp, ["tests/bootstrap.php", "tests/Unit/", ".wp-env.json", "package.json", "playwright.config.ts"])
        r = resolve(d, central, "browser", 69)
        check("C1 a wordpress plugin reproduces a browser bug with its browser way", (r["way"], r["test"], r["ready"], r["sandbox"]),
              ("browser", "tests/e2e/repro/issue-69.spec.ts", "yes", ""))
        spec = json.loads(r["spec"])
        check("C1 the command runs only the new test, in chromium", ("{test}" not in spec["run"], "chromium" in spec["run"], "tests/e2e/repro/issue-69.spec.ts" in spec["run"]), (True, True, True))
        r = resolve(d, central, "logic", 12)
        check("C2 a logic bug keeps the unit test", (r["way"], r["test"], r["sandbox"], r["ready"]), ("unit", "tests/Unit/Repro/Issue12Test.php", "php-unit", "yes"))
        check("C2 no layer is a logic bug", resolve(d, central, "", 12)["way"], "unit")
        check("C6 a plugin with no reproduction settings gets the pack's unit and browser",
              sorted(x for w in config(d, central)[1]["ways"].values() for x in layers(w)), ["api", "browser", "cli", "logic"])
        check("a WP-CLI or REST bug in a plugin is a unit test there", (resolve(d, central, "cli", 3)["way"], resolve(d, central, "api", 3)["way"]), ("unit", "unit"))
        repo(wp + "repro:\n  ways:\n    browser: false\n", ["tests/bootstrap.php", "tests/Unit/"])
        r = resolve(d, central, "browser", 69)
        check("C3 a repository with no browser way declares nothing for that layer", (r["way"], r["ready"]), ("", "no"))
        repo("kind: library\n")
        check("C3 a kind with no ways reproduces nothing in a browser", resolve(d, central, "browser", 1)["way"], "")
        # #376: no stack is assumed. A repository whose kind and policy
        # declare nothing has no way, and says how to declare one.
        r = resolve(d, central, "logic", 1)
        check("#376 C3 a repository that declares nothing has no way, not a PHP unit test",
              (r["way"], r["ready"], "declares no way to reproduce a bug" in r["why"], "repro.ways" in r["why"]), ("", "no", True, True))
        repo("high-risk: [scripts/**]\n", ["pyproject.toml", "tests/bootstrap.php", "tests/Unit/"])
        check("#376 C3 whatever files it has (Python, or PHP's own) it gets no way of a stack",
              (resolve(d, central, "logic", 1)["way"], resolve(d, central, "workflow", 1)["way"]), ("", ""))
        repo(wp, ["tests/bootstrap.php", "tests/Unit/"])
        check("#376 a plugin keeps its unit way: the pack declares it, nothing falls back",
              (resolve(d, central, "logic", 1)["way"], resolve(d, central, "logic", 1)["sandbox"], resolve(d, central, "logic", 1)["why"]), ("unit", "php-unit", ""))
        r = resolve(d, central, "workflow", 1)
        check("#376 C3 a layer no way covers says which it covers and how to add one",
              (r["way"], "no way to reproduce a workflow bug" in r["why"], "api, browser, cli, logic" in r["why"]), ("", True, True))
        repo(wp)
        check("#376 C3 a way whose files are missing says which", "tests/bootstrap.php, tests/Unit/" in resolve(d, central, "logic", 1)["why"], True)
        repo(wp + "repro:\n  ways:\n    bad:\n      layer: screen\n")
        check("#376 C3 settings that are not valid say so", "not valid" in resolve(d, central, "logic", 1)["why"], True)
        # This repository's own ways (#376): a Python test for a script's
        # logic, one that reads the workflow's file for its wiring.
        here = {"REPO_POLICY": os.path.join(central, ".github", "review-policy.yml")}
        saved = {k: os.environ.get(k) for k in here}
        os.environ.update(here)
        try:
            logic, wf, cli = (resolve(central, central, x, 366) for x in ("logic", "workflow", "cli"))
            spec = json.loads(logic["spec"])
            check("#376 C1 a logic bug here is a Python test, run by pytest with a JUnit report",
                  (logic["way"], logic["test"], logic["ready"], logic["sandbox"], "pytest" in spec["run"], "tests/repro/test_issue_366.py" in spec["run"], spec["junit"]),
                  ("python", "tests/repro/test_issue_366.py", "yes", "", True, True, "build/dx-repro-junit.xml"))
            check("#376 pytest is installed in setup, before the test is in the tree", any("pytest" in s for s in spec["setup"]), True)
            check("#376 C2 a workflow bug here is a test that reads the workflow",
                  (wf["way"], wf["test"], wf["ready"], wf["noun"]), ("workflow", "tests/repro/test_issue_366.py", "yes", "workflow test"))
            check("#376 a script's command is a Python test too", cli["way"], "python")
            b = brief(central, central, "workflow", 375)
            check("#376 C2 the workflow way's brief lists the workflows and shows its example",
                  (".github/workflows/weekly-failure.yml" in b, "## Example: tests/examples/test_workflow.py" in b, "wf.get(True)" in b), (True, True, True))
            b = brief(central, central, "logic", 366)
            check("#376 C1 the logic way's brief shows how a script is loaded", ("## Example: tests/examples/test_logic.py" in b, "spec_from_file_location" in b), (True, True))
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        repo(wp + "repro:\n  ways:\n    cli:\n      layer: cli\n      noun: CLI test\n      test: tests/cli/issue-{n}.sh\n      run: bash {test}\n      junit: build/cli.xml\n")
        r = resolve(d, central, "cli", 5)
        check("a repository adds a way of its own", (r["way"], r["test"]), ("cli", "tests/cli/issue-5.sh"))
        repo(wp + "repro:\n  ways:\n    browser:\n      minutes: 30\n")
        check("a repository changes one key of the pack's way", resolve(d, central, "browser", 1)["minutes"], "30")
        repo(wp + "repro:\n  ways:\n    bad:\n      layer: screen\n      test: /etc/x\n")
        check("a wrong way says so and resolves to none", (resolve(d, central, "browser", 1)["way"] == "", "layer" in resolve(d, central, "browser", 1)["problems"]), (True, True))
        repo(wp, [".wp-env.json"])
        check("a way whose files are missing is not ready", resolve(d, central, "browser", 1)["ready"], "no")
        repo(wp, ["playwright.config.ts", "tests/e2e/specs/a.spec.ts"])
        b = brief(d, central, "browser", 69)
        check("C7 the brief asks for a phone, dark mode or another theme only when the report says so",
              ("only when the report talks about a phone" in b, "only when the report mentions it" in b, "another only when the report names it" in b,
               "tests/e2e/repro/issue-69.spec.ts" in b, "tests/e2e/specs/a.spec.ts" in b), (True, True, True, True, True))
        check("the brief forbids screenshots compared pixel by pixel", "toHaveScreenshot" in b, True)

        def lint_of(text, ext="php"):
            p = os.path.join(d, f"t.{ext}")
            open(p, "w").write(text)
            return bool(lint(p))
        check("C4 a unit test that reads CSS as text is rejected",
              (lint_of("$css = file_get_contents( DIR . '/assets/css/front.css' );"), lint_of("const css = fs.readFileSync('assets/front.css', 'utf8');", "ts")), (True, True))
        check("C4 a browser test that measures the page is not", lint_of("const box = await page.locator('.card').boundingBox();\nawait expect(page).toHaveCSS", "ts"), False)
        check("C4 a test naming a stylesheet in a URL is not", lint_of("await page.goto('/wp-admin/');\nexpect(href).toContain('front.css');", "ts"), False)
        check("C4 a logic test that builds a stylesheet's path is not",
              lint_of("$url = plugin_dir_path( __FILE__ ) . 'css/front.css';\nwp_enqueue_style( 'x', $url );"), False)
        check("C4 a Python test reading it through pathlib is", lint_of("css = Path('assets/front.css').read_text()", "py"), True)
        check("C4 one that reads it through a built path is",
              lint_of("$css = file_get_contents( plugin_dir_path( __FILE__ ) . 'css/front.css' );"), True)

        def junit_any(xml, name):
            p = os.path.join(d, "j.xml")
            open(p, "w").write(xml)
            return verdict(p, name)

        def junit(xml):
            return junit_any(xml, "issue-69.spec.ts")
        ok_setup = '<testcase name="sign in" classname="global.setup.ts"/>'
        check("C1 an assertion that fails reproduces",
              junit(f'<testsuites><testsuite>{ok_setup}<testcase name="x" classname="issue-69.spec.ts"><failure message="Error: expect(received).toBe(expected)"/></testcase></testsuite></testsuites>'), "reproduced")
        check("a test that passes does not", junit('<testsuites><testsuite><testcase name="x" classname="issue-69.spec.ts"/></testsuite></testsuites>'), "passed")
        check("C8 an error that is not an assertion is no verdict",
              junit('<testsuites><testsuite><testcase name="x" classname="issue-69.spec.ts"><failure message="TypeError: page.lokator is not a function"/></testcase></testsuite></testsuites>'), "broken")
        check("C8 a setup that failed is the environment, not the test",
              junit('<testsuites><testsuite><testcase name="s" classname="global.setup.ts"><failure message="Timeout"/></testcase><testcase name="x" classname="issue-69.spec.ts"><failure message="expect(x)"/></testcase></testsuite></testsuites>'), "environment")
        check("a teardown that fails after the test failed an assertion does not undo the reproduction",
              junit('<testsuites><testsuite><testcase name="x" classname="issue-69.spec.ts"><failure message="Error: expect(received).toBe(expected)"/></testcase><testcase name="t" classname="global.teardown.ts"><failure message="TypeError: Invalid URL"/></testcase></testsuite></testsuites>'), "reproduced")
        teardown = '<testcase name="t" classname="global.teardown.ts"><failure message="TypeError: Invalid URL"/></testcase>'
        check("a teardown that fails after the test passed does not undo the pass",
              junit(f'<testsuites><testsuite><testcase name="x" classname="issue-69.spec.ts"/>{teardown}</testsuite></testsuites>'), "passed")
        check("C8 a teardown that fails when the test errored is the environment",
              junit(f'<testsuites><testsuite><testcase name="x" classname="issue-69.spec.ts"><failure message="page.goto: Invalid URL"/></testcase>{teardown}</testsuite></testsuites>'), "environment")
        check("C8 even when the test itself never ran",
              junit('<testsuites><testsuite><testcase name="s" classname="global.setup.ts"><failure message="page.goto: Protocol error"/></testcase><testcase name="t" classname="global.teardown.ts"><failure message="TypeError: Invalid URL"/></testcase></testsuite></testsuites>'), "environment")
        check("C8 no test of the file is no verdict", junit("<testsuites><testsuite/></testsuites>"), "broken")
        # Playwright's report of a failed expect(locator): its message, and
        # the details with the call log as the failure's text (#366).
        def report(message, details):
            return ('<testsuites><testsuite><testcase name="x" classname="issue-69.spec.ts">'
                    f'<failure message="{message}">{details}</failure></testcase></testsuite></testsuites>')
        underline = ("Locator: .diluxone-users-account--guest a.diluxone-users-button\nExpected: &quot;none&quot;\n"
                     "Received: &quot;underline&quot;\nTimeout: 10000ms\nCall log:\n  - Expect &quot;toHaveCSS&quot; with timeout 10000ms\n"
                     "  - waiting for locator('.diluxone-users-account--guest a.diluxone-users-button')\n")
        check("#366 C1 an assertion on an element that exists reproduces, whatever its call log says",
              junit(report("Error: expect(locator).toHaveCSS(expected) failed", underline)), "reproduced")
        not_found = "Locator: .nope\nExpected: visible\nReceived: &lt;element(s) not found&gt;\nCall log:\n  - waiting for locator('.nope')\n"
        check("#366 C2 an element the test never found is no verdict (a wrong selector)",
              junit(report("Error: expect(locator).toBeVisible() failed", not_found)), "broken")
        check("C8 an element the test never found is no verdict (a wrong selector)",
              junit('<testsuites><testsuite><testcase name="x" classname="issue-69.spec.ts"><failure message="Error: expect(locator).toBeVisible() failed. Locator: .nope Expected: visible Received: &lt;element(s) not found&gt;"/></testcase></testsuite></testsuites>'), "broken")
        check("C8 no report is no verdict", verdict(os.path.join(d, "none.xml"), "issue-69.spec.ts"), "broken")
        # node:test's junit reporter: the title as name, classname="test",
        # no `file` (#501).
        def node_test(inner):
            return junit_any('<testsuites name="test"><testsuite name="test">'
                             f'<testcase name="the player keeps its volume" classname="test">{inner}</testcase></testsuite></testsuites>', "issue-239.test.mts")
        check("#501 a node:test assert that fails reproduces, with no file named",
              node_test('<failure type="testCodeFailure" message="Expected values to be strictly equal:">AssertionError [ERR_ASSERTION]: Expected values</failure>'), "reproduced")
        check("#501 a node:test report that passes passes", node_test(""), "passed")
        check("#501 a node:test TypeError is no verdict",
              node_test('<failure type="testCodeFailure" message="TypeError: x is not a function">TypeError: x is not a function</failure>'), "broken")
        check("#501 a report naming another file and none of the test's stays no verdict",
              junit('<testsuites><testsuite><testcase name="x" classname="other.spec.ts"/></testsuite></testsuites>'), "broken")
        # pytest's report (#376, junit_family=xunit1, so `file` names the test).
        def pytest_report(*cases):
            p = os.path.join(d, "p.xml")
            body = "".join(f'<testcase classname="tests.repro.test_issue_7" name="t{i}" file="tests/repro/test_issue_7.py">{c}</testcase>' for i, c in enumerate(cases))
            open(p, "w").write(f"<testsuites><testsuite>{body}</testsuite></testsuites>")
            return verdict(p, "test_issue_7.py")
        trace = "def test_x():\n&gt;       assert f() == 2\nE       TypeError: unsupported operand"
        check("#376 C1 a pytest assertion that fails reproduces", pytest_report('<failure message="assert 1 == 2">E  assert 1 == 2</failure>'), "reproduced")
        check("#376 a pytest exception is no verdict, whatever assert its traceback quotes",
              pytest_report(f'<failure message="TypeError: unsupported operand type(s)">{trace}</failure>'), "broken")
        check("#376 a dotted exception is no verdict either", pytest_report('<failure message="json.decoder.JSONDecodeError: Expecting value">assert x</failure>'), "broken")
        check("#376 an AssertionError with a message reproduces", pytest_report('<failure message="AssertionError: the bot has a cap">assert</failure>'), "reproduced")
        check("#376 a pytest.raises that saw nothing raised reproduces",
              pytest_report('<failure message="Failed: DID NOT RAISE &lt;class \'ValueError\'&gt;">E   Failed: DID NOT RAISE</failure>'), "reproduced")
        check("#376 a passing pytest test passes", pytest_report(""), "passed")
        check("#376 a test file that does not import is no verdict",
              junit_any('<testsuites><testsuite><testcase classname="" name="tests.repro.test_issue_7" file="tests/repro/test_issue_7.py"><error message="collection failure"/></testcase></testsuite></testsuites>', "test_issue_7.py"), "broken")

        way = {"browser": {"layer": "browser", "test": "tests/e2e/repro/issue-{n}.spec.ts", "run": "x", "junit": "y"}}
        conf = merged({"repro": {"ways": way, "affected": [{"paths": ["assets/**/*.css", "templates/**"], "tests": ["tests/e2e/specs/layout.spec.ts"]}]}}, {})
        repo(wp, ["tests/e2e/repro/issue-69.spec.ts", "tests/e2e/repro/helpers.ts"])
        check("C5 a pull request touching mapped paths runs the reproduction and the mapped tests",
              affected(conf, ["assets/css/front.css", "tests/e2e/repro/issue-69.spec.ts"], d),
              {"targeted": True, "tests": ["tests/e2e/specs/layout.spec.ts"], "repro": ["tests/e2e/repro/issue-69.spec.ts"]})
        check("C5 a file beside the reproduction tests that is not one is not run, and keeps it whole",
              affected(conf, ["assets/css/front.css", "tests/e2e/repro/helpers.ts"], d), {"targeted": False, "tests": ["tests/e2e/specs/layout.spec.ts"], "repro": []})
        check("C5 a reproduction test the pull request deletes is not run",
              affected(conf, ["assets/css/front.css", "tests/e2e/repro/issue-70.spec.ts"], d)["repro"], [])
        check("C5 one touching nothing mapped runs the whole suite", affected(conf, ["includes/a.php"], d)["targeted"], False)
        check("C5 one touching a mapped path and an unmapped one runs the whole suite",
              affected(conf, ["assets/css/front.css", "includes/a.php"], d)["targeted"], False)
        docs = merged({"repro": {"ways": way, "affected": [{"paths": ["assets/**/*.css"], "tests": ["tests/e2e/specs/layout.spec.ts"]}, {"paths": ["readme.txt"], "tests": []}]}}, {})
        check("C5 a path an entry maps to no tests (the changelog) keeps it targeted",
              affected(docs, ["assets/css/front.css", "readme.txt"], d)["targeted"], True)
        check("C5 a change to a mapped test itself keeps it targeted",
              affected(docs, ["assets/css/front.css", "tests/e2e/specs/layout.spec.ts"], d)["targeted"], True)
        check("C5 a repository that maps nothing runs the whole suite", affected(merged({}, {}), ["assets/a.css"], d)["targeted"], False)
        check("#479 C3 the smoke set is the pack's, then the repository's, each once, never a non-string",
              merged({"repro": {"smoke": ["tests/e2e/specs/smoke.spec.ts"]}}, {"repro": {"smoke": ["tests/e2e/specs/smoke.spec.ts", "tests/e2e/specs/login.spec.ts", 3]}})["smoke"],
              ["tests/e2e/specs/smoke.spec.ts", "tests/e2e/specs/login.spec.ts"])
        check("#479 C3 none said is none", merged({}, {})["smoke"], [])
        check("** spans folders, * does not", (glob_match("assets/css/a.css", "assets/**/*.css"), glob_match("assets/a.css", "assets/**/*.css"), glob_match("assets/css/a.css", "assets/*.css")), (True, True, False))

        # #377: the organisation's repos.yml between the pack and the
        # repository, and the way a repository's stack proposes.
        unit = {"layer": "logic", "test": "tests/repro/test_issue_{n}.py", "run": "pytest {test}", "junit": "build/repro.xml"}
        both = merged({"repro": {"ways": {"a": {"layer": "logic", "test": "p/{n}", "run": "p", "junit": "p.xml"}}}},
                      {"repro": {"ways": {"a": {"run": "mine"}}}}, {"ways": {"a": {"run": "org", "junit": "org.xml"}, "b": unit}})
        check("#377 org's ways go over the pack's, the repository's over both, its own first",
              (list(both["ways"]), both["ways"]["a"]["run"], both["ways"]["a"]["junit"]), (["a", "b"], "mine", "org.xml"))
        check("#377 a way the organisation declares, the repository may switch off",
              list(merged({}, {"repro": {"ways": {"b": False}}}, {"ways": {"b": unit}})["ways"]), [])
        org_conf = {"repos": {"api": {"kinds": []}, "plugin": {"kinds": [{"kind": "wordpress-plugin", "paths": ["**"]}]}},
                    "repro": {"api": {"ways": {"pytest": unit}}}}
        kinds_dir = os.path.join(central, "kinds")
        check("#377 declares: repos.yml's way, the pack's (by repos.yml's kind, else the policy's), none for one that says nothing",
              (declares(org_conf, "api", {}, kinds_dir), declares(org_conf, "plugin", {}, kinds_dir), declares(org_conf, "site", {}, kinds_dir),
               declares(org_conf, "site", {"kind": "wordpress-plugin"}, kinds_dir)), (["pytest"], ["unit"], [], ["unit"]))
        check("#377 `false` in repos.yml: no way, by design", (by_design({"repro": {"x": False}}, "x"), by_design(org_conf, "api"),
                                                               declares({"repro": {"x": False}}, "x", {}, kinds_dir)), (True, False, []))
        check("#377 a way only for the browser is no way for a logic bug",
              declares({}, "x", {"repro": {"ways": {"e2e": {"layer": "browser", "test": "e/{n}", "run": "x", "junit": "j"}}}}, kinds_dir), [])
        with tempfile.TemporaryDirectory() as c:
            os.makedirs(os.path.join(c, "kinds"))
            with open(os.path.join(c, "repos.yml"), "w") as fh:
                fh.write("repos:\n  api: {kinds: []}\nrepro:\n  api:\n    ways:\n      pytest: {layer: logic, test: 'tests/repro/test_issue_{n}.py', run: 'pytest {test}', junit: build/repro.xml}\n")
            repo("", [])
            r = resolve(d, c, "logic", 7)
            check("#377 the organisation's way of another repository is not this one's", r["way"], "")
            os.environ["REPO"] = "Acme/api"
            try:
                r = resolve(d, c, "logic", 7)
                check("#377 resolve reads the organisation's repos.yml for the repository it runs in", (r["way"], r["test"]), ("pytest", "tests/repro/test_issue_7.py"))
                check("#377 missing: nothing for a repository the organisation declares a way for", missing(d, c), "")
            finally:
                os.environ["REPO"] = "Acme/none-such"
        # C2: a .NET test project proposes `dotnet test` with a JUnit logger.
        repo("", ["src/Api/Api.csproj", "Api.sln"])
        os.makedirs(os.path.join(d, "tests", "Api.Tests"))
        with open(os.path.join(d, "tests", "Api.Tests", "Api.Tests.csproj"), "w") as fh:
            fh.write('<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><PackageReference Include="Microsoft.NET.Test.Sdk" /></ItemGroup></Project>')
        found = propose(d)
        check("C2 a *.csproj test project proposes a dotnet test way with a JUnit logger",
              (found[0], "dotnet test tests/Api.Tests/Api.Tests.csproj" in found[2]["run"], '--logger "junit;LogFilePath=' in found[2]["run"], found[2]["junit"]),
              ("dotnet-test", True, True, "build/repro.xml"))
        check("C2 the proposal is a valid way", problems({"ways": {found[1]: found[2]}}), [])
        r = resolve(d, central, "logic", 9)
        check("#377 a repository with no way: why names the proposed way, and proposed is its repro: block",
              ("proposes the `dotnet-test` way" in r["why"], r["proposed"].startswith("repro:\n  ways:\n    dotnet-test:\n")), (True, True))
        check("#377 a browser bug gets no proposal of a logic way", resolve(d, central, "browser", 9)["proposed"], "")
        said = missing(d, central)
        check("#377 missing: says it declares none, with the way to declare", ("declares no way" in said, "dotnet-test:" in said), (True, True))
        repo("", ["README.md"])
        check("#377 no stack recognised: no proposal, and missing gives the keys to write",
              (propose(d), "no stack of policy/repro-stacks.yml" in missing(d, central), "`junit`" in missing(d, central)), (None, True, True))
        repo("", ["node_modules/x/pytest.ini"])
        check("#377 what a repository installs is not its stack", propose(d), None)
        # Every stack's way reaches a verdict on the report its tools write
        # (issue 7): a failed assertion reproduces, an exception does not.
        reports = {
            "php-phpunit": ('<testsuites><testsuite name="Issue7Test" file="/w/tests/Repro/Issue7Test.php"><testcase name="test_sum" class="Issue7Test" classname="Issue7Test" file="/w/tests/Repro/Issue7Test.php" line="9"><failure type="PHPUnit\\Framework\\ExpectationFailedException">Issue7Test::test_sum\nFailed asserting that 1 is identical to 2.</failure></testcase></testsuite></testsuites>',
                            '<testsuites><testsuite><testcase name="test_sum" classname="Issue7Test" file="/w/tests/Repro/Issue7Test.php"><error type="Error">Error: Call to undefined function sum()</error></testcase></testsuite></testsuites>'),
            "python-pytest": ('<testsuites><testsuite name="pytest"><testcase classname="tests.repro.test_issue_7" name="test_sum" file="tests/repro/test_issue_7.py" line="3"><failure message="assert 1 == 2">def test_sum():\n&gt;       assert sum([1]) == 2\nE       assert 1 == 2</failure></testcase></testsuite></testsuites>',
                              '<testsuites><testsuite><testcase classname="tests.repro.test_issue_7" name="test_sum" file="tests/repro/test_issue_7.py"><failure message="ImportError: cannot import name \'x\'">E   ImportError</failure></testcase></testsuite></testsuites>'),
            "dotnet-test": ('<testsuites><testsuite name="Api.Tests.dll"><testcase classname="Api.Tests.Repro.Issue7Tests" name="Api.Tests.Repro.Issue7Tests.Sum_is_two" time="0.01"><failure type="failure" message="Assert.Equal() Failure: Values differ&#10;Expected: 2&#10;Actual:   1">at Api.Tests.Repro.Issue7Tests.Sum_is_two()</failure></testcase></testsuite></testsuites>',
                            '<testsuites><testsuite><testcase classname="Api.Tests.Repro.Issue7Tests" name="Sum_is_two"><failure type="failure" message="System.NullReferenceException : Object reference not set to an instance of an object.">at Api.Sum()</failure></testcase></testsuite></testsuites>'),
            "go-test": ('<testsuites><testsuite name="example.com/api/repro" tests="1" failures="1"><testcase classname="example.com/api/repro" name="TestIssue7" time="0.00"><failure message="Failed" type="">=== RUN   TestIssue7\n    issue7_test.go:12: Sum() = 1, want 2\n--- FAIL: TestIssue7 (0.00s)\n</failure></testcase></testsuite></testsuites>',
                        '<testsuites><testsuite><testcase classname="example.com/api/repro" name="TestIssue7"><failure message="Failed" type="">panic: runtime error: index out of range [recovered]\n\t/w/repro/issue7_test.go:12 +0x1d\n</failure></testcase></testsuite></testsuites>'),
            "node-vitest": ('<testsuites><testsuite name="tests/repro/issue-7.test.ts"><testcase classname="tests/repro/issue-7.test.ts" name="sum &gt; is two" time="0.002"><failure message="expected 1 to be 2 // Object.is equality" type="AssertionError">AssertionError: expected 1 to be 2</failure></testcase></testsuite></testsuites>',
                            '<testsuites><testsuite><testcase classname="tests/repro/issue-7.test.ts" name="sum"><failure message="sum is not a function" type="TypeError">TypeError: sum is not a function</failure></testcase></testsuite></testsuites>'),
            "node-jest": ('<testsuites><testsuite name="sum"><testcase classname="sum is two" name="sum is two" file="tests/repro/issue-7.test.js"><failure>Error: expect(received).toBe(expected)\n\nExpected: 2\nReceived: 1</failure></testcase></testsuite></testsuites>',
                          '<testsuites><testsuite><testcase classname="sum" name="sum" file="tests/repro/issue-7.test.js"><failure>TypeError: sum is not a function</failure></testcase></testsuite></testsuites>'),
        }
        detect = _load("detect", "detect.py")
        stacks = detect.stacks()
        check("#377 every stack has its reports here", sorted(reports), sorted(stacks))
        got = {}
        for stack, (asserted, broke) in reports.items():
            way = detect.filled(stacks[stack]["way"], "a/b.x")
            name = fill(way.get("case") or os.path.basename(way["test"]), 7, central, "")
            out = []
            for xml in (asserted, broke):
                with open(os.path.join(d, "r.xml"), "w") as fh:
                    fh.write(xml)
                out.append(verdict(os.path.join(d, "r.xml"), name, way.get("assertion")))
            got[stack] = tuple(out)
        check("#377 every stack's report: a failed assertion reproduces, an exception is no verdict", got, {s: ("reproduced", "broken") for s in reports})
        check("#377 an assertion that is not a regular expression is said", problems({"ways": {"go": {"layer": "logic", "test": "t/{n}", "run": "x", "junit": "j", "assertion": "("}}}),
              ["repro.ways.go.assertion: a regular expression"])
        os.symlink("/etc/hostname", os.path.join(d, "pytest.ini"))
        check("#377 a symbolic link is never read nor matched", propose(d), None)
    print(f"{'all tests passed' if not failed else f'{failed} failed'}")
    return 1 if failed else 0


def main():
    args = sys.argv[1:]
    root = os.environ.get("DIR") or "."
    central = os.environ.get("CENTRAL") or os.path.dirname(HERE)
    layer = os.environ.get("LAYER") or "logic"
    number = os.environ.get("NUMBER") or "0"
    if args == ["--test"]:
        return self_test()
    if args == ["resolve"]:
        r = resolve(root, central, layer, number)
        if r["problems"]:
            print(f"::warning::repro: {r['problems']}", file=sys.stderr)
        emit(r)
        return 0
    if args == ["brief"]:
        print(brief(root, central, layer, number))
        return 0
    if len(args) == 2 and args[0] == "lint":
        why = lint(args[1])
        if why:
            print(why)
            return 1
        return 0
    if len(args) in (3, 4) and args[0] == "verdict":
        print(verdict(args[1], args[2], args[3] if len(args) == 4 and args[3] else None))
        return 0
    if args == ["propose"]:
        found = propose(root)
        if not found:
            print("no stack of policy/repro-stacks.yml is recognised here")
            return 1
        print(f"# {found[0]}\n{way_yaml(found)}", end="")
        return 0
    if args == ["missing"]:
        why = missing(root, central)
        print(why or "this repository declares a way to reproduce a bug")
        return 1 if why else 0
    if args == ["affected"]:
        _, conf = config(root, central)
        paths = [line.strip() for line in sys.stdin if line.strip()]
        print(json.dumps(dict(affected(conf, paths, root), smoke=conf.get("smoke") or [])))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
