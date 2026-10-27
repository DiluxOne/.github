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


def makefile(directory):
    """The text of DIR's Makefile, as make picks it, or None."""
    for name in MAKEFILES:
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
    return None


def has_target(text):
    """Whether a Makefile's text has a `pre-pr` rule."""
    return bool(text) and bool(TARGET_RE.search(text))


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
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
