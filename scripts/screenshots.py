#!/usr/bin/env python3
"""Before and after screenshots of an autopilot pull request that changes
what a user sees (#564), for its "📸 Screenshots" section.

What is the browser layer and which specs it affects comes from the pack,
never from a list here: the repository's way whose layer is `browser`
(kinds/<kind>/pack.yml `repro.ways`, its own .github/review-policy.yml over
it, scripts/repro-ways.py), and `repro.affected`, which maps the paths a
pull request touches to the tests that cover them. Its specs are the
`*.spec.ts` among those tests, and among the paths it touches, that the
way's `list` globs name (its end-to-end tests). None, nothing runs.

They run on the base and on the head, each in its own checkout, with the
way's `setup` and `teardown` and its `shots` command, through a generated
Playwright configuration, playwright.dx-shots.config.ts, that imports the
repository's own and only turns `screenshot` on (the repository's file is
never changed). A failing test still leaves its screenshot. The images go
to the repository's orphan branch `dx-screenshots`, as
pr-<n>/{before,after}/<spec>/<test>.png, and the section is rewritten
between its markers with a before/after table; a later run replaces it. A
run that fails says so there, and never blocks the merge.

  screenshots.py plan            the plan, from the changed paths on stdin
                                 (DIR, the head's checkout; CENTRAL): JSON
                                 {specs, setup, shots, teardown}, and
                                 specs=... to $GITHUB_OUTPUT
  screenshots.py config          the generated Playwright configuration
  screenshots.py take LABEL PLAN OUT
                                 in DIR, the way's setup, the configuration,
                                 the specs of PLAN that exist there, its
                                 teardown; their images copied under
                                 OUT/LABEL/ (never fails on a test)
  screenshots.py collect REPORT LABEL OUT
                                 the images a Playwright JSON report names,
                                 copied under OUT/LABEL/<spec>/<test>.png
  screenshots.py publish OUT     the images of OUT on `dx-screenshots` and
                                 the section rewritten (GH_TOKEN,
                                 GITHUB_REPOSITORY, PR, RUN_URL; FAILED=true
                                 says the run failed)
  screenshots.py --test          self-test
"""
import base64
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BRANCH = "dx-screenshots"
CONFIG = "playwright.dx-shots.config.ts"
START, END = "<!-- dx-screenshots -->", "<!-- /dx-screenshots -->"
HEADING = "## 📸 Screenshots"
AI = "🤖 AI-generated · Claude Opus 5.5 (Anthropic)"
# At most this many images per side: a section people read, not a gallery.
MAX_SHOTS = 40


def _ways():
    spec = importlib.util.spec_from_file_location("repro_ways", os.path.join(HERE, "repro-ways.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ways = _ways()


def browser_way(conf):
    """(name, way) of the repository's way for the browser layer, or None."""
    for name, way in conf["ways"].items():
        if "browser" in ways.layers(way) and way.get("sandbox") is None:
            return name, way
    return None


def is_spec(path, way):
    """Whether PATH is one of the way's end-to-end specs."""
    globs = way.get("list") or ["tests/e2e/**"]
    return path.endswith(".spec.ts") and any(ways.glob_match(path, g) for g in globs)


def plan(conf, paths, root=".", central="", kind=""):
    """The specs a pull request's screenshots run, and how: the tests
    `repro.affected` maps its paths to, and the specs it changes, that are
    the browser way's and are there at its head. Pure but for reading
    which files exist under ROOT."""
    found = browser_way(conf)
    if not found:
        return {"specs": [], "why": "this repository declares no way for the browser layer"}
    _, way = found
    hit = ways.affected(conf, paths, root)
    specs = []
    for t in hit["tests"] + hit["repro"] + list(paths):
        if is_spec(t, way) and t not in specs and os.path.isfile(os.path.join(root, t)):
            specs.append(t)
    fill = lambda c: ways.fill(str(c), "0", central, kind)
    return {"specs": specs, "setup": [fill(c) for c in way.get("setup") or []],
            "shots": fill(way.get("shots") or "npx playwright test -c " + CONFIG + " {tests}"),
            "teardown": fill(way.get("teardown") or ""), "minutes": int(way.get("minutes") or 20)}


def config_text():
    return """/**
 * The repository's Playwright configuration with a screenshot of every test
 * (DiluxOne/.github#564, scripts/screenshots.py): written next to it by
 * pr-screenshots.yml for the before and after runs of a pull request, never
 * committed. Everything else is the repository's own.
 */
import { defineConfig } from '@playwright/test';
import base from './playwright.config';

const label = process.env.DX_SHOTS === 'before' ? 'before' : 'after';
const on = <T extends { use?: object }>(p: T): T => ({ ...p, use: { ...(p.use ?? {}), screenshot: 'on' } });

export default defineConfig({
	...base,
	retries: 0,
	outputDir: `build/dx-shots/${label}`,
	reporter: [['json', { outputFile: `build/dx-shots-${label}.json` }], ['line']],
	use: { ...(base.use ?? {}), screenshot: 'on' },
	...(base.projects ? { projects: base.projects.map(on) } : {}),
});
"""


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:80] or "test"


def spec_name(path):
    return slug(os.path.basename(str(path)).removesuffix(".ts").removesuffix(".spec"))


def shots(report):
    """(spec, test, image path) for each test of a Playwright JSON report
    that has a screenshot: its last result's. Pure."""
    out = []

    def walk(suite, file):
        file = suite.get("file") or file
        for spec in suite.get("specs") or []:
            for test in spec.get("tests") or []:
                results = test.get("results") or []
                pngs = [a.get("path") for a in ((results[-1] if results else {}).get("attachments") or [])
                        if a.get("contentType") == "image/png" and a.get("path")]
                if pngs:
                    out.append((spec_name(spec.get("file") or file), slug(spec.get("title")), pngs[-1]))
        for child in suite.get("suites") or []:
            walk(child, file)

    for suite in (report or {}).get("suites") or []:
        walk(suite, "")
    return out


def collect(report_path, label, out, root="."):
    try:
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
    except (OSError, ValueError):
        return []
    done = []
    for spec, test, path in shots(report)[:MAX_SHOTS]:
        src = path if os.path.isabs(path) else os.path.join(root, path)
        if not os.path.isfile(src):
            continue
        dest = os.path.join(out, label, spec, f"{test}.png")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(src, dest)
        done.append(f"{label}/{spec}/{test}.png")
    return done


def listed(out):
    """{label: {(spec, test)}} of the images under OUT."""
    found = {"before": set(), "after": set()}
    for label in found:
        base = os.path.join(out, label)
        for spec in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            for name in sorted(os.listdir(os.path.join(base, spec))):
                if name.endswith(".png"):
                    found[label].add((spec, name[:-4]))
    return found


def section(repo, number, found, run_url="", failed=False):
    """The section's text between its markers: a before/after table that
    links every image, or what went wrong. Pure."""
    run = f" ([the run]({run_url}))" if run_url.startswith("https://github.com/") else ""
    if failed:
        body = f"The screenshots could not be taken this time{run}; this does not block the merge."
    elif not (found["before"] or found["after"]):
        body = f"No screenshot: the browser-layer specs this change affects left none{run}."
    else:
        url = lambda label, spec, test: f"https://github.com/{repo}/blob/{BRANCH}/pr-{number}/{label}/{spec}/{test}.png?raw=true"
        cell = lambda label, key: f"![{label}]({url(label, *key)})" if key in found[label] else "—"
        rows = ["| Spec · test | Before | After |", "| --- | --- | --- |"]
        for key in sorted(found["before"] | found["after"]):
            rows.append(f"| `{key[0]}` · {key[1]} | {cell('before', key)} | {cell('after', key)} |")
        body = f"Before (the base) and after (this branch), of the browser-layer specs this change affects{run}:\n\n" + "\n".join(rows)
    return f"{START}\n{body}\n{END}"


def set_section(body, text):
    """BODY with TEXT between its markers: replaced where they are, else put
    under the "📸 Screenshots" heading (what it held goes), else a new
    section before the AI line. Pure."""
    body = body or ""
    if START in body and END in body:
        a, b = body.index(START), body.index(END) + len(END)
        return body[:a] + text + body[b:]
    if HEADING in body:
        a = body.index(HEADING) + len(HEADING)
        nxt = re.search(r"^## ", body[a:], re.M)
        b = a + nxt.start() if nxt else len(body)
        return body[:a] + "\n\n" + text + "\n\n" + body[b:].lstrip("\n")
    m = re.search(r"\n🤖 AI-[a-z]+ ·[^\n]*\s*$", body)
    at = m.start() if m else len(body.rstrip())
    return body[:at].rstrip() + f"\n\n{HEADING}\n\n{text}\n" + body[at:]


def gh(*args, data=None):
    res = subprocess.run(["gh", "api"] + list(args), input=json.dumps(data) if data is not None else None, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip()[:300])
    return json.loads(res.stdout) if res.stdout.strip() else {}


def push(repo, number, out, api=gh):
    """The images under OUT committed to BRANCH as pr-<n>/..., through the
    API (signed); the branch is created, orphan, when it is missing."""
    files = []
    for label in ("before", "after"):
        base = os.path.join(out, label)
        for root, _, names in os.walk(base):
            for name in sorted(names):
                if name.endswith(".png"):
                    full = os.path.join(root, name)
                    files.append((f"pr-{number}/{os.path.relpath(full, out)}", full))
    if not files:
        return 0
    try:
        head = api(f"repos/{repo}/git/ref/heads/{BRANCH}")["object"]["sha"]
        tree = api(f"repos/{repo}/git/commits/{head}")["tree"]["sha"]
    except RuntimeError as e:
        if "404" not in str(e) and "Not Found" not in str(e):
            raise
        head = tree = None
    entries = []
    for path, full in files:
        with open(full, "rb") as fh:
            blob = api("-X", "POST", f"repos/{repo}/git/blobs", "--input", "-", data={"content": base64.b64encode(fh.read()).decode(), "encoding": "base64"})
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    new_tree = api("-X", "POST", f"repos/{repo}/git/trees", "--input", "-", data=dict({"tree": entries}, **({"base_tree": tree} if tree else {})))
    commit = api("-X", "POST", f"repos/{repo}/git/commits", "--input", "-",
                 data={"message": f"Screenshots of #{number}", "tree": new_tree["sha"], "parents": [head] if head else []})
    if head:
        api("-X", "PATCH", f"repos/{repo}/git/refs/heads/{BRANCH}", "--input", "-", data={"sha": commit["sha"], "force": False})
    else:
        api("-X", "POST", f"repos/{repo}/git/refs", "--input", "-", data={"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})
    return len(files)


def take(label, plan_, out, root="."):
    """The way's setup, the configuration, the specs that exist here, the
    teardown, in ROOT; the images under OUT/LABEL. Never fails on a test."""
    specs = [s for s in plan_.get("specs") or [] if os.path.isfile(os.path.join(root, s))]
    if not specs:
        print(f"{label}: none of the specs is here")
        return []
    env = dict(os.environ, DX_SHOTS=label, CI="true")
    for cmd in plan_.get("setup") or []:
        subprocess.run(["bash", "-c", cmd], cwd=root, env=env, check=True, timeout=60 * plan_.get("minutes", 20))
    with open(os.path.join(root, CONFIG), "w", encoding="utf-8") as fh:
        fh.write(config_text())
    run = plan_["shots"].replace("{tests}", " ".join(specs))
    rc = subprocess.run(["bash", "-c", run], cwd=root, env=env, timeout=60 * plan_.get("minutes", 20)).returncode
    print(f"{label}: the specs ran (exit {rc}); a failing test still has its screenshot")
    if plan_.get("teardown"):
        subprocess.run(["bash", "-c", plan_["teardown"]], cwd=root, env=env)
    return collect(os.path.join(root, f"build/dx-shots-{label}.json"), label, out, root)


def self_test():
    import tempfile
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    pack = ways.read(os.path.join(HERE, "..", "kinds", "wordpress-plugin", "pack.yml"))
    mine = {"repro": {"affected": [{"paths": ["assets/**/*.css", "templates/**"], "tests": ["tests/e2e/specs/front-layout.spec.ts"]},
                                   {"paths": ["includes/**"], "tests": ["tests/Unit/FooTest.php"]}]}}
    conf = ways.merged(pack, mine)
    with tempfile.TemporaryDirectory() as d:
        for f in ("tests/e2e/specs/front-layout.spec.ts", "tests/e2e/specs/admin.spec.ts", "tests/Unit/FooTest.php"):
            os.makedirs(os.path.dirname(os.path.join(d, f)), exist_ok=True)
            open(os.path.join(d, f), "w").close()
        p = plan(conf, ["assets/css/front.css"], d, "/c", "wordpress-plugin")
        check("C4 a browser-layer path → the specs repro.affected maps it to", p["specs"], ["tests/e2e/specs/front-layout.spec.ts"])
        check("C4 a spec the change touches is one of them", plan(conf, ["tests/e2e/specs/admin.spec.ts", "readme.txt"], d)["specs"], ["tests/e2e/specs/admin.spec.ts"])
        check("C4 a path only a unit test covers runs nothing", plan(conf, ["includes/a.php"], d)["specs"], [])
        check("C4 nor does a mapped spec that is not there", plan(ways.merged(pack, {"repro": {"affected": [{"paths": ["a.css"], "tests": ["tests/e2e/specs/gone.spec.ts"]}]}}), ["a.css"], d)["specs"], [])
        check("C4 no browser way, nothing runs", plan(ways.merged(pack, {"repro": {"ways": {"browser": False}}}), ["assets/css/front.css"], d)["specs"], [])
        check("C4 the way's setup and its shots command come from the pack",
              (p["setup"][0], "cp /c/kinds/wordpress-plugin/playwright.dx-repro.config.ts" in " ".join(p["setup"]), p["shots"], p["teardown"]),
              ("npm ci --no-audit --no-fund", True, f"npx playwright test -c {CONFIG} --project=chromium {{tests}}", "npx wp-env stop"))
    cfg = config_text()
    check("C4 the generated config imports the repository's and turns screenshots on, every project too",
          ("import base from './playwright.config';" in cfg, "screenshot: 'on'" in cfg, "base.projects.map(on)" in cfg, "retries: 0" in cfg), (True, True, True, True))
    check("C4 the before and after runs report and write apart",
          ("build/dx-shots-${label}.json" in cfg, "outputDir: `build/dx-shots/${label}`" in cfg, "process.env.DX_SHOTS === 'before'" in cfg), (True, True, True))
    report = {"suites": [{"file": "specs/front-layout.spec.ts", "specs": [], "suites": [{"specs": [
        {"title": "The header stays on one line", "file": "specs/front-layout.spec.ts", "tests": [{"results": [
            {"attachments": [{"name": "screenshot", "contentType": "image/png", "path": "build/dx-shots/after/x/test-finished-1.png"}]}]}]},
        {"title": "No screenshot", "tests": [{"results": [{"attachments": [{"name": "trace", "contentType": "application/zip", "path": "t.zip"}]}]}]}]}]}]}
    check("C4 the report's screenshots, per spec and test", shots(report), [("front-layout", "the-header-stays-on-one-line", "build/dx-shots/after/x/test-finished-1.png")])
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "build/dx-shots/after/x"))
        open(os.path.join(d, "build/dx-shots/after/x/test-finished-1.png"), "wb").write(b"\x89PNG")
        with open(os.path.join(d, "r.json"), "w") as fh:
            json.dump(report, fh)
        out = os.path.join(d, "out")
        check("C4 collect copies them under their label", collect(os.path.join(d, "r.json"), "after", out, d), ["after/front-layout/the-header-stays-on-one-line.png"])
        os.makedirs(os.path.join(out, "before", "front-layout"))
        open(os.path.join(out, "before", "front-layout", "the-header-stays-on-one-line.png"), "wb").write(b"\x89PNG")
        os.makedirs(os.path.join(out, "after", "admin"))
        open(os.path.join(out, "after", "admin", "a-new-screen.png"), "wb").write(b"\x89PNG")
        found = listed(out)
        text = section("DiluxOne/x", 12, found, "https://github.com/DiluxOne/x/actions/runs/9")
        check("C4 the section links the before and the after image of each test",
              "| `front-layout` · the-header-stays-on-one-line | ![before](https://github.com/DiluxOne/x/blob/dx-screenshots/pr-12/before/front-layout/the-header-stays-on-one-line.png?raw=true) | ![after](https://github.com/DiluxOne/x/blob/dx-screenshots/pr-12/after/front-layout/the-header-stays-on-one-line.png?raw=true) |" in text, True)
        check("C4 a new spec has no before", "| `admin` · a-new-screen | — | ![after](" in text, True)
        check("C4 it sits between its markers and links the run", (text.startswith(START), text.endswith(END), "[the run](https://github.com/DiluxOne/x/actions/runs/9)" in text), (True, True, True))
        calls = []

        def api(*args, data=None):
            calls.append((args, data))
            if args[0].endswith(f"/git/ref/heads/{BRANCH}"):
                raise RuntimeError("gh: Not Found (HTTP 404)")
            return {"sha": f"s{len(calls)}"}
        check("C4 the images are committed on the orphan branch, under pr-<n>/", push("DiluxOne/x", 12, out, api), 3)
        tree = next(d for a, d in calls if a[2:3] == ("repos/DiluxOne/x/git/trees",))
        check("C4 at pr-<n>/{before,after}/<spec>/<test>.png, with no base tree for a new branch",
              (sorted(e["path"] for e in tree["tree"]), "base_tree" in tree),
              (["pr-12/after/admin/a-new-screen.png", "pr-12/after/front-layout/the-header-stays-on-one-line.png", "pr-12/before/front-layout/the-header-stays-on-one-line.png"], False))
        check("C4 an orphan commit, then the branch created", (next(d for a, d in calls if a[2:3] == ("repos/DiluxOne/x/git/commits",))["parents"], calls[-1][0][2].endswith("/git/refs")), ([], True))
    tpl = open(os.path.join(HERE, "..", "pull_request_template.md"), encoding="utf-8").read()
    once = set_section(tpl, f"{START}\nx\n{END}")
    check("C4 the template's section is filled between its markers", (f"{HEADING}\n\n" in once and f"{START}\nx\n{END}" in once, once.count(START)), (True, 1))
    check("C4 a later run replaces it", set_section(once, f"{START}\ny\n{END}").count("y\n" + END), 1)
    body = "## 📝 What changes\n\nA.\n\n## 🧪 How I tested it\n\nB.\n\n🤖 AI-generated · Claude Opus 5.5 (Anthropic)\n"
    added = set_section(body, f"{START}\nz\n{END}")
    check("C4 a description with no section gets one, before its AI line", added.endswith(f"{HEADING}\n\n{START}\nz\n{END}\n\n🤖 AI-generated · Claude Opus 5.5 (Anthropic)\n"), True)
    check("C4 a run that failed says so and does not block", "does not block the merge" in section("o/r", 1, {"before": set(), "after": set()}, failed=True), True)
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    root = os.environ.get("DIR") or "."
    central = os.environ.get("CENTRAL") or os.path.dirname(HERE)
    if argv == ["plan"]:
        kind, conf = ways.config(root, central)
        p = plan(conf, [l.strip() for l in sys.stdin if l.strip()], root, central, kind)
        print(json.dumps(p))
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
                fh.write(f"specs={' '.join(p['specs'])}\n")
        return 0
    if argv == ["config"]:
        sys.stdout.write(config_text())
        return 0
    if len(argv) == 4 and argv[0] == "take":
        with open(argv[2], encoding="utf-8") as fh:
            print("\n".join(take(argv[1], json.load(fh), argv[3], root)))
        return 0
    if len(argv) == 4 and argv[0] == "collect":
        print("\n".join(collect(argv[1], argv[2], argv[3], root)))
        return 0
    if len(argv) == 2 and argv[0] == "publish":
        repo, number = os.environ["GITHUB_REPOSITORY"], int(os.environ["PR"])
        failed = os.environ.get("FAILED") == "true"
        n = 0 if failed else push(repo, number, argv[1])
        found = listed(argv[1]) if n else {"before": set(), "after": set()}
        text = section(repo, number, found, os.environ.get("RUN_URL", ""), failed)
        pr = gh(f"repos/{repo}/pulls/{number}")
        gh("-X", "PATCH", f"repos/{repo}/pulls/{number}", "--input", "-", data={"body": set_section(pr.get("body") or "", text)})
        print(f"#{number}: {n} screenshots, the section rewritten")
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
