#!/usr/bin/env python3
"""A security patch on the version in production, after a veto window (#247).

security-fix.yml writes an advisory's fix in the private repository and
records it on the claim's issue there ("Fix <GHSA> in <repository>"). Once
the advisory is a draft (a maintainer or the triage moved it) and the fix's
checks passed, security-patch.yml takes it through these stages, each one a
label on that issue, read and written by dilux-bot only:

  (none)          start: the fix is applied on the version in production
                  (scripts/production-version.py), with a changelog entry and
                  the markers of the patch, and the repository's checks run;
                  green, the maintainer is told when it publishes, and the
                  issue gets `patch:window` and the time in its marker
  patch:window    publish, once the window is over and nobody added
                  `patch:hold`: the same tree is built again and pushed to
                  security/X.Y.Z in the public repository, whose release
                  workflow releases it (plugin-release-wp.yml); `patch:pushed`
  patch:pushed    finish, once that release exists: the advisory is
                  published with the patched version, an issue in the public
                  repository carries the fix into its default branch, and
                  the claim's issue closes; `patch:released`
  patch:hold      a maintainer stopped it; nothing moves until they remove it
  patch:failed    the fix did not apply or its checks failed on the version
                  in production; a maintainer takes it from there

The window is `security-patch.veto-hours` in policy/autonomy.yml (6 unless
the organisation says otherwise). It runs here, in private, before anything
is public: the fix leaves this repository only when the window is over.

  security-patch.py stage    LABELS (comma-separated), MARKER (the issue's
                             patch marker or empty), NOW (ISO time): prints
                             start|publish|finish|wait|none and why
  security-patch.py hours    the veto window in hours, from the policy
  security-patch.py marker   VERSION, DUE: the marker line
  security-patch.py entry    README, VERSION_TEXT: the readme with a held
                             changelog entry for the patch on top
  security-patch.py release  ROOT (the public repository's checkout),
                             VERSION: its kind's release command for that
                             version and its caller's slug, as JSON
                             {kind, slug, argv}
  security-patch.py --test
"""
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = re.compile(r"<!-- dx-security-patch: version=(\d+\.\d+\.\d+) due=(\S+) -->")
STAGES = ("patch:window", "patch:pushed", "patch:released", "patch:hold", "patch:failed")
DEFAULT_HOURS = 6


def hours(policy):
    """The veto window, in hours: a positive number, else the default."""
    v = ((policy or {}).get("security-patch") or {}).get("veto-hours", DEFAULT_HOURS)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return DEFAULT_HOURS
    return v if 0 < v <= 24 * 30 else DEFAULT_HOURS


def marker(version, due):
    return f"<!-- dx-security-patch: version={version} due={due} -->"


def parse(text):
    m = MARK.search(text or "")
    return {"version": m.group(1), "due": m.group(2)} if m else None


def when(iso):
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))


def stage(labels, mark, now):
    """(act, why) for one claim issue whose fix is recorded and whose
    advisory is a draft (the caller checks both)."""
    labels = set(labels)
    if "patch:hold" in labels:
        return "wait", "a maintainer holds it (patch:hold)"
    if "patch:failed" in labels or "patch:released" in labels:
        return "none", "done" if "patch:released" in labels else "it failed; a maintainer takes it"
    if "patch:pushed" in labels:
        return "finish", "pushed; finish once its release exists"
    if "patch:window" in labels:
        m = parse(mark)
        if not m:
            return "wait", "in the window, but its marker is missing: a maintainer looks"
        if when(now) < when(m["due"]):
            return "wait", f"the window closes at {m['due']}"
        return "publish", f"the window closed at {m['due']}"
    return "start", "a recorded fix on a draft advisory"


def entry(readme, text):
    """The readme with a held entry for the patch on top of its changelog:
    `= Unreleased =`, the line `Unreleased.` and one note. release-markers.sh
    prepare then names it and stamps the markers."""
    lines = readme.split("\n")
    try:
        i = next(k for k, l in enumerate(lines) if l.strip() == "== Changelog ==")
    except StopIteration:
        raise ValueError("the readme has no == Changelog == section")
    note = re.sub(r"\s+", " ", text).strip()[:300] or "Security fix."
    block = ["", "= Unreleased =", "", "Unreleased.", f"* Security: {note}"]
    j = i + 1
    return "\n".join(lines[:j] + block + lines[j:])


def _release_issue():
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_issue", os.path.join(HERE, "release-issue.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def release(root, version):
    """The kind's `prepare` command for VERSION, filled from the
    repository's own release caller (scripts/release-issue.py), and its
    slug: the same command the release pull request runs."""
    ri = _release_issue()
    kind = ri.kind_of(root)
    rel = ri.pack_release(os.path.join(HERE, ".."), kind)
    if not rel:
        raise ValueError(f"the kind {kind or '(none)'} publishes nothing: no security patch")
    inputs = ri.caller_inputs(root, rel["workflow"]) or {}
    if not inputs.get("slug"):
        raise ValueError(f"no job calls {rel['workflow']} with a slug")
    return {"kind": kind, "slug": inputs["slug"], "argv": ri.prepare_argv(rel, inputs, version, os.path.join(HERE, ".."))}


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    check("hours: the default is 6", hours({}), 6)
    check("hours: the policy sets it", hours({"security-patch": {"veto-hours": 2}}), 2)
    check("hours: nonsense or none reads as the default", [hours({"security-patch": {"veto-hours": v}}) for v in (0, -1, "x", None, 10**6)], [6] * 5)
    m = marker("2.1.1", "2026-10-18T06:00:00Z")
    check("marker: reads back", parse("text\n" + m), {"version": "2.1.1", "due": "2026-10-18T06:00:00Z"})
    check("stage: nothing yet starts", stage([], "", "2026-10-18T00:00:00Z")[0], "start")
    check("stage: in the window it waits", stage(["patch:window"], m, "2026-10-18T05:59:00Z")[0], "wait")
    check("stage: past the window it publishes", stage(["patch:window"], m, "2026-10-18T06:00:00Z")[0], "publish")
    check("stage: a hold stops every stage", [stage(["patch:hold", s], m, "2030-01-01T00:00:00Z")[0] for s in ("patch:window", "patch:pushed", "")], ["wait"] * 3)
    check("stage: pushed finishes", stage(["patch:pushed"], m, "2030-01-01T00:00:00Z")[0], "finish")
    check("stage: released or failed does nothing", [stage([s], m, "2030-01-01T00:00:00Z")[0] for s in ("patch:released", "patch:failed")], ["none", "none"])
    check("stage: a window without its marker waits for a person", stage(["patch:window"], "", "2030-01-01T00:00:00Z")[0], "wait")
    readme = "=== X ===\nStable tag: 2.1.0\n\n== Changelog ==\n\n= 2.1.0 =\n\n* Old.\n"
    got = entry(readme, "Escape the title  in the list.\nMore")
    check("entry: a held entry on top of the changelog, the old one kept",
          (got.index("= Unreleased =") < got.index("= 2.1.0 ="), "\nUnreleased.\n" in got, "* Security: Escape the title in the list. More" in got, got.endswith("* Old.\n")), (True, True, True, True))
    try:
        entry("no changelog", "x")
        check("entry: a readme without a changelog fails", "no error", "an error")
    except ValueError:
        check("entry: a readme without a changelog fails", True, True)
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, ".github", "workflows"))
        open(os.path.join(root, ".github", "review-policy.yml"), "w").write("kind: wordpress-plugin\n")
        open(os.path.join(root, ".github", "workflows", "release.yml"), "w").write(
            "jobs:\n  release:\n    uses: DiluxOne/.github/.github/workflows/plugin-release-wp.yml@v5\n    with:\n      slug: diluxone-x\n      version-constant: DX_VERSION\n")
        r = release(root, "2.1.1")
        check("release: the kind, the caller's slug and the release command for the version",
              (r["kind"], r["slug"], "release-markers.sh" in r["argv"][1], "2.1.1" in r["argv"], "diluxone-x.php" in r["argv"], "DX_VERSION" in r["argv"]),
              ("wordpress-plugin", "diluxone-x", True, True, True, True))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv == ["stage"]:
        labels = [l for l in os.environ.get("LABELS", "").split(",") if l]
        act, why = stage(labels, os.environ.get("MARKER", ""), os.environ["NOW"])
        print(json.dumps({"act": act, "why": why}))
        return 0
    if argv == ["hours"]:
        import yaml
        with open(os.path.join(HERE, "..", "policy", "autonomy.yml"), encoding="utf-8") as fh:
            print(hours(yaml.safe_load(fh)))
        return 0
    if argv == ["marker"]:
        print(marker(os.environ["VERSION"], os.environ["DUE"]))
        return 0
    if argv == ["entry"]:
        with open(os.environ["README"], encoding="utf-8") as fh:
            text = entry(fh.read(), os.environ.get("VERSION_TEXT", ""))
        with open(os.environ["README"], "w", encoding="utf-8") as fh:
            fh.write(text)
        return 0
    if argv == ["release"]:
        print(json.dumps(release(os.environ["ROOT"], os.environ["VERSION"])))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
