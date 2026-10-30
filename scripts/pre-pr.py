#!/usr/bin/env python3
"""`make pre-pr`: the one check before a pull request, in every repository (#479).

Whatever the stack, a repository's Makefile has a `pre-pr` target that runs,
one after the other and stopping at the first failure, every check its pull
request and its merge queue run. It starts and stops what it needs (a
plugin's wp-env sites, say) and relies on nothing started before it. The
person, the agent and the autopilot run the same command before a pull
request (`dx check` runs it, then the local review), so what the queue finds
was found first on the branch.

What it must cover is data: a kind's pack says it (kinds/<kind>/pack.yml
`pre-pr`), and a repository with no kind says it in its own
.github/review-policy.yml (`pre-pr`, a list of what its target runs).

  pre-pr.py has [DIR]          exit 0 when DIR's Makefile (Makefile,
                               makefile or GNUmakefile; DIR defaults to .)
                               has a `pre-pr` target, 1 when not, saying so
  pre-pr.py covers [DIR]       what DIR's `pre-pr` must cover, one per line:
                               its kind's pack (`kind:` in its
                               .github/review-policy.yml), else that
                               policy's own `pre-pr`
  pre-pr.py required NAME      `required`, `optional` or `exempt`: org.yml
                               `pre-pr` (optional when unset) and repos.yml
                               `pre-pr` (NAME: false, a repository that has
                               none by design)
  pre-pr.py check NAME [DIR]   for the conventions check: exit 1 when NAME
                               must have one (`required`) and DIR has none
  pre-pr.py render KIND        the dx.mk of a repository of KIND, from its
                               pack's `pre-pr-make` (nothing, exit 1, when
                               the pack has none)
  pre-pr.py --test             self-test
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CENTRAL = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
import policy  # noqa: E402  the YAML reader and the packs (scripts/policy.py)

MAKEFILES = ("GNUmakefile", "makefile", "Makefile")
# A rule naming `pre-pr` among its targets: `pre-pr:`, `pre-pr check:`,
# `pre-pr: lint test`; not a variable (`pre-pr := x`, `pre-pr ?= x`).
TARGET_RE = re.compile(r"^(?:[^\s:#=]+[ \t]+)*pre-pr(?:[ \t]+[^\s:#=]+)*[ \t]*::?(?!=)", re.M)
CONTRACT = ("`make pre-pr` is the one check before a pull request (DiluxOne/.github#479, kinds/README.md `pre-pr`): "
            "every check the pull request and the merge queue run, one after the other, starting what it needs")


# The managed fragment (#479): `sync-repos.py pre-pr` writes it from the
# pack and the repository's Makefile includes it, so the organisation owns
# `pre-pr` and the repository's own targets stay its own.
FRAGMENT = "dx.mk"
INCLUDE = f"include {FRAGMENT}"
INCLUDE_RE = re.compile(r"^-?include[ \t]+(?:\S+[ \t]+)*dx\.mk[ \t]*$", re.M)


def render(make):
    """The dx.mk text for a pack's `pre-pr-make` ({run: [...], finally:
    [...]}), or None when it has no `run`. The lines run as one bash script,
    stopping at the first failure; `finally` after it either way, keeping
    the exit code of `run`. Make expands `$`, so each one is doubled; the
    script travels in an exported variable, never on the command line."""
    make = make if isinstance(make, dict) else {}
    run = [str(x) for x in make.get("run") or []]
    if not run:
        return None
    after = [str(x) for x in make.get("finally") or []]
    body = []
    if after:
        body += ["dx_finally() {", "  rc=$?"] + [f"  {line} || true" for line in after] + ["  exit $rc", "}", "trap dx_finally EXIT"]
    body += run
    esc = [line.replace("$", "$$") for line in body]
    return ("# Managed by DiluxOne/.github (scripts/sync-repos.py pre-pr, #479), from its kind's pack\n"
            "# (kinds/<kind>/pack.yml `pre-pr-make`): do not edit it here, it is rewritten.\n"
            "# `make pre-pr` is the one check before a pull request. This repository's\n"
            "# Makefile includes it, and adds its own checks as prerequisites:\n"
            "#   pre-pr: my-check\n"
            ".PHONY: pre-pr\n"
            "define DX_PRE_PR\n" + "\n".join(esc) + "\nendef\n"
            "export DX_PRE_PR\n"
            "pre-pr:\n"
            "\t@bash -euo pipefail -c \"$$DX_PRE_PR\"\n")


def render_kind(kind):
    """render() for a kind's pack; None for no kind, no pack or no steps."""
    if not kind or not os.path.isfile(policy.pack_path(str(kind))):
        return None
    return render(policy.load_yaml(policy.pack_path(str(kind))).get("pre-pr-make"))


def with_include(text):
    """A Makefile's text (None for none) that includes dx.mk: unchanged when
    it does, the include first otherwise, so its own rules come after."""
    if text and INCLUDE_RE.search(text):
        return text
    return INCLUDE + "\n" + (("\n" + text) if text else "")


def own_recipe(text):
    """Whether a Makefile's own `pre-pr` rule has a recipe (a tab line after
    it, or one after `;`): including dx.mk then would give make two recipes,
    the repository's winning, so it waits until that one is a prerequisite."""
    if not text or INCLUDE_RE.search(text):
        return False
    for m in TARGET_RE.finditer(text):
        rest = text[m.end():].split("\n", 2)
        if ";" in rest[0].split("#", 1)[0] or (len(rest) > 1 and rest[1].startswith("\t")):
            return True
    return False


def wanted(kind, have_fragment, have_makefile, name="Makefile"):
    """The files a repository of KIND needs for its `make pre-pr`, {path:
    text}, given its dx.mk and its Makefile (text, None for none; `name` the
    one make picks). Empty for a kind with no `pre-pr-make`, or one in step."""
    fragment = render_kind(kind)
    if fragment is None:
        return {}
    out = {}
    if have_fragment != fragment:
        out[FRAGMENT] = fragment
    if with_include(have_makefile) != have_makefile and not own_recipe(have_makefile):
        out[name] = with_include(have_makefile)
    return out


def makefile(directory):
    """The text of DIR's Makefile, as make picks it, or None."""
    for name in MAKEFILES:
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
    return None


def has_target(text):
    """Whether a Makefile's text has a `pre-pr` rule, its own or the one of
    the dx.mk it includes (whether that one is in step is the drift check's)."""
    return bool(text) and bool(TARGET_RE.search(text) or INCLUDE_RE.search(text))


def covers(directory):
    """What DIR's `pre-pr` must cover: the pack's list for its kind, else its
    policy's own `pre-pr`; [] when it says nothing."""
    own = policy.load_yaml(os.path.join(directory, ".github", "review-policy.yml"))
    own = own if isinstance(own, dict) else {}
    kind = own.get("kind")
    if kind:
        pack = policy.load_yaml(policy.pack_path(str(kind)))
        return [str(x) for x in (pack.get("pre-pr") or [])]
    return [str(x) for x in (own.get("pre-pr") or [])]


def required(name, org_conf, repos_conf):
    """`required`, `optional` or `exempt` for repository NAME."""
    if ((repos_conf or {}).get("pre-pr") or {}).get(name) is False:
        return "exempt"
    mode = (org_conf or {}).get("pre-pr")
    mode = "optional" if mode in (None, "") else str(mode)
    if mode not in ("required", "optional"):
        raise ValueError(f"org.yml `pre-pr` is `{mode}`: required or optional")
    return mode


def confs():
    return policy.load_yaml(os.path.join(CENTRAL, "org.yml")), policy.load_yaml(os.path.join(CENTRAL, "repos.yml"))


def self_test():
    fails = []

    def check(name, got, want):
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        if got != want:
            fails.append(name)

    check("a pre-pr rule is a target", has_target("check:\n\tx\npre-pr: ## all\n\t$(MAKE) check\n"), True)
    check("a rule with more targets names it", (has_target("pre-pr check:\n"), has_target("all pre-pr: lint\n")), (True, True))
    check("a double-colon rule is one", has_target("pre-pr::\n"), True)
    check("a variable is not", (has_target("pre-pr := x\n"), has_target("pre-pr ?= x\n"), has_target("pre-pr = x\n")), (False, False, False))
    check("another target is not", (has_target("pre-pr-lite:\n"), has_target("check:\n\t$(MAKE) pre-pr\n"), has_target("# pre-pr: soon\n")), (False, False, False))
    check("no Makefile is none", has_target(None), False)
    check("C1 a Makefile that includes dx.mk has the organisation's", (has_target("include dx.mk\n"), has_target("-include dx.mk\n"), has_target("include other.mk\n")), (True, True, False))
    check("an exception by design is exempt", required("a", {"pre-pr": "required"}, {"pre-pr": {"a": False}}), "exempt")
    check("org.yml decides the others", (required("b", {"pre-pr": "required"}, {"pre-pr": {"a": False}}), required("b", {"pre-pr": "optional"}, {})), ("required", "optional"))
    check("unset is optional", required("b", {}, {}), "optional")
    try:
        required("b", {"pre-pr": "maybe"}, {})
        check("a mode that is neither fails", "passed", "raised")
    except ValueError:
        check("a mode that is neither fails", "raised", "raised")
    org_conf, repos_conf = confs()
    check("org.yml's own value is one of the two", required("x-not-listed", org_conf, repos_conf) in ("required", "optional"), True)
    pack = policy.load_yaml(policy.pack_path("wordpress-plugin"))
    items = [str(x) for x in pack.get("pre-pr") or []]
    for what in ("lint", "analysis", "unit", "translations", "Plugin Check", "integration", "E2E", "review rules"):
        check(f"the wordpress-plugin pack's pre-pr covers {what}", any(what.lower() in i.lower() for i in items), True)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, ".github"))
        check("a directory with no Makefile has none", has_target(makefile(d)), False)
        with open(os.path.join(d, "Makefile"), "w") as fh:
            fh.write(".PHONY: pre-pr\npre-pr:\n\tnpm test\n")
        check("a Makefile's target is found", has_target(makefile(d)), True)
        with open(os.path.join(d, ".github", "review-policy.yml"), "w") as fh:
            fh.write("pre-pr:\n  - npm test\n  - npx playwright test\n")
        check("a repository with no kind says what it covers in its policy", covers(d), ["npm test", "npx playwright test"])
        with open(os.path.join(d, ".github", "review-policy.yml"), "w") as fh:
            fh.write("kind: wordpress-plugin\npre-pr: [ignored]\n")
        check("a kind's repository covers its pack's list", covers(d), items)
    # #479 C1: the pack's steps, written into dx.mk, are what `make pre-pr` runs.
    import subprocess
    import shutil
    frag = render_kind("wordpress-plugin")
    check("C1 the wordpress-plugin pack renders a dx.mk with a pre-pr target", has_target(frag), True)
    for step in ("composer lint", "composer stan", "composer test:unit", "phpunit-integration.xml", "e2e-run.sh", "repro-ways.py\" affected", "review-rules.php"):
        check(f"C1 its pre-pr runs {step}", step.replace("$", "$$") in (frag or ""), True)
    check("C1 a kind with no pack, or no kind, gets none", (render_kind("no-such-kind"), render_kind(None), render({})), (None, None, None))
    check("C1 a Makefile without the include gets it first, its own rules kept", with_include("check:\n\ttrue\n"), "include dx.mk\n\ncheck:\n\ttrue\n")
    check("C1 one that includes it is unchanged, as is -include", (with_include("x:\ninclude dx.mk\n"), with_include("-include dx.mk\n")), ("x:\ninclude dx.mk\n", "-include dx.mk\n"))
    check("C1 no Makefile gets one that includes it", with_include(None), "include dx.mk\n")
    check("C1 a repository of the kind gets dx.mk and the include", sorted(wanted("wordpress-plugin", None, None)), ["Makefile", "dx.mk"])
    check("C1 one in step needs nothing", wanted("wordpress-plugin", frag, "include dx.mk\n"), {})
    check("C1 a Makefile with its own pre-pr recipe gets dx.mk, not the include (two recipes)",
          (own_recipe("pre-pr:\n\tnpm test\n"), own_recipe("pre-pr: ; npm test\n"), own_recipe("pre-pr: lint test\nlint:\n\tx\n"), sorted(wanted("wordpress-plugin", None, "pre-pr:\n\tnpm test\n"))),
          (True, True, False, ["dx.mk"]))
    check("C1 a repository of no kind gets nothing", (wanted(None, None, None), wanted("no-such-kind", None, None)), ({}, {}))
    if shutil.which("make") and shutil.which("bash"):
        with tempfile.TemporaryDirectory() as d:
            mk = render({"run": ["x=${PWD##*/}", "echo \"run $x\" >> log", "test ! -f broken"], "finally": ["echo finally >> log"]})
            with open(os.path.join(d, FRAGMENT), "w") as fh:
                fh.write(mk)
            with open(os.path.join(d, "Makefile"), "w") as fh:
                fh.write(with_include("own:\n\t@echo own >> log\npre-pr: own\n"))
            ok = subprocess.run(["make", "-s", "pre-pr"], cwd=d, capture_output=True, text=True)
            log = open(os.path.join(d, "log")).read().split("\n")
            check("C1 make pre-pr runs the repository's own prerequisite, the steps as one script (variables kept, $ intact), then finally",
                  (ok.returncode, log[:3]), (0, ["own", "run " + os.path.basename(d), "finally"]))
            open(os.path.join(d, "broken"), "w").close()
            os.remove(os.path.join(d, "log"))
            bad = subprocess.run(["make", "-s", "pre-pr"], cwd=d, capture_output=True, text=True)
            check("C1 a failing step fails make pre-pr, and finally still runs", (bad.returncode != 0, "finally" in open(os.path.join(d, "log")).read()), (True, True))
    print("all tests passed" if not fails else f"{len(fails)} failed")
    return 1 if fails else 0


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    if argv[:1] == ["has"] and len(argv) <= 2:
        directory = argv[1] if len(argv) == 2 else "."
        if has_target(makefile(directory)):
            return 0
        print(f"No `pre-pr` target in {os.path.join(directory, 'Makefile')}. {CONTRACT}.", file=sys.stderr)
        return 1
    if argv[:1] == ["covers"] and len(argv) <= 2:
        print("\n".join(covers(argv[1] if len(argv) == 2 else ".")))
        return 0
    if argv[:1] == ["required"] and len(argv) == 2:
        print(required(argv[1], *confs()))
        return 0
    if argv[:1] == ["check"] and len(argv) in (2, 3):
        directory = argv[2] if len(argv) == 3 else "."
        mode = required(argv[1], *confs())
        if mode != "required" or has_target(makefile(directory)):
            return 0
        print(f"::error::{argv[1]} has no `pre-pr` target in its Makefile. {CONTRACT}. "
              "A repository that has none by design is listed in DiluxOne/.github repos.yml `pre-pr`.")
        return 1
    if argv[:1] == ["render"] and len(argv) == 2:
        text = render_kind(argv[1])
        if text is None:
            print(f"The {argv[1]} kind's pack has no `pre-pr-make`.", file=sys.stderr)
            return 1
        sys.stdout.write(text)
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
