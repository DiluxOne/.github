#!/usr/bin/env python3
"""The PHP versions a plugin's checks run on (#85).

Two values decide them, both in the kind's pack (kinds/<kind>/pack.yml,
`settings.php`), and nowhere else:

  tools     the PHP every tool runs on (PHPCS, PHPStan, Psalm, i18n, the
            wp-env suites): the latest release. The `platform` lane raises it
            when a new PHP ships.
  minimum   the oldest PHP every plugin supports. Only the maintainer
            changes it.

The tools never run on the minimum: they analyse for it (PHPStan's
`phpVersion`, PHPCompatibility's `testVersion`, Psalm's `--php-version`),
and the syntax and unit-test jobs run on every release from the minimum to
the tools' PHP.

A plugin that still declares a higher `Requires PHP` than the pack's minimum
(it has not lowered it yet, in its own pull request) is checked from its own
minimum until it does, with a warning that says so: the organisation's
minimum going down never turns every plugin's checks red at once. A plugin
that declares a lower one is checked from the pack's, which is all the
organisation supports.

Reads from the environment:

  SETTINGS  the kind's settings as JSON (scripts/kind.sh's `settings`);
            `php.tools` and `php.minimum`, as "major.minor"
  MAIN      the plugin's main file, whose `Requires PHP:` header is read
  README    readme.txt, read when the main file says nothing (default
            readme.txt)

Writes to $GITHUB_OUTPUT (and prints):

  tools     the tools' PHP, e.g. 8.5
  minimum   the oldest PHP the checks run on, e.g. 7.4
  declared  the plugin's own `Requires PHP`, "major.minor"; empty when none
  versions  every release from minimum to tools, as a JSON list
  phpstan   the minimum as PHPStan's `phpVersion` (70400)

`php-versions.py --test` checks these rules.
"""
import json
import os
import re
import sys

# The last minor release of each finished major: PHP 7 ended at 7.4. When
# the tools' PHP moves to a new major, the one before it is added here.
LAST_MINOR = {5: 6, 7: 4}

VERSION = re.compile(r"(\d+)\.(\d+)")
HEADER = re.compile(r"^[ \t/*#@]*Requires PHP:[ \t]*(\S+)", re.IGNORECASE | re.MULTILINE)


def parse(text, what):
    """'8.1' -> (8, 1); '8' and '8.1.30' are read as 8.0 and 8.1."""
    m = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.\d+)?", str(text).strip())
    if not m:
        raise ValueError(f"{what} is '{text}', not a PHP version (major.minor)")
    return int(m.group(1)), int(m.group(2) or 0)


def releases(low, high):
    """Every PHP release from low to high, both included."""
    out, (major, minor) = [], low
    while (major, minor) <= high:
        if major < high[0] and major not in LAST_MINOR:
            raise ValueError(f"PHP {major}'s last minor release is not known: add it to LAST_MINOR in scripts/php-versions.py")
        out.append(f"{major}.{minor}")
        if major < high[0] and minor >= LAST_MINOR[major]:
            major, minor = major + 1, 0
        else:
            minor += 1
    return out


def declared(main, readme):
    """The plugin's `Requires PHP`, from its main file, else its readme; None when neither says."""
    for path in (main, readme):
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                m = HEADER.search(fh.read(8192))
            if m:
                return m.group(1), path
    return None, None


def plan(settings, main, readme):
    """(outputs, notes): what the checks run on, and the annotations that say why."""
    php = (settings or {}).get("php") or {}
    if "tools" not in php or "minimum" not in php:
        raise ValueError("the kind's settings name no php.tools and php.minimum (kinds/<kind>/pack.yml)")
    tools = parse(php["tools"], "php.tools")
    floor = parse(php["minimum"], "php.minimum")
    if floor > tools:
        raise ValueError(f"php.minimum ({php['minimum']}) is newer than php.tools ({php['tools']})")
    notes = []
    raw, where = declared(main, readme)
    own = parse(raw, f"Requires PHP in {where}") if raw is not None else None
    low = floor
    if own is not None and own > floor:
        low = own
        notes.append(f"::warning file={where}::Requires PHP is {own[0]}.{own[1]}, above the organisation's minimum, PHP {floor[0]}.{floor[1]}: the checks start at {own[0]}.{own[1]} until the plugin lowers it (DiluxOne/.github#85).")
    elif own is not None and own < floor:
        notes.append(f"::notice file={where}::Requires PHP is {own[0]}.{own[1]}; the organisation checks from PHP {floor[0]}.{floor[1]}, its minimum.")
    if low > tools:
        raise ValueError(f"Requires PHP ({low[0]}.{low[1]}) is newer than the tools' PHP ({tools[0]}.{tools[1]})")
    out = {
        "tools": f"{tools[0]}.{tools[1]}",
        "minimum": f"{low[0]}.{low[1]}",
        "declared": f"{own[0]}.{own[1]}" if own is not None else "",
        "versions": json.dumps(releases(low, tools), separators=(",", ":")),
        "phpstan": str(low[0] * 10000 + low[1] * 100),
    }
    return out, notes


def main():
    try:
        settings = json.loads(os.environ.get("SETTINGS") or "{}")
        out, notes = plan(settings, os.environ.get("MAIN", ""), os.environ.get("README", "readme.txt"))
    except ValueError as err:
        print(f"::error::{err}")
        return 1
    for note in notes:
        print(note)
    lines = "".join(f"{k}={v}\n" for k, v in out.items())
    print(lines, end="")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(lines)
    return 0


def self_test():
    import tempfile

    failed = 0

    def check(name, ok, detail=""):
        nonlocal failed
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
        failed += 0 if ok else 1

    def run(settings, main_text=None, readme_text=None):
        with tempfile.TemporaryDirectory() as d:
            main = os.path.join(d, "plugin.php")
            readme = os.path.join(d, "readme.txt")
            if main_text is not None:
                with open(main, "w") as fh:
                    fh.write(main_text)
            if readme_text is not None:
                with open(readme, "w") as fh:
                    fh.write(readme_text)
            try:
                return plan(settings, main, readme)
            except ValueError as err:
                return None, [str(err)]

    pack = {"php": {"tools": "8.5", "minimum": "7.4"}}
    header = "<?php\n/**\n * Plugin Name: P\n * Requires PHP: {}\n */\n"

    check("releases: across a major", releases((7, 4), (8, 5)) == ["7.4", "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"], releases((7, 4), (8, 5)))
    check("releases: one", releases((8, 5), (8, 5)) == ["8.5"])
    try:
        releases((8, 4), (9, 0))
        check("releases: a major whose end is unknown fails", False, "no error")
    except ValueError as err:
        check("releases: a major whose end is unknown fails", "LAST_MINOR" in str(err), err)

    out, notes = run(pack, header.format("7.4"))
    check("a plugin at the minimum: from 7.4 to 8.5", out and out["minimum"] == "7.4" and json.loads(out["versions"]) == ["7.4", "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"] and not notes, (out, notes))
    check("the tools' PHP", out and out["tools"] == "8.5", out)
    check("PHPStan's phpVersion", out and out["phpstan"] == "70400", out)

    out, notes = run(pack, header.format("8.0"))
    check("a plugin still above the minimum: from its own, with a warning", out and out["minimum"] == "8.0" and out["declared"] == "8.0" and json.loads(out["versions"])[0] == "8.0" and notes and notes[0].startswith("::warning") and "#85" in notes[0], (out, notes))
    check("its PHPStan phpVersion is its own", out and out["phpstan"] == "80000", out)

    out, notes = run(pack, header.format("7.2"))
    check("a plugin below the minimum: from the organisation's, with a notice", out and out["minimum"] == "7.4" and notes and notes[0].startswith("::notice"), (out, notes))

    out, notes = run(pack, "<?php\n// no header\n", "=== P ===\nRequires PHP: 8.1\n")
    check("no header in the main file: the readme's", out and out["minimum"] == "8.1" and "readme.txt" in notes[0], (out, notes))

    out, notes = run(pack, header.format("8.1.30"))
    check("a patch release is read as its minor", out and out["minimum"] == "8.1", out)

    out, notes = run(pack)
    check("no Requires PHP anywhere: the pack's minimum", out and out["minimum"] == "7.4" and out["declared"] == "" and not notes, (out, notes))

    out, notes = run(pack, header.format("eight"))
    check("a Requires PHP that is not a version fails", out is None and "not a PHP version" in notes[0], notes)

    out, notes = run(pack, header.format("9.0"))
    check("a Requires PHP newer than the tools fails", out is None and "newer than the tools" in notes[0], notes)

    out, notes = run({"php": {"tools": "8.5"}})
    check("a pack without both values fails", out is None and "php.minimum" in notes[0], notes)

    out, notes = run({"php": {"tools": "8.3", "minimum": "8.4"}})
    check("a minimum newer than the tools fails", out is None and "newer than php.tools" in notes[0], notes)

    out, notes = run({"php": {"tools": 8.5, "minimum": 7.4}}, header.format("7.4"))
    check("numbers in the pack read as versions", out and out["tools"] == "8.5" and out["minimum"] == "7.4", (out, notes))

    # The pack this repository ships.
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import importlib

    policy = importlib.import_module("policy")
    shipped = (policy.load_yaml(os.path.join(here, "..", "kinds", "wordpress-plugin", "pack.yml")).get("settings") or {})
    out, notes = run(shipped, header.format("7.4"))
    check("the wordpress-plugin pack names both, as strings", out is not None and all(isinstance(shipped["php"][k], str) for k in ("tools", "minimum")), (shipped.get("php"), notes))
    return failed


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        failed = self_test()
        if not failed:
            print("all tests passed")
        sys.exit(1 if failed else 0)
    sys.exit(main())
