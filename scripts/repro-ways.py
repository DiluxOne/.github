#!/usr/bin/env python3
"""The ways a repository reproduces a bug (#352): which test, where, with
what, for the layer the bug lives in.

A bug lives in a layer: `logic`, `browser`, `cli` or `api`. The triage says
which (the `layer:<name>` label), knowing nothing of the repository's tools.
The repository says how it reproduces each layer: its kind's pack gives the
default (kinds/<kind>/pack.yml, `repro:`), and its own .github/review-policy.yml
may add a way, change one, or switch one off (`repro: {ways: {name: false}}`).
Nothing about a tool is written in the workflows: issue-repro.yml asks here.

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
  teardown  a command after the verdict, best effort
  minutes   the most setup and run may take together
  context   files the writer reads whole; list: globs it sees by name;
  example   a glob whose first match it reads as the house style
  guide     what the writer must do and avoid, for this way
`repro.affected` maps paths to the tests a pull request that touches them
runs (`{paths: [globs], tests: [paths]}`), instead of the whole suite.

  repro-ways.py resolve   the way for LAYER (default logic) in the repository
                          at DIR (default .): key=value lines (also to
                          $GITHUB_OUTPUT), way= empty when it declares none,
                          ready=yes|no for its `needs`
  repro-ways.py brief     the way's part of the writer's brief (markdown)
  repro-ways.py lint FILE exit 1, saying why, when FILE reads a stylesheet
                          as text: never a reproduction of how a page looks
  repro-ways.py verdict JUNIT NAME
                          reproduced|passed|broken|environment from a JUnit
                          report, for the test file NAME
  repro-ways.py affected  the tests a pull request runs, from the changed
                          paths on stdin: JSON {"targeted", "tests", "repro"}
  repro-ways.py --test    self-test

Environment: DIR, LAYER, NUMBER, CENTRAL (the organisation's checkout, for
`{kind}`: its kinds/<kind>/ folder), REPO_POLICY (default
DIR/.github/review-policy.yml).
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
LAYERS = ("logic", "browser", "cli", "api")
KEYS = {"layer", "noun", "test", "needs", "sandbox", "setup", "theme", "run", "junit", "teardown",
        "minutes", "context", "list", "example", "guide"}
SANDBOXES = ("php-unit",)
DEFAULT_UNIT = {"layer": "logic", "noun": "unit test", "test": "tests/Unit/Repro/Issue{n}Test.php",
                "needs": ["tests/bootstrap.php", "tests/Unit/"], "sandbox": "php-unit"}


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


schema = _load("issue_schema", "issue-schema.py")


def read(path):
    data = schema.read_yaml(path) if path and os.path.exists(path) else {}
    return data if isinstance(data, dict) else {}


def merged(pack, repo):
    """The pack's `repro:` with the repository's over it: a way named in both
    is the pack's with the repository's keys over it; `false` switches a way
    off; `affected` is the pack's entries and then the repository's."""
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
    own = [n for n in (mine.get("ways") or {}) if n in ways]
    ways = {**{n: ways[n] for n in own}, **{n: w for n, w in ways.items() if n not in own}}
    if not base.get("ways") and not mine.get("ways"):
        # Neither the kind nor the repository says anything: the PHP unit
        # test every repository had before #352, which needs its setup.
        ways = {"unit": dict(DEFAULT_UNIT)}
    affected = [a for a in (base.get("affected") or []) + (mine.get("affected") or []) if isinstance(a, dict)]
    return {"ways": ways, "affected": affected}


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
        if way.get("sandbox") is None and not (way.get("run") and way.get("junit")):
            out.append(f"repro.ways.{name}: a command way needs `run` and `junit`")
    return out


def config(root, central):
    repo = read(os.environ.get("REPO_POLICY") or os.path.join(root, ".github", "review-policy.yml"))
    kind = str(repo.get("kind") or "").strip()
    pack = {}
    if re.fullmatch(r"[a-z0-9-]+", kind):
        pack = read(os.path.join(central, "kinds", kind, "pack.yml"))
    return kind, merged(pack, repo)


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
    out = {"layer": layer, "way": "", "ready": "no", "problems": "; ".join(bad)}
    if not way or bad:
        return out
    test = fill(way["test"], number, central, kind)
    out.update({
        "way": name,
        "test": test,
        "dir": os.path.dirname(test),
        "noun": str(way.get("noun") or "test"),
        "sandbox": str(way.get("sandbox") or ""),
        "minutes": str(int(way.get("minutes") or 15)),
        "ready": "yes" if ready(root, way.get("needs")) else "no",
        # The command way whole, as JSON, for scripts/repro-run.sh.
        "spec": json.dumps({k: (fill(v, number, central, kind, test) if isinstance(v, str) else [fill(x, number, central, kind, test) for x in v] if isinstance(v, list) else v)
                            for k, v in way.items() if k in ("setup", "theme", "run", "junit", "teardown", "minutes", "test")}, separators=(",", ":")),
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
        if "/." in dirpath[len(root):] or "node_modules" in dirpath or "vendor" in dirpath:
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


def verdict(junit, name):
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
    others = [c for c in cases if c not in mine and (c.find("failure") is not None or c.find("error") is not None)]
    after = [c for c in others if "teardown" in " ".join(filter(None, (c.get("classname"), c.get("name"), c.get("file")))).lower()]
    if len(after) < len(others):
        return "environment"
    own = mine_verdict(mine)
    return "environment" if after and own == "broken" else own


def mine_verdict(mine):
    if not mine:
        return "broken"
    failed = False
    for c in mine:
        if c.find("error") is not None:
            return "broken"
        f = c.find("failure")
        if f is not None:
            text = " ".join(filter(None, (f.get("message"), f.get("type"), f.text)))
            if not re.search(r"\bexpect\(|AssertionError|toBe|toEqual|toHave|assert", text):
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
        check("a repository that declares nothing keeps the unit test it had", (resolve(d, central, "logic", 1)["way"], resolve(d, central, "logic", 1)["ready"]), ("unit", "no"))
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

        def junit(xml):
            p = os.path.join(d, "j.xml")
            open(p, "w").write(xml)
            return verdict(p, "issue-69.spec.ts")
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
        missing = "Locator: .nope\nExpected: visible\nReceived: &lt;element(s) not found&gt;\nCall log:\n  - waiting for locator('.nope')\n"
        check("#366 C2 an element the test never found is no verdict (a wrong selector)",
              junit(report("Error: expect(locator).toBeVisible() failed", missing)), "broken")
        check("C8 an element the test never found is no verdict (a wrong selector)",
              junit('<testsuites><testsuite><testcase name="x" classname="issue-69.spec.ts"><failure message="Error: expect(locator).toBeVisible() failed. Locator: .nope Expected: visible Received: &lt;element(s) not found&gt;"/></testcase></testsuite></testsuites>'), "broken")
        check("C8 no report is no verdict", verdict(os.path.join(d, "none.xml"), "issue-69.spec.ts"), "broken")

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
        check("** spans folders, * does not", (glob_match("assets/css/a.css", "assets/**/*.css"), glob_match("assets/a.css", "assets/**/*.css"), glob_match("assets/css/a.css", "assets/*.css")), (True, True, False))
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
    if len(args) == 3 and args[0] == "verdict":
        print(verdict(args[1], args[2]))
        return 0
    if args == ["affected"]:
        _, conf = config(root, central)
        paths = [line.strip() for line in sys.stdin if line.strip()]
        print(json.dumps(affected(conf, paths, root)))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
