"""repos.yml's one entry per repository (#562), read the same way everywhere.

Each repository of `repos:` holds everything the organisation says of it:
`kinds`, `project` (its public Project's number), `design-system`, `repro`,
`merge-queue`, `pre-pr`, `dependabot` and `callers` (the values of its
callers' inputs, over `callers: defaults`). `entry(conf, name)` is that
entry; `value(conf, name, key)` one attribute of it. A repos.yml of the
older shape, with a top-level map per attribute keyed by repository (an
organisation's own repos.yml laid over this one, scripts/config-overlay.sh,
may still be one), is read too, the entry winning; `repos-config.py check`
refuses that shape here.
"""

# The attributes an entry holds, beside `kinds`; each was a top-level map
# keyed by repository before #562 (`project` was `projects`).
ATTRIBUTES = ("project", "design-system", "repro", "merge-queue", "pre-pr", "dependabot", "callers")
LEGACY = {"project": "projects", "design-system": "design-system", "repro": "repro",
          "merge-queue": "merge-queue", "pre-pr": "pre-pr", "dependabot": "dependabot"}


def entry(conf, name):
    """Repository NAME's entry in repos.yml, {} when it has none."""
    conf = conf if isinstance(conf, dict) else {}
    repos = conf.get("repos") if isinstance(conf.get("repos"), dict) else {}
    own = repos.get(name) if isinstance(repos.get(name), dict) else {}
    out = {}
    for key, old in LEGACY.items():
        legacy = conf.get(old)
        if isinstance(legacy, dict) and name in legacy:
            out[key] = legacy[name]
    out.update(own)
    return out


def value(conf, name, key, default=None):
    """One attribute of repository NAME's entry, DEFAULT when unset."""
    found = entry(conf, name)
    return found[key] if key in found else default


def names_with(conf, key):
    """{name: value} of every repository whose entry sets KEY."""
    repos = conf.get("repos") if isinstance(conf.get("repos"), dict) else {}
    legacy = conf.get(LEGACY.get(key, "")) if isinstance(conf.get(LEGACY.get(key, "")), dict) else {}
    out = {}
    for name in list(repos) + [n for n in legacy if n not in repos]:
        found = entry(conf, name)
        if key in found:
            out[name] = found[key]
    return out


def slug_of(name):
    """A repository's slug: its name without the `-wordpress` ending."""
    return name[:-len("-wordpress")] if name.endswith("-wordpress") else name


def caller_values(conf, name):
    """{input: value} a caller of repository NAME is written with (#562):
    repos.yml `callers: defaults`, `{slug}` and `{SLUG}` filled in, under
    its entry's `callers`, which wins."""
    defaults = (conf.get("callers") or {}).get("defaults") if isinstance(conf.get("callers"), dict) else None
    slug = slug_of(name)
    out = {}
    for key, v in (defaults if isinstance(defaults, dict) else {}).items():
        out[key] = v.replace("{slug}", slug).replace("{SLUG}", slug.upper().replace("-", "_")) if isinstance(v, str) else v
    own = value(conf, name, "callers")
    out.update(own if isinstance(own, dict) else {})
    return out


def self_test(check):
    conf = {"repos": {"a": {"kinds": [], "project": 3, "pre-pr": False}, "b": {"kinds": []}}}
    check("entry: the repository's own", entry(conf, "a"), {"kinds": [], "project": 3, "pre-pr": False})
    check("entry: none for a name repos.yml lacks", entry(conf, "z"), {})
    check("value: an attribute, else the default", (value(conf, "a", "project"), value(conf, "b", "project", 0)), (3, 0))
    old = {"repos": {"a": {"kinds": [], "repro": False}}, "projects": {"a": 1, "c": 2}, "repro": {"a": {"ways": {}}}}
    check("the older shape is read, the entry winning", (value(old, "a", "project"), value(old, "a", "repro")), (1, False))
    check("names_with: every repository setting it", names_with(old, "project"), {"a": 1, "c": 2})
    values = {"callers": {"defaults": {"slug": "{slug}", "version-constant": "{SLUG}_VERSION", "dry-run": False}},
              "repos": {"diluxone-mail-wordpress": {"kinds": [], "callers": {"dry-run": True}}}}
    check("caller_values: the defaults, the slug from the name, the entry winning",
          caller_values(values, "diluxone-mail-wordpress"), {"slug": "diluxone-mail", "version-constant": "DILUXONE_MAIL_VERSION", "dry-run": True})
