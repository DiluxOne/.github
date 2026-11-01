#!/usr/bin/env python3
"""The organisation's configuration, repos.yml, held to its schema (#191).

`repos:` holds one entry per repository with everything the organisation
says of it (#562, scripts/repos_conf.py): its kinds of project, each a pack
in kinds/, over the paths it covers, with the roles of those paths, and its
`project`, `design-system`, `repro`, `merge-queue`, `pre-pr`, `who-decides`,
`dependabot` and `callers`. This checks it, and the rest of repos.yml against it:

  - every kind has a pack in kinds/, every role is one of ROLES;
  - one repository's kinds never cover the same paths (a monorepo splits
    them), and a kind covers at least one path;
  - an entry holds only those attributes: `project` a Project's number,
    `design-system` one of design-systems/ (or `local`), `merge-queue`
    auto, on or off, `pre-pr` `false` (no `make pre-pr` by design, #479),
    `who-decides` codeowners, acceptor or writers (#588),
    `repro` (#377) a `repro:` as its .github/review-policy.yml takes it,
    every way to the schema of scripts/repro-ways.py, or `false` (no way,
    by design), `dependabot` a map of ecosystems, `callers` a map of its
    callers' inputs to their values;
  - the top-level maps keyed by repository that came before it (projects,
    design-system, repro, merge-queue, pre-pr, dependabot) are refused;
  - every repository `no-workflows` names is listed in `repos:`;
  - no section of repos.yml is unknown.

  repos-config.py check          repos.yml here (exit 1, with the reasons)
  repos-config.py --test         self-test
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import repos_conf  # noqa: E402  the loader every reader goes through (#562)
ROOT = os.path.join(HERE, "..")
ROLES = ("front", "back", "data", "infra", "docs")
SECTIONS = {"no-workflows", "exclude", "repos", "settings", "security", "files", "callers"}
# The top-level maps keyed by repository before #562: each is now an
# attribute of the repository's entry.
LEGACY = {"projects": "project", "design-system": "design-system", "dependabot": "dependabot", "repro": "repro",
          "merge-queue": "merge-queue", "pre-pr": "pre-pr"}
# Who decides (#588, scripts/deciders.py): a repository's exception.
WHO_DECIDES = ("codeowners", "acceptor", "writers")
ATTRIBUTES = {"kinds", "project", "design-system", "repro", "merge-queue", "pre-pr", "who-decides", "dependabot", "callers"}


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
        if key in LEGACY:
            out.append(f"{key}: a map keyed by repository is no longer read: each repository's `{LEGACY[key]}` is in its entry of `repos:` (#562)")
        else:
            out.append(f"{key}: not a section of repos.yml")
    repos = conf.get("repos")
    if not isinstance(repos, dict) or not repos:
        return out + ["repos: every repository of the organisation, with its kinds"]
    for name, entry in repos.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("kinds"), list):
            out.append(f"repos.{name}: {{kinds: [...]}} (an empty list leaves it unclassified)")
            continue
        for key in sorted(set(entry) - ATTRIBUTES):
            out.append(f"repos.{name}.{key}: not an attribute of a repository ({', '.join(sorted(ATTRIBUTES))})")
        out += attribute_problems(name, entry, systems)
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
    for name in conf.get("no-workflows") or []:
        if name not in repos:
            out.append(f"no-workflows: {name} is not a repository of `repos:`")
    defaults = (conf.get("callers") or {}).get("defaults") if isinstance(conf.get("callers"), dict) else None
    if defaults is not None and (not isinstance(defaults, dict) or not all(isinstance(v, (str, bool, int)) for v in defaults.values())):
        out.append("callers.defaults: a map of an input to its value")
    return out


def attribute_problems(name, entry, systems):
    """What is wrong with one entry's attributes beside its kinds."""
    out, where = [], f"repos.{name}"
    if "project" in entry and (not isinstance(entry["project"], int) or isinstance(entry["project"], bool) or entry["project"] <= 0):
        out.append(f"{where}.project: {entry['project']!r} is not a Project's number")
    system = entry.get("design-system")
    if system is not None and system != "local" and system not in systems:
        out.append(f"{where}.design-system: {system!r} is not in design-systems/ (nor local)")
    if "merge-queue" in entry and entry["merge-queue"] not in ("auto", "on", "off", True, False):
        out.append(f"{where}.merge-queue: {entry['merge-queue']!r} is not auto, on or off")
    if "pre-pr" in entry and entry["pre-pr"] is not False:
        out.append(f"{where}.pre-pr: {entry['pre-pr']!r} is not false (a repository that has none by design)")
    if "who-decides" in entry and entry["who-decides"] not in WHO_DECIDES:
        out.append(f"{where}.who-decides: {entry['who-decides']!r} is not {', '.join(WHO_DECIDES)}")
    if "dependabot" in entry and not isinstance(entry["dependabot"], dict):
        out.append(f"{where}.dependabot: a map of ecosystem to what it adds")
    if "callers" in entry and (not isinstance(entry["callers"], dict) or not all(isinstance(v, (str, bool, int)) for v in entry["callers"].values())):
        out.append(f"{where}.callers: a map of an input to its value")
    repro = entry.get("repro", False)
    if repro is False:  # none set, or no way by design
        return out
    if not isinstance(repro, dict) or set(repro) - {"ways", "affected"} or not isinstance(repro.get("ways"), dict) or not repro["ways"]:
        return out + [f"{where}.repro: {{ways: {{name: way}}}}, and `affected` if any, or false (none, by design)"]
    off = [w for w, way in repro["ways"].items() if not isinstance(way, dict)]
    out += [f"{where}.repro: ways.{w}: a way's keys (to switch one off, a repository's own policy says false)" for w in off]
    ways = {w: way for w, way in repro["ways"].items() if isinstance(way, dict)}
    return out + [f"{where}.repro: {p.removeprefix('repro.')}" for p in repro_ways().problems({"ways": ways})]


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
    good = {"repos": {"a": dict(plugin, project=1, **{"design-system": "wordpress-admin"}), "b": {"kinds": [], "design-system": "local"}}}

    def with_b(**attrs):
        return {"repos": {"a": good["repos"]["a"], "b": dict(good["repos"]["b"], **attrs)}}
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
    check("#562 an attribute an entry does not hold", problems(with_b(owner="me"), kinds, systems),
          [f"repos.b.owner: not an attribute of a repository ({', '.join(sorted(ATTRIBUTES))})"])
    check("#562 every top-level map keyed by repository is refused, saying where it went",
          [p.split(":")[0] for p in problems(dict(good, projects={"a": 1}, repro={"b": False}, **{"pre-pr": {}, "merge-queue": {}, "design-system": {}, "dependabot": {}}), kinds, systems)],
          ["dependabot", "design-system", "merge-queue", "pre-pr", "projects", "repro"])
    check("#562 a Project is a number", problems(with_b(project="two"), kinds, systems), ["repos.b.project: 'two' is not a Project's number"])
    check("#562 the callers' values are a map of input to value, and so are the defaults",
          (problems(with_b(callers={"slug": "b"}), kinds, systems), problems(with_b(callers=["slug"]), kinds, systems), problems(dict(good, callers={"defaults": {"dry-run": False}}), kinds, systems)),
          ([], ["repos.b.callers: a map of an input to its value"], []))
    check("a design system that does not exist", problems(with_b(**{"design-system": "material"}), kinds, systems), ["repos.b.design-system: 'material' is not in design-systems/ (nor local)"])
    check("an unknown section", problems(dict(good, owners={}), kinds, systems), ["owners: not a section of repos.yml"])
    check("#451 a repository's merge queue: auto, on or off", (problems(with_b(**{"merge-queue": "off"}), kinds, systems), problems(with_b(**{"merge-queue": "sometimes"}), kinds, systems)),
          ([], ["repos.b.merge-queue: 'sometimes' is not auto, on or off"]))
    check("C2 (#588) a repository's who-decides: codeowners, acceptor or writers", (problems(with_b(**{"who-decides": "writers"}), kinds, systems), problems(with_b(**{"who-decides": "anyone"}), kinds, systems)),
          ([], ["repos.b.who-decides: 'anyone' is not codeowners, acceptor, writers"]))
    check("#479 a repository's pre-pr exception is false, and nothing else", (problems(with_b(**{"pre-pr": False}), kinds, systems), problems(with_b(**{"pre-pr": True}), kinds, systems)),
          ([], ["repos.b.pre-pr: True is not false (a repository that has none by design)"]))
    way = {"layer": "logic", "test": "tests/repro/test_issue_{n}.py", "run": "pytest {test}", "junit": "build/repro.xml"}
    check("#377 a repository's way to reproduce a bug", problems(with_b(repro={"ways": {"pytest": way}}), kinds, systems), [])
    check("#377 a way that is wrong says why", problems(with_b(repro={"ways": {"pytest": dict(way, layer="screen")}}), kinds, systems),
          ["repos.b.repro: ways.pytest.layer: one of " + ", ".join(repro_ways().LAYERS) + ", or a list of them"])
    check("#377 an entry that is no `repro:`", problems(with_b(repro={"pytest": way}), kinds, systems), ["repos.b.repro: {ways: {name: way}}, and `affected` if any, or false (none, by design)"])
    check("#377 a way that is not a mapping is said, never a crash", problems(with_b(repro={"ways": {"unit": False}}), kinds, systems),
          ["repos.b.repro: ways.unit: a way's keys (to switch one off, a repository's own policy says false)"])
    check("#377 false: a repository with no way, by design", problems(with_b(repro=False), kinds, systems), [])
    check("no-workflows names a repository of `repos:`", problems(dict(good, **{"no-workflows": ["z"]}), kinds, systems), ["no-workflows: z is not a repository of `repos:`"])
    check("kind: a single-kind repository's", kind_of(good, "a"), "wordpress-plugin")
    check("kind: none for an unclassified one, a monorepo or an unknown name", (kind_of(good, "b"), kind_of(mono, "m"), kind_of(good, "zz")), (None, None, None))
    check("overlap: '**' overlaps everything; siblings do not", (overlap("**", "a/**"), overlap("api/**", "web/**"), overlap("api/**", "api/v2/*")), (True, False, True))
    check("overlap: on a segment's boundary, not a string's", (overlap("src/foo", "src/foobar/**"), overlap("src/foo", "src/foo/**")), (False, True))
    repos_conf.self_test(check)
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
