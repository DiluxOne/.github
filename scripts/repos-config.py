#!/usr/bin/env python3
"""The organisation's configuration, repos.yml, held to its schema (#191).

`repos:` says what each repository is: its kinds of project, each a pack in
kinds/, over the paths it covers, with the roles of those paths. This
checks it, and the rest of repos.yml against it:

  - every kind has a pack in kinds/, every role is one of ROLES;
  - one repository's kinds never cover the same paths (a monorepo splits
    them), and a kind covers at least one path;
  - every repository another section names (projects, design-system,
    dependabot, repro, merge-queue, pre-pr, no-workflows) is listed in
    `repos:`, and a design system named exists in design-systems/ (or is
    `local`);
  - a repository's `pre-pr:` (#479) is `false`: it has no `make pre-pr`
    by design;
  - each repository's `repro:` (#377) is a `repro:` as its
    .github/review-policy.yml takes it, every way to the schema of
    scripts/repro-ways.py, or `false` (no way, by design);
  - no section of repos.yml is unknown.

  repos-config.py check          repos.yml here (exit 1, with the reasons)
  repos-config.py --test         self-test
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
ROLES = ("front", "back", "data", "infra", "docs")
SECTIONS = {"no-workflows", "exclude", "repos", "projects", "design-system", "settings", "security", "files", "dependabot", "callers", "repro", "merge-queue", "pre-pr"}
NAMED = ("projects", "design-system", "dependabot", "repro", "merge-queue", "pre-pr")


def load(path):
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def prefix(pattern):
    """The literal start of a path pattern, up to its first wildcard."""
    cut = min([i for i in (pattern.find("*"), pattern.find("?"), pattern.find("[")) if i >= 0] or [len(pattern)])
    return pattern[:cut]


def overlap(a, b):
    """Whether two path patterns may match the same file: one's literal
    start is the other's (a conservative test; "**" overlaps everything)."""
    def under(x, y):  # x within y, on a path segment's boundary
        return x.startswith(y) and (y == "" or y.endswith("/") or len(x) == len(y) or x[len(y)] == "/")
    pa, pb = prefix(a), prefix(b)
    return under(pa, pb) or under(pb, pa)


def problems(conf, kinds, systems):
    out = []
    for key in sorted(set(conf) - SECTIONS):
        out.append(f"{key}: not a section of repos.yml")
    repos = conf.get("repos")
    if not isinstance(repos, dict) or not repos:
        return out + ["repos: every repository of the organisation, with its kinds"]
    for name, entry in repos.items():
        if not isinstance(entry, dict) or set(entry) - {"kinds"} or not isinstance(entry.get("kinds"), list):
            out.append(f"repos.{name}: {{kinds: [...]}} (an empty list leaves it unclassified)")
            continue
        seen = []
        for i, k in enumerate(entry["kinds"]):
            where = f"repos.{name}.kinds[{i}]"
            if not isinstance(k, dict) or set(k) - {"kind", "paths", "roles"}:
                out.append(f"{where}: kind, paths and roles")
                continue
            if k.get("kind") not in kinds:
                out.append(f"{where}: kind {k.get('kind')!r} has no pack in kinds/")
            paths = k.get("paths")
            if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
                out.append(f"{where}: paths, a list of patterns (\"**\" for the whole repository)")
                paths = []
            roles = k.get("roles") or []
            if not isinstance(roles, list) or any(r not in ROLES for r in roles):
                out.append(f"{where}: roles are among {', '.join(ROLES)}")
            for p in paths:
                for other, q in seen:
                    if overlap(p, q):
                        out.append(f"{where}: {p!r} overlaps {q!r} of {other}; one path belongs to one kind")
            seen += [(k.get("kind"), p) for p in paths]
    for section in NAMED:
        for name in (conf.get(section) or {}):
            if name not in repos:
                out.append(f"{section}.{name}: not a repository of `repos:`")
    for name in conf.get("no-workflows") or []:
        if name not in repos:
            out.append(f"no-workflows: {name} is not a repository of `repos:`")
    for name, system in (conf.get("design-system") or {}).items():
        if system != "local" and system not in systems:
            out.append(f"design-system.{name}: {system!r} is not in design-systems/ (nor local)")
    for name, mode in (conf.get("merge-queue") or {}).items():
        if mode not in ("auto", "on", "off", True, False):
            out.append(f"merge-queue.{name}: {mode!r} is not auto, on or off")
    for name, entry in (conf.get("pre-pr") or {}).items():
        if entry is not False:
            out.append(f"pre-pr.{name}: {entry!r} is not false (a repository that has none by design)")
    for name, entry in (conf.get("repro") or {}).items():
        if entry is False:  # no way, by design
            continue
        if not isinstance(entry, dict) or set(entry) - {"ways", "affected"} or not isinstance(entry.get("ways"), dict) or not entry["ways"]:
            out.append(f"repro.{name}: {{ways: {{name: way}}}}, and `affected` if any, or false (none, by design)")
            continue
        off = [w for w, way in entry["ways"].items() if not isinstance(way, dict)]
        out += [f"repro.{name}: ways.{w}: a way's keys (to switch one off, a repository's own policy says false)" for w in off]
        ways = {w: way for w, way in entry["ways"].items() if isinstance(way, dict)}
        out += [f"repro.{name}: {p.removeprefix('repro.')}" for p in repro_ways().problems({"ways": ways})]
    return out


def repro_ways():
    import importlib.util
    spec = importlib.util.spec_from_file_location("repro_ways", os.path.join(HERE, "repro-ways.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def kind_of(conf, name):
    """The kind of a repository with exactly one, or None."""
    kinds = ((conf.get("repos") or {}).get(name) or {}).get("kinds") or []
    return kinds[0].get("kind") if len(kinds) == 1 else None


def dirs(path):
    return {d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))}


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    kinds, systems = {"wordpress-plugin", "web-api"}, {"wordpress-admin"}
    plugin = {"kinds": [{"kind": "wordpress-plugin", "paths": ["**"], "roles": ["back", "front"]}]}
    good = {"repos": {"a": plugin, "b": {"kinds": []}}, "projects": {"a": 1}, "design-system": {"a": "wordpress-admin", "b": "local"}}
    check("a configuration that holds", problems(good, kinds, systems), [])
    check("this repository's repos.yml holds", problems(load(os.path.join(ROOT, "repos.yml")), dirs(os.path.join(ROOT, "kinds")), dirs(os.path.join(ROOT, "design-systems"))), [])
    mono = {"repos": {"m": {"kinds": [{"kind": "web-api", "paths": ["api/**"], "roles": ["back"]},
                                      {"kind": "wordpress-plugin", "paths": ["plugin/**"], "roles": ["back", "front"]}]}}}
    check("a monorepo whose kinds split the paths", problems(mono, kinds, systems), [])
    clash = {"repos": {"m": {"kinds": [{"kind": "web-api", "paths": ["**"]}, {"kind": "wordpress-plugin", "paths": ["plugin/**"]}]}}}
    check("two kinds over the same paths", len(problems(clash, kinds, systems)), 1)
    check("a kind with no pack", problems({"repos": {"a": {"kinds": [{"kind": "rails", "paths": ["**"]}]}}}, kinds, systems), ["repos.a.kinds[0]: kind 'rails' has no pack in kinds/"])
    check("an unknown role", problems({"repos": {"a": {"kinds": [{"kind": "web-api", "paths": ["**"], "roles": ["mobile"]}]}}}, kinds, systems), [f"repos.a.kinds[0]: roles are among {', '.join(ROLES)}"])
    check("a kind with no paths", len(problems({"repos": {"a": {"kinds": [{"kind": "web-api", "paths": []}]}}}, kinds, systems)), 1)
    check("a section naming a repository repos: lacks", problems(dict(good, projects={"z": 3}), kinds, systems), ["projects.z: not a repository of `repos:`"])
    check("a design system that does not exist", problems(dict(good, **{"design-system": {"a": "material"}}), kinds, systems), ["design-system.a: 'material' is not in design-systems/ (nor local)"])
    check("an unknown section", problems(dict(good, owners={}), kinds, systems), ["owners: not a section of repos.yml"])
    check("#451 a repository's merge queue: auto, on or off", problems(dict(good, **{"merge-queue": {"a": "off", "b": "sometimes"}}), kinds, systems), ["merge-queue.b: 'sometimes' is not auto, on or off"])
    check("#479 a repository's pre-pr exception is false, and nothing else", problems(dict(good, **{"pre-pr": {"a": False, "b": True}}), kinds, systems), ["pre-pr.b: True is not false (a repository that has none by design)"])
    check("#479 a pre-pr exception of a repository repos: lacks", problems(dict(good, **{"pre-pr": {"z": False}}), kinds, systems), ["pre-pr.z: not a repository of `repos:`"])
    way = {"layer": "logic", "test": "tests/repro/test_issue_{n}.py", "run": "pytest {test}", "junit": "build/repro.xml"}
    check("#377 a repository's way to reproduce a bug", problems(dict(good, repro={"b": {"ways": {"pytest": way}}}), kinds, systems), [])
    check("#377 a way of a repository repos: lacks", problems(dict(good, repro={"z": {"ways": {"pytest": way}}}), kinds, systems), ["repro.z: not a repository of `repos:`"])
    check("#377 a way that is wrong says why", problems(dict(good, repro={"b": {"ways": {"pytest": dict(way, layer="screen")}}}), kinds, systems),
          ["repro.b: ways.pytest.layer: one of " + ", ".join(repro_ways().LAYERS) + ", or a list of them"])
    check("#377 an entry that is no `repro:`", problems(dict(good, repro={"b": {"pytest": way}}), kinds, systems), ["repro.b: {ways: {name: way}}, and `affected` if any, or false (none, by design)"])
    check("#377 a way that is not a mapping is said, never a crash", problems(dict(good, repro={"b": {"ways": {"unit": False}}}), kinds, systems),
          ["repro.b: ways.unit: a way's keys (to switch one off, a repository's own policy says false)"])
    check("#377 false: a repository with no way, by design", problems(dict(good, repro={"b": False}), kinds, systems), [])
    check("kind: a single-kind repository's", kind_of(good, "a"), "wordpress-plugin")
    check("kind: none for an unclassified one, a monorepo or an unknown name", (kind_of(good, "b"), kind_of(mono, "m"), kind_of(good, "zz")), (None, None, None))
    check("overlap: '**' overlaps everything; siblings do not", (overlap("**", "a/**"), overlap("api/**", "web/**"), overlap("api/**", "api/v2/*")), (True, False, True))
    check("overlap: on a segment's boundary, not a string's", (overlap("src/foo", "src/foobar/**"), overlap("src/foo", "src/foo/**")), (False, True))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    conf = load(os.path.join(ROOT, "repos.yml"))
    if argv == ["check"]:
        found = problems(conf, dirs(os.path.join(ROOT, "kinds")), dirs(os.path.join(ROOT, "design-systems")))
        for line in found:
            print(line)
        return 1 if found else 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
