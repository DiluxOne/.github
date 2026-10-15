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
  BASE_MAIN, BASE_README
            on a pull request, the same two files as the base branch has
            them (a missing one is an empty file): a pull request that
            raises Requires PHP above both the pack's minimum and the
            base's fails. The legacy floor is only ever the one already
            merged; a plugin's Requires PHP goes down to the minimum, never
            up.

Writes to $GITHUB_OUTPUT (and prints):

  tools     the tools' PHP, e.g. 8.5
  minimum   the oldest PHP the checks run on, e.g. 7.4
  declared  the plugin's own `Requires PHP`, "major.minor"; empty when none
  versions  every release from minimum to tools, as a JSON list
  phpstan   the minimum as PHPStan's `phpVersion` (70400)
  analysis-only
            the pack's `php.analysis-only`, as a JSON list: the dev
            packages only the analysis needs

`php-versions.py unit-deps` (ANALYSIS_ONLY, that list, in the environment)
takes those packages out of the checkout's composer.json require-dev, for
a unit-test job: it resolves the rest for its own PHP (`composer update`),
so a tool that needs a newer PHP than the minimum (Psalm 6 needs 8.1) never
stops the unit tests on the minimum.

`php-versions.py gate <script>` is one static gate of the checks (`lint`,
`stan`, `psalm:taint`), run from the plugin's checkout with TOOLS, MINIMUM
and PHPSTAN (the outputs above) in the environment. Before `composer
install` (no vendor/composer/installed.json yet) and again after it, it
writes `php`, the PHP the gate runs on: the tools', except for Psalm 5,
which stops at PHP 8.3 (a composer.json whose vimeo/psalm allows no 6, said
before the install, so Composer is not asked to install it on a PHP it
refuses; or a Psalm 5 installed, said after it). After the install it
warns when PHPCompatibility is missing or is 9 (which knows no syntax newer
than PHP 7.4), and for `stan` (before and after) writes `config`, a PHPStan config that
includes the repository's own (phpstan.neon, phpstan.neon.dist,
phpstan.dist.neon) and sets phpVersion to the minimum, in RUNNER_TEMP.
These are the bridges of #85, warnings until each plugin moves.

`php-versions.py --test` checks these rules.
"""
import json
import os
import re
import sys

# The last minor release of each finished major: PHP 7 ended at 7.4. When
# the tools' PHP moves to a new major, the one before it is added here.
LAST_MINOR = {5: 6, 7: 4}

# Psalm 5's newest PHP (vimeo/psalm 5.26.1: ~8.3.0). Psalm 6.14.2 is the
# first that runs on PHP 8.5.
PSALM5_PHP = "8.3"
PHPSTAN_CONFIGS = ("phpstan.neon", "phpstan.neon.dist", "phpstan.dist.neon")

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


def plan(settings, main, readme, base=None):
    """(outputs, notes): what the checks run on, and the annotations that say why.

    `base` is (main, readme) as the base branch has them, on a pull request:
    a pull request may lower Requires PHP, never raise it above both the
    pack's minimum and what the base declared."""
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
    if base is not None and own is not None and own > floor:
        braw, bwhere = declared(*base)
        before = parse(braw, f"Requires PHP in the base's {bwhere}") if braw is not None else None
        if before is None or own > before:
            was = f"PHP {before[0]}.{before[1]}" if before is not None else "nothing"
            raise ValueError(f"this pull request raises Requires PHP to {own[0]}.{own[1]} (the base says {was}), above the organisation's minimum, PHP {floor[0]}.{floor[1]}: every plugin supports the minimum, and a plugin's Requires PHP only goes down to it (DiluxOne/.github#85)")
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
        "analysis-only": json.dumps(analysis_only(php), separators=(",", ":")),
    }
    return out, notes


def allows_major(constraint, major):
    """Whether a Composer constraint lets in some release of `major` or later."""
    for alt in re.split(r"\s*\|\|?\s*", str(constraint or "").strip()):
        # A hyphen range (`5.0 - 6.2`) is its two bounds; an operator written
        # apart from its version (`>= 5.0`) is one part.
        alt = re.sub(r"^\s*(\S+)\s+-\s+(\S+)\s*$", r">=\1 <=\2", alt)
        parts = [p for p in re.split(r"[\s,]+", re.sub(r"([<>=!~^]+)\s+", r"\1", alt.strip())) if p]
        if not parts:
            continue
        ok = True
        for part in parts:
            m = re.search(r"(\d+)(?:\.(\d+))?", part)
            number = (int(m.group(1)), int(m.group(2) or 0)) if m else None
            if part.startswith("<="):
                ok = ok and number is not None and number[0] >= major
            elif part.startswith("<"):
                ok = ok and number is not None and number > (major, 0)
            elif part.startswith(("*", ">", "!=", "dev-")):
                # A lower bound, or one excluded release: no upper bound.
                continue
            else:
                # ^X, ~X, X.*, X.Y: nothing from a later major, as Composer reads them.
                ok = ok and number is not None and number[0] >= major
        if ok:
            return True
    return False


def installed_version(installed, name):
    """The version of `name` in vendor/composer/installed.json, without a leading v; '' when absent."""
    packages = installed.get("packages", []) if isinstance(installed, dict) else installed
    for pkg in packages or []:
        if pkg.get("name") == name:
            return str(pkg.get("version", "")).lstrip("v")
    return ""


def gate(script, env, root="."):
    """(outputs, notes) for one static gate; see the module's docstring."""
    tools, minimum = env["TOOLS"], env["MINIMUM"]
    out, notes = {"php": tools}, []
    composer = {}
    if os.path.isfile(os.path.join(root, "composer.json")):
        with open(os.path.join(root, "composer.json"), encoding="utf-8") as fh:
            composer = json.load(fh)
    path = os.path.join(root, "vendor", "composer", "installed.json")
    installed = None
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            installed = json.load(fh)
    move = "(DiluxOne/.github#85, docs/migrating.md)"
    if script == "psalm:taint":
        wanted = (composer.get("require-dev") or {}).get("vimeo/psalm") or (composer.get("require") or {}).get("vimeo/psalm")
        psalm = installed_version(installed, "vimeo/psalm") if installed is not None else ""
        if installed is None and wanted and not allows_major(wanted, 6):
            out["php"] = PSALM5_PHP
            notes.append(f"::warning file=composer.json::vimeo/psalm {wanted} allows no Psalm 6, and Psalm 5 does not run on PHP {tools}: Psalm runs on PHP {PSALM5_PHP} until the repository requires ^5.26 || ^6.14.2 {move}.")
        elif installed is not None and re.match(r"[0-5]\.", psalm) and tools != PSALM5_PHP:
            # (Already on 8.3: said before the install, not again.)
            out["php"] = PSALM5_PHP
            notes.append(f"::warning file=composer.json::Composer installed Psalm {psalm}, which does not run on PHP {tools}: Psalm runs on PHP {PSALM5_PHP} until the repository installs Psalm 6.14.2 or later (no config.platform.php holding its tools to an older PHP) {move}.")
    elif script == "lint" and installed is not None:
        compat = installed_version(installed, "phpcompatibility/php-compatibility")
        if not compat:
            notes.append(f"::warning file=composer.json::No PHPCompatibility is installed: nothing holds the code to PHP {minimum}. Require phpcompatibility/phpcompatibility-wp ^3.0@alpha and add PHPCompatibilityWP to the PHPCS ruleset {move}.")
        elif re.match(r"[0-9]\.", compat):
            notes.append(f"::warning file=composer.json::PHPCompatibility {compat} knows no syntax newer than PHP 7.4, so PHP 8 syntax passes it unseen: require phpcompatibility/phpcompatibility-wp ^3.0@alpha, which brings PHPCompatibility 10 {move}.")
    elif script == "stan":
        own = next((f for f in PHPSTAN_CONFIGS if os.path.isfile(os.path.join(root, f))), None)
        if own is None:
            raise ValueError(f"no {', '.join(PHPSTAN_CONFIGS)} at the repository's root: the checks give PHPStan the PHP to analyse for through it")
        config = os.path.join(env.get("RUNNER_TEMP") or root, "dx-phpstan.neon")
        with open(config, "w", encoding="utf-8") as fh:
            fh.write(f"includes:\n  - {os.path.abspath(os.path.join(root, own))}\nparameters:\n  phpVersion: {int(env['PHPSTAN'])}\n")
        out["config"] = config
    elif script not in ("lint", "stan", "psalm:taint"):
        raise ValueError(f"'{script}' is not a static gate (lint, stan, psalm:taint)")
    return out, notes


def annotation(note):
    """A workflow command with its message escaped: text read from the pull request (a constraint, a header) cannot start another command."""
    m = re.match(r"(::[a-z]+(?: (?:(?!::)[^\r\n])*)?::)(.*)", note, re.S)
    head, message = (m.group(1), m.group(2)) if m else ("", note)
    return head + message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def emit(out, notes):
    for note in notes:
        print(annotation(note))
    lines = "".join(f"{k}={v}\n" for k, v in out.items())
    print(lines, end="")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(lines)


def analysis_only(php):
    """The pack's `php.analysis-only`, checked: a list of Composer package names."""
    names = php.get("analysis-only") or []
    if not isinstance(names, list) or not all(isinstance(n, str) and re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", n) for n in names):
        raise ValueError(f"php.analysis-only is {names!r}, not a list of Composer package names")
    return names


def unit_deps(path, names):
    """Take the analysis-only packages out of composer.json's require-dev; the names taken out."""
    with open(path, encoding="utf-8") as fh:
        composer = json.load(fh)
    dev = composer.get("require-dev") or {}
    gone = [n for n in names if n in dev]
    if gone:
        composer["require-dev"] = {k: v for k, v in dev.items() if k not in gone}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(composer, fh, indent=4)
            fh.write("\n")
    return gone


def main(argv):
    try:
        if argv[:1] == ["gate"] and len(argv) == 2:
            emit(*gate(argv[1], os.environ))
            return 0
        if argv == ["unit-deps"]:
            gone = unit_deps("composer.json", json.loads(os.environ.get("ANALYSIS_ONLY") or "[]"))
            print("Not installed for the unit tests (analysis only): " + (", ".join(gone) or "nothing"))
            return 0
        if argv:
            print("usage: php-versions.py [--test | gate <lint|stan|psalm:taint> | unit-deps]", file=sys.stderr)
            return 64
        settings = json.loads(os.environ.get("SETTINGS") or "{}")
        base = None
        if os.environ.get("BASE_MAIN") or os.environ.get("BASE_README"):
            base = (os.environ.get("BASE_MAIN", ""), os.environ.get("BASE_README", ""))
        emit(*plan(settings, os.environ.get("MAIN", ""), os.environ.get("README", "readme.txt"), base))
    except (ValueError, KeyError) as err:
        print(annotation(f"::error::{err}"))
        return 1
    return 0


def self_test():
    import tempfile

    failed = 0

    def check(name, ok, detail=""):
        nonlocal failed
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
        failed += 0 if ok else 1

    def run(settings, main_text=None, readme_text=None, base_text=None):
        with tempfile.TemporaryDirectory() as d:
            main = os.path.join(d, "plugin.php")
            readme = os.path.join(d, "readme.txt")
            base_main = os.path.join(d, "base.php")
            for path, text in ((main, main_text), (readme, readme_text), (base_main, base_text)):
                if text is not None:
                    with open(path, "w") as fh:
                        fh.write(text)
            base = (base_main, os.path.join(d, "base-readme.txt")) if base_text is not None else None
            try:
                return plan(settings, main, readme, base)
            except ValueError as err:
                return None, [str(err)]

    pack = {"php": {"tools": "8.5", "minimum": "7.4"}}
    header = "<?php\n/**\n * Plugin Name: P\n * Requires PHP: {}\n */\n"

    out, notes = run(pack, header.format("8.1"), None, header.format("8.0"))
    check("a pull request that raises Requires PHP above the base and the minimum fails", out is None and "raises Requires PHP to 8.1" in notes[0], notes)
    out, notes = run(pack, header.format("8.0"), None, header.format("7.4"))
    check("a pull request that takes a 7.4 plugin to 8.0 fails", out is None and "the base says PHP 7.4" in notes[0], notes)
    out, notes = run(pack, header.format("8.0"), None, "")
    check("a new plugin above the minimum fails", out is None and "the base says nothing" in notes[0], notes)
    out, notes = run(pack, header.format("8.0"), None, header.format("8.0"))
    check("a pull request that keeps a legacy Requires PHP passes, with the warning", out and out["minimum"] == "8.0" and notes[0].startswith("::warning"), (out, notes))
    out, notes = run(pack, header.format("7.4"), None, header.format("8.1"))
    check("a pull request that lowers it to the minimum is checked from the minimum", out and out["minimum"] == "7.4" and not notes, (out, notes))
    out, notes = run(pack, header.format("8.0"), None, header.format("8.1"))
    check("a pull request that lowers it part of the way passes", out and out["minimum"] == "8.0", (out, notes))

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
    shipped_php_analysis = json.loads(out["analysis-only"]) if out else []

    # The static gates.
    check("constraint: ^5.26 allows no 6", not allows_major("^5.26", 6))
    check("constraint: ^5.26 || ^6.14.2 allows 6", allows_major("^5.26 || ^6.14.2", 6))
    check("constraint: ^5.0|^6.0 allows 6", allows_major("^5.0|^6.0", 6))
    check("constraint: >=5 and * allow 6", allows_major(">=5", 6) and allows_major("*", 6))
    check("constraint: >=5.0 <6.0 allows no 6", not allows_major(">=5.0 <6.0", 6))
    check("constraint: 5.0 - 6.2 allows 6, 5.0 - 5.26 does not", allows_major("5.0 - 6.2", 6) and not allows_major("5.0 - 5.26", 6))
    check("constraint: >=5.0 !=5.1.0 allows 6", allows_major(">=5.0 !=5.1.0", 6))
    check("constraint: >= 5.0 (operator apart) allows 6, >= 5.0 < 6.0 does not", allows_major(">= 5.0", 6) and not allows_major(">= 5.0 < 6.0", 6))
    check("constraint: >=5.0,<6.1 and <=6.0 allow 6", allows_major(">=5.0,<6.1", 6) and allows_major("<=6.0", 6))
    check("constraint: 5.* and ~5.26 allow no 6, 6.* does", not allows_major("5.*", 6) and not allows_major("~5.26", 6) and allows_major("6.*", 6))
    env = {"TOOLS": "8.5", "MINIMUM": "7.4", "PHPSTAN": "70400"}

    def gate_in(script, composer=None, installed=None, files=()):
        with tempfile.TemporaryDirectory() as d:
            if composer is not None:
                with open(os.path.join(d, "composer.json"), "w") as fh:
                    json.dump(composer, fh)
            if installed is not None:
                os.makedirs(os.path.join(d, "vendor", "composer"))
                with open(os.path.join(d, "vendor", "composer", "installed.json"), "w") as fh:
                    json.dump({"packages": [{"name": n, "version": v} for n, v in installed.items()]}, fh)
            for f in files:
                open(os.path.join(d, f), "w").close()
            try:
                out, notes = gate(script, dict(env, RUNNER_TEMP=d), d)
                if "config" in out:
                    with open(out["config"]) as fh:
                        out["config_text"] = fh.read()
                return out, notes
            except ValueError as err:
                return None, [str(err)]

    out, notes = gate_in("psalm:taint", {"require-dev": {"vimeo/psalm": "^5.26"}})
    check("psalm: ^5 alone, before the install: PHP 8.3, so Composer is not asked for Psalm 5 on 8.5", out["php"] == "8.3" and notes and notes[0].startswith("::warning"), (out, notes))
    out, notes = gate_in("psalm:taint", {"require-dev": {"vimeo/psalm": "^5.26 || ^6.14.2"}})
    check("psalm: 6 allowed, before the install: the tools' PHP", out["php"] == "8.5" and not notes, (out, notes))
    out, notes = gate_in("psalm:taint", {"require-dev": {"vimeo/psalm": "^5.26 || ^6.14.2"}}, {"vimeo/psalm": "5.26.1"})
    check("psalm: Psalm 5 installed (a platform pin): PHP 8.3, with a warning", out["php"] == "8.3" and "5.26.1" in notes[0], (out, notes))
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "composer.json"), "w") as fh:
            json.dump({"require-dev": {"vimeo/psalm": "^5.26"}}, fh)
        os.makedirs(os.path.join(d, "vendor", "composer"))
        with open(os.path.join(d, "vendor", "composer", "installed.json"), "w") as fh:
            json.dump({"packages": [{"name": "vimeo/psalm", "version": "5.26.1"}]}, fh)
        out, notes = gate("psalm:taint", dict(env, TOOLS="8.3"), d)
    check("psalm: already on 8.3 after the install: stays, said once", out["php"] == "8.3" and not notes, (out, notes))
    out, notes = gate_in("stan", {}, None, ["phpstan.neon"])
    check("stan: the config is written before the install too", out and "config" in out, out)
    out, notes = gate_in("psalm:taint", {"require-dev": {"vimeo/psalm": "^6.14.2"}}, {"vimeo/psalm": "v6.20.0"})
    check("psalm: Psalm 6 installed: the tools' PHP, nothing said", out["php"] == "8.5" and not notes, (out, notes))
    out, notes = gate_in("lint", {}, {"phpcompatibility/php-compatibility": "9.3.5"})
    check("lint: PHPCompatibility 9 is warned about", out["php"] == "8.5" and notes and "9.3.5" in notes[0], (out, notes))
    out, notes = gate_in("lint", {}, {"phpcompatibility/php-compatibility": "10.0.0-alpha2"})
    check("lint: PHPCompatibility 10 says nothing", not notes, notes)
    out, notes = gate_in("lint", {}, {})
    check("lint: no PHPCompatibility is warned about", notes and "No PHPCompatibility" in notes[0], notes)
    out, notes = gate_in("lint", {})
    check("lint: before the install, nothing to say", out["php"] == "8.5" and not notes, (out, notes))
    out, notes = gate_in("stan", {}, {}, ["phpstan.neon.dist"])
    check("stan: the repository's config, included, with the minimum's phpVersion", out and "phpstan.neon.dist" in out["config_text"] and "phpVersion: 70400" in out["config_text"], out)
    out, notes = gate_in("stan", {}, {}, ["phpstan.neon", "phpstan.neon.dist"])
    check("stan: phpstan.neon first, as PHPStan reads it", out and "phpstan.neon\n" in out["config_text"], out)
    out, notes = gate_in("stan", {}, {})
    check("stan: no config at the root fails", out is None and "phpstan.neon" in notes[0], notes)
    out, notes = gate_in("nope", {}, {})
    check("a gate that is not one fails", out is None and "not a static gate" in notes[0], notes)

    # The unit-test jobs' dependencies (#156 review): a plugin that requires
    # Psalm 6 alone (PHP 8.1+) still resolves its unit tests on PHP 7.4.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "composer.json")
        psalm_only = {"require": {"php": ">=7.4"}, "require-dev": {"phpunit/phpunit": "^9.6", "vimeo/psalm": "^6.14.2", "humanmade/psalm-plugin-wordpress": "^3.1.2", "phpstan/phpstan": "^2.1", "brain/monkey": "^2.6"}, "scripts": {"test:unit": "phpunit"}}
        with open(path, "w") as fh:
            json.dump(psalm_only, fh)
        gone = unit_deps(path, shipped_php_analysis)
        with open(path) as fh:
            left = json.load(fh)
        check("unit-deps: a Psalm-bearing composer.json loses the analysis tools", sorted(gone) == ["humanmade/psalm-plugin-wordpress", "phpstan/phpstan", "vimeo/psalm"], gone)
        check("unit-deps: keeps what the unit tests need, and the rest of the file", left["require-dev"] == {"phpunit/phpunit": "^9.6", "brain/monkey": "^2.6"} and left["scripts"] == psalm_only["scripts"] and left["require"] == psalm_only["require"], left)
        check("unit-deps: nothing left to take out changes nothing", unit_deps(path, shipped_php_analysis) == [])
    check("the pack's analysis-only names Psalm and its WordPress plugin", {"vimeo/psalm", "humanmade/psalm-plugin-wordpress"} <= set(shipped_php_analysis), shipped_php_analysis)
    out, notes = run(pack, header.format("7.4"))
    check("plan: analysis-only is written, empty when the pack has none", out and out["analysis-only"] == "[]", out)
    out, notes = run({"php": {"tools": "8.5", "minimum": "7.4", "analysis-only": ["not a package"]}}, header.format("7.4"))
    check("plan: an analysis-only entry that is not a package fails", out is None and "analysis-only" in notes[0], notes)

    check("annotation: a newline from the pull request cannot start another command",
          annotation("::warning file=composer.json::vimeo/psalm ^5\n::error::forged 100%") == "::warning file=composer.json::vimeo/psalm ^5%0A::error::forged 100%25")
    check("annotation: a property with a colon still has its message escaped",
          annotation("::warning file=C:/x.php::a\n::error::b") == "::warning file=C:/x.php::a%0A::error::b")
    check("annotation: text that is no command is escaped whole", "\n" not in annotation("plain\n::error::b"))
    out, notes = gate_in("psalm:taint", {"require-dev": {"vimeo/psalm": "^5.26\n::error::forged"}})
    check("psalm: a forged constraint is escaped when printed", "\n" not in annotation(notes[0]), notes)

    # The command line, as the workflow calls it.
    import subprocess

    with tempfile.TemporaryDirectory() as d:
        output = os.path.join(d, "out")
        with open(os.path.join(d, "plugin.php"), "w") as fh:
            fh.write(header.format("8.0"))
        proc = subprocess.run([sys.executable, os.path.abspath(__file__)], cwd=d, capture_output=True, text=True,
                              env=dict(os.environ, SETTINGS=json.dumps(pack), MAIN="plugin.php", GITHUB_OUTPUT=output))
        with open(output) as fh:
            written = fh.read()
        check("cli: writes the plan to GITHUB_OUTPUT and warns", proc.returncode == 0 and "minimum=8.0\n" in written and 'versions=["8.0",' in written and "::warning" in proc.stdout, (proc.returncode, proc.stdout, written))
        proc = subprocess.run([sys.executable, os.path.abspath(__file__)], cwd=d, capture_output=True, text=True,
                              env=dict(os.environ, SETTINGS="{}", MAIN="plugin.php", GITHUB_OUTPUT=output))
        check("cli: a pack without php fails with an error annotation", proc.returncode == 1 and proc.stdout.startswith("::error::"), (proc.returncode, proc.stdout))
        with open(os.path.join(d, "composer.json"), "w") as fh:
            json.dump({"require-dev": {"vimeo/psalm": "^5.26"}}, fh)
        proc = subprocess.run([sys.executable, os.path.abspath(__file__), "gate", "psalm:taint"], cwd=d, capture_output=True, text=True,
                              env=dict(os.environ, TOOLS="8.5", MINIMUM="7.4", PHPSTAN="70400", GITHUB_OUTPUT=output))
        check("cli: gate writes the PHP", proc.returncode == 0 and "php=8.3" in proc.stdout, (proc.returncode, proc.stdout))
        proc = subprocess.run([sys.executable, os.path.abspath(__file__), "unit-deps"], cwd=d, capture_output=True, text=True,
                              env=dict(os.environ, ANALYSIS_ONLY='["vimeo/psalm"]'))
        with open(os.path.join(d, "composer.json")) as fh:
            left = json.load(fh)
        check("cli: unit-deps edits the checkout's composer.json", proc.returncode == 0 and "vimeo/psalm" in proc.stdout and "vimeo/psalm" not in left.get("require-dev", {}), (proc.returncode, proc.stdout, left))
        proc = subprocess.run([sys.executable, os.path.abspath(__file__), "gate"], cwd=d, capture_output=True, text=True)
        check("cli: gate without a script is a usage error", proc.returncode == 64, proc.returncode)
    return failed


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        failed = self_test()
        if not failed:
            print("all tests passed")
        sys.exit(1 if failed else 0)
    sys.exit(main(sys.argv[1:]))
