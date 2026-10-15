#!/usr/bin/env python3
"""The design systems (design-systems/<name>/): their tokens as CSS, and
their rules checked against their fixtures.

  design-tokens.py build [--check] [--system NAME]
        write design-systems/<name>/dist/tokens.css from its tokens.json, and
        dist/stylelint.json from its rules.yml, for every system (or the one
        named); --check writes nothing and fails when a file differs from
        what it would write, or a system is not valid.
  design-tokens.py brief --repo NAME --repos FILE --changed FILE [--root DIR]
        the review brief's section on the design system repository NAME
        declares in FILE (repos.yml), when a path listed in --changed is one
        of its screens; nothing otherwise. --root is the repository's
        checkout, for a `local` system (its docs/design-system/).
  design-tokens.py --test   self-test, and every system checked as --check

tokens.json is in the Design Tokens format (W3C community group): groups,
and tokens with `$value`, `$type` (on the token or inherited from a group),
`$description`; `{a.b.c}` is a reference to another token, `$root` a group's
own token. Every token becomes one custom property, `--dx-<path>` (`$root`
left out of the name); a reference becomes `var()` of the one it names, so a
property set at runtime (the accent, from the person's admin colour scheme)
carries everything built on it. One extension, `com.diluxone.mix`, writes a
colour as `color-mix()` of another and white: its `$value` must be the
colour that mix gives with the default values.

rules.yml lists what a review checks; a rule of type `pattern` carries a
regular expression and fixtures, and every `fail` fixture must match it and
no `pass` fixture may (comments are left out first). Its `screens` are the
paths, as regular expressions, of the files that draw a screen: a change to
one brings the system into the Claude review's brief (`brief`). The pattern
rules that read CSS are also dist/stylelint.json, the options of the stylelint rule
scripts/stylelint/design-system.mjs (the plugins' check,
scripts/design-lint.py): the same expressions, so a pattern keeps to the part
of Python's syntax JavaScript reads the same way. A rule's `tokens` (paths of
tokens.json, e.g. `color` or `font.size`) are where its message looks up the
token that holds a raw value it found.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SYSTEMS = os.path.join(ROOT, "design-systems")
PREFIX = "--dx-"
TYPES = {"color", "dimension", "number", "fontWeight", "duration", "shadow", "fontFamily"}
SEVERITIES = {"error", "warning", "notice"}
REF = re.compile(r"^\{([A-Za-z0-9_$.-]+)\}$")
HEX = re.compile(r"^#(?:[0-9a-f]{6}|[0-9a-f]{8})$")
DIMENSION = re.compile(r"^-?\d+(?:\.\d+)?(?:px|rem|em|%)$")
DURATION = re.compile(r"^\d+(?:\.\d+)?(?:ms|s)$")
NAME = re.compile(r"^(?:[a-z0-9]+(?:-[a-z0-9]+)*|\$root)$")
WEIGHTS = {"thin", "hairline", "extra-light", "ultra-light", "light", "normal", "regular", "book", "medium",
           "semi-bold", "demi-bold", "bold", "extra-bold", "ultra-bold", "black", "heavy"}


class Invalid(Exception):
    pass


def read_yaml(path):
    """yq where it is (the runners), PyYAML otherwise, as scripts/policy.py."""
    if shutil.which("yq"):
        out = subprocess.run(["yq", "-o=json", ".", path], check=True, capture_output=True, text=True).stdout
        return json.loads(out or "null") or {}
    try:
        import yaml
    except ImportError:
        sys.exit(f"{os.path.basename(sys.argv[0])} needs yq or PyYAML to read {path}")
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def flatten(tree):
    """{path: token} in the file's order; each token a dict with type, value,
    description and extensions, its type inherited from its groups."""
    out = {}

    def walk(node, path, inherited):
        kind = node.get("$type", inherited)
        if "$value" in node:
            if not path:
                raise Invalid("the file itself is not a token")
            if kind is None:
                raise Invalid(f"{'.'.join(path)}: no $type, on it or on a group above it")
            if kind not in TYPES:
                raise Invalid(f"{'.'.join(path)}: $type {kind} is not one this script writes ({', '.join(sorted(TYPES))})")
            extra = [k for k in node if k.startswith("$") and k not in ("$value", "$type", "$description", "$extensions")]
            children = [k for k in node if not k.startswith("$")]
            if extra or children:
                raise Invalid(f"{'.'.join(path)}: a token holds {', '.join(extra + children)}")
            if not isinstance(node.get("$extensions", {}), dict):
                raise Invalid(f"{'.'.join(path)}: $extensions is an object")
            out[".".join(path)] = {"type": kind, "value": node["$value"], "description": node.get("$description", ""),
                                   "extensions": node.get("$extensions") or {}}
            return
        for key, child in node.items():
            if key in ("$type", "$description", "$extensions"):
                continue
            if key.startswith("$") and key != "$root":
                raise Invalid(f"{'.'.join(path) or 'the file'}: unknown key {key}")
            if not NAME.match(key):
                raise Invalid(f"{'.'.join(path + [key])}: a name is lower-case words joined by hyphens")
            if not isinstance(child, dict):
                raise Invalid(f"{'.'.join(path + [key])}: neither a token nor a group")
            if key == "$root" and "$value" not in child:
                raise Invalid(f"{'.'.join(path + [key])}: $root is a token")
            walk(child, path + [key], kind)

    walk(tree, [], None)
    return out


def css_name(path):
    return PREFIX + "-".join(p for p in path.split(".") if p != "$root")


def target(tokens, ref, where):
    m = REF.match(ref) if isinstance(ref, str) else None
    if not m:
        return None
    name = m.group(1)
    if name not in tokens:
        raise Invalid(f"{where}: {ref} names no token")
    return name


def resolve(tokens, path, seen=()):
    """The value a token has once every reference is followed."""
    if path in seen:
        raise Invalid(f"{path}: a reference loop ({' -> '.join(seen + (path,))})")
    value = tokens[path]["value"]
    name = target(tokens, value, path)
    if name:
        if tokens[name]["type"] != tokens[path]["type"]:
            raise Invalid(f"{path}: a {tokens[path]['type']} cannot name the {tokens[name]['type']} {name}")
        return resolve(tokens, name, seen + (path,))
    if isinstance(value, dict):
        return {k: (resolve(tokens, n, seen + (path,)) if (n := target(tokens, v, path)) else v) for k, v in value.items()}
    return value


def mix(colour, other, amount):
    """colour at amount% over other, in sRGB, as color-mix() computes it."""
    a, b = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (colour, other))
    return "#" + "".join(f"{round(x * amount / 100 + y * (100 - amount) / 100):02x}" for x, y in zip(a, b))


def check_value(kind, value, path):
    def bad(why):
        raise Invalid(f"{path}: {why}")
    if kind == "color" and not (isinstance(value, str) and HEX.match(value)):
        bad(f"a color is #rrggbb or #rrggbbaa in lower case, not {value!r}")
    if kind == "dimension" and not (isinstance(value, str) and DIMENSION.match(value)):
        bad(f"a dimension is a number and px, rem, em or %, not {value!r}")
    if kind == "duration" and not (isinstance(value, str) and DURATION.match(value)):
        bad(f"a duration is a number and ms or s, not {value!r}")
    if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
        bad(f"a number, not {value!r}")
    if kind == "fontWeight" and not ((isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 1000) or value in WEIGHTS):
        bad(f"a font weight is 1 to 1000 or a keyword, not {value!r}")
    if kind == "fontFamily" and not (isinstance(value, str) or (isinstance(value, list) and value and all(isinstance(v, str) for v in value))):
        bad("a font family is a name or a list of names")
    if kind == "shadow":
        if not isinstance(value, dict) or set(value) - {"color", "offsetX", "offsetY", "blur", "spread", "inset"} \
                or not {"color", "offsetX", "offsetY", "blur"} <= set(value):
            bad("a shadow is color, offsetX, offsetY, blur, and optionally spread and inset")
        check_value("color", value["color"], path + ".color")
        for k in ("offsetX", "offsetY", "blur", "spread"):
            if k in value:
                check_value("dimension", value[k], f"{path}.{k}")


def validate(tokens):
    """Raises Invalid on anything the CSS could not be written from."""
    for path, tok in tokens.items():
        resolved = resolve(tokens, path)
        check_value(tok["type"], resolved, path)
        if isinstance(tok["value"], dict) and tok["type"] != "shadow":
            raise Invalid(f"{path}: an object value is only a shadow's")
        m = tok["extensions"].get("com.diluxone.mix")
        if m is not None:
            if tok["type"] != "color" or target(tokens, tok["value"], path):
                raise Invalid(f"{path}: a mix is a colour written as its value, not a reference")
            if not isinstance(m, dict):
                raise Invalid(f"{path}: a mix names `of` (a colour token), `with` (#rrggbb) and `amount` (1 to 99)")
            of = target(tokens, m.get("of"), path)
            amount = m.get("amount")
            if not of or tokens[of]["type"] != "color" or isinstance(amount, bool) or not isinstance(amount, int) \
                    or not 0 < amount < 100 or not (isinstance(m.get("with"), str) and re.fullmatch(r"#[0-9a-f]{6}", m["with"])):
                raise Invalid(f"{path}: a mix names `of` (a colour token), `with` (#rrggbb) and `amount` (1 to 99)")
            want = mix(resolve(tokens, of), m["with"], amount)
            if tok["value"] != want:
                raise Invalid(f"{path}: $value is {tok['value']}, but the mix it names gives {want}")


def css_value(tokens, path):
    tok = tokens[path]
    value = tok["value"]

    def one(v):
        name = target(tokens, v, path)
        return f"var({css_name(name)})" if name else v

    m = tok["extensions"].get("com.diluxone.mix")
    if m:
        return f"color-mix(in srgb, {one(m['of'])} {m['amount']}%, {m['with']})"
    if tok["type"] == "shadow" and isinstance(value, dict):
        parts = (["inset"] if value.get("inset") else []) + [one(value[k]) for k in ("offsetX", "offsetY", "blur", "spread") if k in value] + [one(value["color"])]
        return " ".join(parts)
    if tok["type"] == "fontFamily" and isinstance(value, list):
        return ", ".join(f'"{v}"' if " " in v else v for v in value)
    return str(one(value))


def render(name, tree):
    tokens = flatten(tree)
    validate(tokens)
    lines = [f"/* {name}: generated by scripts/design-tokens.py from design-systems/{name}/tokens.json.",
             "   Do not edit: change tokens.json and run `python3 scripts/design-tokens.py build`. */", ":root {"]
    group = None
    for path in tokens:
        top = path.split(".")[0]
        if top != group:
            if group is not None:
                lines.append("")
            lines.append(f"\t/* {top} */")
            group = top
        lines.append(f"\t{css_name(path)}: {css_value(tokens, path)};")
    names = [css_name(p) for p in tokens]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise Invalid(f"two tokens write the same property: {', '.join(dupes)}")
    return "\n".join(lines) + "\n}\n"


def strip_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


# What Python's `re` reads and JavaScript's RegExp does not, or reads
# otherwise: a pattern holds none of them, since stylelint runs it too.
NOT_IN_JS = [
    (re.compile(r"\(\?P[<=>]"), "a named group in Python's form (?P...)"),
    (re.compile(r"\(\?#"), "a comment group (?#...)"),
    (re.compile(r"\(\?[aiLmsux-]+[:)]"), "an inline flag ((?i), (?x)...)"),
    (re.compile(r"(?<!\\)\\[AZz]"), r"\A or \Z (^ and $ instead)"),
    (re.compile(r"\(\?>"), "an atomic group (?>...)"),
    (re.compile(r"(?<!\\)[*+?}]\+"), "a possessive quantifier (*+, ++, ?+)"),
]


def js_problems(pattern):
    return [why for rx, why in NOT_IN_JS if rx.search(pattern)]


def token_groups(rule, tokens):
    """A rule's `tokens` as a list, and what is wrong with it."""
    groups = rule.get("tokens")
    if groups is None:
        return [], []
    if isinstance(groups, str):
        groups = [groups]
    if not isinstance(groups, list) or not all(isinstance(g, str) and g for g in groups):
        return [], ["`tokens` is a path of tokens.json or a list of them"]
    if tokens is None:
        return groups, []
    return groups, [f"`tokens`: {g} is no token or group of tokens.json" for g in groups
                    if not any(p == g or p.startswith(g + ".") for p in tokens)]


def check_rules(rules, tokens=None):
    """The rules file's problems, as lines; an empty list when it is sound.
    Given the system's tokens (flattened), a rule's `tokens` must name some."""
    found = []
    screens = (rules or {}).get("screens")
    if screens is not None:
        if not isinstance(screens, list) or not screens or not all(isinstance(x, str) and x for x in screens):
            found.append("rules.yml: `screens` is a list of regular expressions")
        else:
            for rx in screens:
                try:
                    re.compile(rx)
                except re.error as exc:
                    found.append(f"rules.yml: a screen that does not compile: {rx!r}: {exc}")
    items = (rules or {}).get("rules")
    if not isinstance(items, list) or not items:
        return found + ["rules.yml: no `rules` list"]
    ids = [r.get("id") for r in items if isinstance(r, dict)]
    for rule in items:
        if not isinstance(rule, dict):
            found.append(f"rules.yml: an entry that is not a rule: {rule!r}")
            continue
        rid = rule.get("id") or "?"
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(rid)):
            found.append(f"{rid}: an id is kebab-case")
        if ids.count(rid) > 1:
            found.append(f"{rid}: the id is not unique")
        for key in ("message", "source"):
            if not str(rule.get(key) or "").strip():
                found.append(f"{rid}: no {key}")
        if rule.get("severity") not in SEVERITIES:
            found.append(f"{rid}: severity is one of {', '.join(sorted(SEVERITIES))}")
        if rule.get("applies-to") not in ("css", "php", "any"):
            found.append(f"{rid}: applies-to is css, php or any")
        kind = rule.get("type")
        if kind == "review":
            continue
        if kind != "pattern":
            found.append(f"{rid}: type is pattern or review")
            continue
        try:
            rx = re.compile(rule.get("pattern") or "", re.M)
        except re.error as exc:
            found.append(f"{rid}: the pattern does not compile: {exc}")
            continue
        if not rule.get("pattern"):
            found.append(f"{rid}: a pattern rule has a pattern")
            continue
        found += [f"{rid}: the pattern has {why}, which stylelint's JavaScript reads otherwise" for why in js_problems(rule["pattern"])]
        found += [f"{rid}: {p}" for p in token_groups(rule, tokens)[1]]
        fx = rule.get("fixtures") or {}
        if not fx.get("fail") or not fx.get("pass"):
            found.append(f"{rid}: a pattern rule has fail and pass fixtures")
            continue
        for code in fx["fail"]:
            if not rx.search(strip_comments(code)):
                found.append(f"{rid}: a fail fixture it does not catch: {code.strip()!r}")
        for code in fx["pass"]:
            if rx.search(strip_comments(code)):
                found.append(f"{rid}: a pass fixture it catches: {code.strip()!r}")
    return found


def normalise(value):
    """A raw value as scripts/stylelint/design-system.mjs reads one: a hex in
    lower case with six or eight digits, a number without trailing zeros."""
    value = str(value).lower()
    m = re.fullmatch(r"#([0-9a-f]{3,4})", value)
    if m:
        return "#" + "".join(c * 2 for c in m.group(1))
    m = re.fullmatch(r"(-?(?:\d+(?:\.\d*)?|\.\d+))([a-z%]*)", value)
    if m:
        number = float(m.group(1))
        return (str(int(number)) if number.is_integer() else repr(number)) + m.group(2)
    return value


def suggestions(tokens, groups):
    """{raw value: [property, ...]} for the tokens under `groups`: first those
    a screen uses, in the file's order, then the palette (a value written
    out that other tokens name); three at most."""
    named = {target(tokens, t["value"], p) for p, t in tokens.items()} - {None}
    palette_of = {p for p in named if not target(tokens, tokens[p]["value"], p)}
    out = {}
    for palette in (False, True):
        for path in tokens:
            if (path in palette_of) != palette or not any(path == g or path.startswith(g + ".") for g in groups):
                continue
            value = resolve(tokens, path)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                names = out.setdefault(normalise(value), [])
                if len(names) < 3:
                    names.append(css_name(path))
    return out


def stylelint_rules(rules, tokens):
    """The pattern rules that read CSS, as the stylelint rule's options."""
    out = []
    for rule in rules.get("rules") or []:
        if rule.get("type") != "pattern" or rule.get("applies-to") not in ("css", "any"):
            continue
        item = {"id": rule["id"], "severity": rule["severity"], "pattern": rule["pattern"],
                "message": " ".join(str(rule["message"]).split())}
        groups = token_groups(rule, tokens)[0]
        if groups and tokens:
            item["suggest"] = suggestions(tokens, groups)
        out.append(item)
    return out


def stylelint_config(name, rules, tokens):
    """dist/stylelint.json: the plugin, by its path from this repository's
    root (stylelint's --config-basedir), and the system's pattern rules."""
    conf = {"plugins": ["./scripts/stylelint/design-system.mjs"],
            "rules": {"diluxone/design-system": [True, {"system": name, "rules": stylelint_rules(rules, tokens)}]}}
    return json.dumps(conf, indent=2, ensure_ascii=False) + "\n"


def systems(only=None):
    names = sorted(d for d in os.listdir(SYSTEMS) if os.path.isfile(os.path.join(SYSTEMS, d, "tokens.json")))
    return [n for n in names if not only or n == only]


def check_system(name):
    """({dist file: what it holds}, the system's problems as lines). A file
    is left out when what it is written from is not sound."""
    base = os.path.join(SYSTEMS, name)
    problems = [f"{name}: no {f}" for f in ("README.md", "rules.yml") if not os.path.isfile(os.path.join(base, f))]
    out, tokens = {}, None
    try:
        with open(os.path.join(base, "tokens.json"), encoding="utf-8") as fh:
            tree = json.load(fh)
        out["tokens.css"] = render(name, tree)
        tokens = flatten(tree)
    except (Invalid, ValueError) as exc:
        problems.append(f"{name}/tokens.json: {exc}")
    if os.path.isfile(os.path.join(base, "rules.yml")):
        rules = read_yaml(os.path.join(base, "rules.yml"))
        found = check_rules(rules, tokens)
        problems += [f"{name}/{p}" for p in found]
        if not found and tokens is not None:
            out["stylelint.json"] = stylelint_config(name, rules, tokens)
        if not found and os.path.isfile(os.path.join(base, "components.md")):
            with open(os.path.join(base, "components.md"), encoding="utf-8") as fh:
                problems += [f"{name}/components.md: {p}" for p in check_examples(fh.read(), rules)]
    return out, problems


def check_examples(markdown, rules):
    """The system's own examples hold to its rules: every ```css block to the
    css pattern rules, every ```html and ```php block to the php ones."""
    found = []
    blocks = re.findall(r"^```(\w+)\n(.*?)^```", markdown, flags=re.S | re.M)
    for rule in rules.get("rules") or []:
        if rule.get("type") != "pattern":
            continue
        langs = {"css": ("css",), "php": ("html", "php"), "any": ("css", "html", "php")}[rule["applies-to"]]
        for lang, code in blocks:
            if lang in langs and (m := re.search(rule["pattern"], strip_comments(code), re.M)):
                found.append(f"an example breaks {rule['id']}: {m.group(0).strip()[:80]!r}")
    return found


# A system that does not say which files draw its screens (a `local` one
# with no rules.yml, and none it extends) is brought in by a stylesheet.
STYLESHEETS = [r"\.(?:css|scss|sass|less)$"]
# What the brief inlines of a system, at most (it is paid for on every
# review): the rest is named, to read when a finding needs it.
BRIEF_LIMIT = 40000
CENTRAL_NAME = "DiluxOne/" + ".github"


def render_rules(rules):
    """A rules file as the reviewer reads it: one line a rule, the fixtures
    and the expressions left out (they are for the checks, not for reading)."""
    lines = []
    for rule in (rules or {}).get("rules") or []:
        if isinstance(rule, dict):
            message = " ".join(str(rule.get("message") or "").split())
            how = "a check finds it" if rule.get("type") == "pattern" else "read for it"
            lines.append(f"- `{rule.get('id')}` ({rule.get('severity')}, {rule.get('applies-to')}, {how}): {message}")
    return "\n".join(lines) + "\n"


def system_parts(base, shown):
    """[(the path to name, where to read it from here, its text, or None when
    it has no such file)] of one system: its README, its components and its
    rules, rendered."""
    parts = []
    for f in ("README.md", "components.md"):
        path = os.path.join(base, f)
        parts.append((f"{shown}/{f}", os.path.relpath(path), open(path, encoding="utf-8").read() if os.path.isfile(path) else None))
    path = os.path.join(base, "rules.yml")
    parts.append((f"{shown}/rules.yml", os.path.relpath(path), render_rules(read_yaml(path)) if os.path.isfile(path) else None))
    return parts


def brief(repo, repos_file, changed, root=".", limit=BRIEF_LIMIT):
    """The brief's section on the repository's design system, or "" when it
    declares none or the change touches none of its screens."""
    conf = read_yaml(repos_file) if os.path.isfile(repos_file) else {}
    system = (conf.get("design-system") or {}).get(repo)
    if not system:
        return ""
    extends = None
    if system == "local":
        base, shown = os.path.join(root, "docs", "design-system"), "docs/design-system"
        readme = os.path.join(base, "README.md")
        if os.path.isfile(readme):
            with open(readme, encoding="utf-8") as fh:
                m = re.search(r"^Extends:\s*`?([a-z0-9-]+)`?", fh.read(), re.M)
            if m and os.path.isdir(os.path.join(SYSTEMS, m.group(1))):
                extends = m.group(1)
    else:
        base, shown = os.path.join(SYSTEMS, system), f"design-systems/{system}"
    if not os.path.isdir(base):
        print(f"design-tokens.py brief: {repo}'s design system `{system}` is not at {base}", file=sys.stderr)
        return ""
    screens = None
    for b in (base, os.path.join(SYSTEMS, extends) if extends else None):
        if b and screens is None and os.path.isfile(os.path.join(b, "rules.yml")):
            screens = read_yaml(os.path.join(b, "rules.yml")).get("screens")
    screens = [re.compile(rx, re.I) for rx in (screens or STYLESHEETS)]
    # A screen the change deletes draws nothing left to hold to the system.
    touched = [f for f in changed if any(rx.search(f) for rx in screens) and os.path.exists(os.path.join(root, f))]
    if not touched:
        return ""
    parts = system_parts(base, shown)
    if extends:
        parts += system_parts(os.path.join(SYSTEMS, extends), f"design-systems/{extends}")
    named = ", ".join(f"`{f}`" for f in touched[:10]) + (f" and {len(touched) - 10} more" if len(touched) > 10 else "")
    out = [f"## Design system: {system}" + (f" (extends {extends})" if extends else ""), "",
           f"This repository's screens follow this design system (repos.yml, `design-system`), and the change touches files that draw them: {named}. "
           "Hold what the change adds or alters in those files to it, as the profile says: a finding that relies on it names the rule's id or the component's heading."
           + (f" (`design-systems/` is in {CENTRAL_NAME}.)" if system != "local" or extends else ""), ""]
    used, left = 0, []
    for path, here, text in parts:
        if text is None:
            continue
        size = len(text.encode("utf-8"))
        if used + size > limit:
            left.append(here)
            continue
        used += size
        out += [f"### {path}", "", text.rstrip("\n"), ""]
    if left:
        out += ["Not inlined, to keep the brief short; read them when a finding needs them: " + ", ".join(f"`{p}`" for p in left) + ".", ""]
    return "\n".join(out)


SOURCES = {"tokens.css": "tokens.json", "stylelint.json": "rules.yml"}


def build(only=None, check=False):
    names = systems(only)
    if not names:
        print(f"no design system{' named ' + only if only else ''} under design-systems/", file=sys.stderr)
        return 1
    failed = 0
    for name in names:
        files, problems = check_system(name)
        for p in problems:
            print(f"::error::{p}")
        failed += bool(problems)
        for file, text in files.items():
            out = os.path.join(SYSTEMS, name, "dist", file)
            current = open(out, encoding="utf-8").read() if os.path.isfile(out) else None
            if check:
                if current != text:
                    print(f"::error::design-systems/{name}/dist/{file} differs from {SOURCES[file]}: run python3 scripts/design-tokens.py build")
                    failed += 1
                else:
                    print(f"{name}: dist/{file} is in step")
            elif current != text:
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with open(out, "w", encoding="utf-8") as fh:
                    fh.write(text)
                print(f"{name}: wrote dist/{file}")
    return 1 if failed else 0


def self_test():
    global SYSTEMS
    failed = 0

    def check(name, ok, detail=""):
        nonlocal failed
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
        failed += 0 if ok else 1

    def raises(name, tree, words):
        try:
            render("t", tree)
            check(name, False, "no error")
        except Invalid as exc:
            check(name, words in str(exc), str(exc))

    tree = {"color": {"$type": "color",
                      "grey": {"9": {"$value": "#1d2327"}},
                      "text": {"$root": {"$value": "{color.grey.9}"}, "muted": {"$value": "#646970"}},
                      "accent": {"$root": {"$value": "#2271b1"},
                                 "wash": {"$value": "#edf4f9", "$extensions": {"com.diluxone.mix": {"of": "{color.accent.$root}", "with": "#ffffff", "amount": 8}}}}},
            "space": {"$type": "dimension", "1": {"$value": "4px"}, "block": {"$value": "{space.1}"}},
            "shadow": {"focus": {"$type": "shadow", "$value": {"color": "{color.accent.$root}", "offsetX": "0px", "offsetY": "0px", "blur": "0px", "spread": "1px"}}},
            "font": {"weight": {"$type": "fontWeight", "semibold": {"$value": 600}}}}
    css = render("t", tree)
    check("a token becomes a property under --dx-", "\t--dx-color-grey-9: #1d2327;" in css, css)
    check("$root is the group's own property", "\t--dx-color-text: var(--dx-color-grey-9);" in css, css)
    check("a reference is var() of the one it names", "\t--dx-space-block: var(--dx-space-1);" in css, css)
    check("a mix is color-mix() of the property, so the scheme carries it", "--dx-color-accent-wash: color-mix(in srgb, var(--dx-color-accent) 8%, #ffffff);" in css, css)
    check("a shadow, its colour a reference", "--dx-shadow-focus: 0px 0px 0px 1px var(--dx-color-accent);" in css, css)
    check("a font weight is a plain number", "--dx-font-weight-semibold: 600;" in css, css)
    check("groups keep the file's order, a comment each", css.index("/* color */") < css.index("/* space */") < css.index("/* shadow */"), css)
    check("the file says it is generated", "Do not edit" in css.splitlines()[1], css)
    check("mix: the arithmetic of color-mix() in sRGB", mix("#2271b1", "#ffffff", 8) == "#edf4f9" and mix("#2271b1", "#ffffff", 45) == "#9cbfdc", mix("#2271b1", "#ffffff", 45))
    raises("a reference to nothing fails", {"c": {"$type": "color", "a": {"$value": "{c.b}"}}}, "names no token")
    raises("a reference loop fails", {"c": {"$type": "color", "a": {"$value": "{c.b}"}, "b": {"$value": "{c.a}"}}}, "loop")
    raises("a reference to a group, not its $root, fails", {"c": {"$type": "color", "a": {"$root": {"$value": "#000000"}}, "b": {"$value": "{c.a}"}}}, "names no token")
    raises("a token with no type fails", {"c": {"a": {"$value": "#000000"}}}, "no $type")
    raises("a type this script does not write fails", {"c": {"$type": "gradient", "a": {"$value": "x"}}}, "not one this script writes")
    raises("a colour in another form fails", {"c": {"$type": "color", "a": {"$value": "#FFF"}}}, "a color is")
    raises("a dimension with no unit fails", {"c": {"$type": "dimension", "a": {"$value": "4"}}}, "a dimension is")
    raises("a reference across types fails", {"c": {"$type": "color", "a": {"$value": "{d.b}"}}, "d": {"$type": "dimension", "b": {"$value": "4px"}}}, "cannot name")
    raises("a name in capitals fails", {"c": {"$type": "color", "Main": {"$value": "#000000"}}}, "lower-case")
    raises("a mix whose $value is not what it gives fails", {"c": {"$type": "color", "a": {"$value": "#2271b1"}, "w": {"$value": "#ffffff", "$extensions": {"com.diluxone.mix": {"of": "{c.a}", "with": "#ffffff", "amount": 8}}}}}, "the mix it names gives #edf4f9")
    raises("two tokens that write the same property fail", {"c": {"$type": "color", "a": {"$root": {"$value": "#000000"}}}, "c-a": {"$type": "color", "$root": {"$value": "#000000"}}}, "same property")
    for what, ext in (("a mix that is not an object", {"com.diluxone.mix": "8%"}), ("a mix whose amount is true", {"com.diluxone.mix": {"of": "{c.a}", "with": "#ffffff", "amount": True}}),
                      ("$extensions that is not an object", "x"), ("$extensions that is an empty list", [])):
        raises(f"{what} fails", {"c": {"$type": "color", "a": {"$value": "#2271b1"}, "w": {"$value": "#edf4f9", "$extensions": ext}}}, "object" if what.startswith("$") else "a mix names")
    raises("a token that is also a group fails", {"c": {"$type": "color", "a": {"$value": "#000000", "b": {"$value": "#000000"}}}}, "a token holds")
    good = {"rules": [{"id": "no-important", "type": "pattern", "severity": "error", "applies-to": "css", "message": "m", "source": "s",
                       "pattern": r"!\s*important", "fixtures": {"fail": [".a { color: red !important; }"], "pass": [".a { color: red; } /* !important */"]}},
                      {"id": "read-it", "type": "review", "severity": "notice", "applies-to": "any", "message": "m", "source": "s"}]}
    check("rules: a pattern with fixtures that hold, and a review rule", check_rules(good) == [], check_rules(good))
    check("rules: a comment is not code", not check_rules(good))
    wrong = {"rules": [dict(good["rules"][0], fixtures={"fail": [".a { color: red; }"], "pass": [".a { x: 1 !important; }"]})]}
    got = check_rules(wrong)
    check("rules: a fail fixture it misses, and a pass fixture it catches, are reported", len(got) == 2 and "does not catch" in got[0] and "it catches" in got[1], got)
    got = check_rules({"rules": [dict(good["rules"][1], id="Bad Id", severity="fatal"), dict(good["rules"][1], id="x", type="pattern"), good["rules"][1], good["rules"][1]]})
    check("rules: a bad id, an unknown severity, a pattern rule with no pattern, a repeated id", any("kebab" in g for g in got) and any("severity" in g for g in got) and any("has a pattern" in g for g in got) and sum("unique" in g for g in got) == 2, got)
    check("rules: no list at all", check_rules({}) == ["rules.yml: no `rules` list"], check_rules({}))
    got = check_rules(dict(good, screens=["\\.css$", "(unclosed"]))
    check("rules: a screen that does not compile is reported", len(got) == 1 and "does not compile" in got[0], got)
    check("rules: screens that are not a list are reported", any("`screens`" in g for g in check_rules(dict(good, screens="\\.css$"))), "")
    rendered = render_rules(good)
    check("brief: a rule is one line with its id and severity, no expression or fixture",
          "- `no-important` (error, css, a check finds it): m" in rendered and "important;" not in rendered, rendered)
    doc = "Text with #fff in it.\n\n```css\n.a { color: red !important; }\n```\n\n```css\n.b { color: red; }\n```\n\n```php\n<?php echo 1 !important; ?>\n```\n"
    got = check_examples(doc, good)
    check("examples: a css block that breaks a css rule is reported, prose and other languages are not", len(got) == 1 and "no-important" in got[0], got)
    with tempfile.TemporaryDirectory() as tmp:
        repos = os.path.join(tmp, "repos.yml")
        with open(repos, "w", encoding="utf-8") as fh:
            fh.write("design-system:\n  r: wordpress-admin\n")
        for f in ("assets/admin.css", "includes/admin/settings.php", "includes/class-sync.php"):
            os.makedirs(os.path.dirname(os.path.join(tmp, f)), exist_ok=True)
            open(os.path.join(tmp, f), "w").close()
        whole = brief("r", repos, ["assets/admin.css"], tmp)
        short = brief("r", repos, ["assets/admin.css"], tmp, limit=8000)
        check("brief: the whole system fits under the limit", "### design-systems/wordpress-admin/components.md" in whole and "Not inlined" not in whole and len(whole) <= BRIEF_LIMIT + 2000, len(whole))
        check("brief: past the limit, what does not fit is named, not inlined",
              "### design-systems/wordpress-admin/README.md" in short and "### design-systems/wordpress-admin/components.md" not in short and "`design-systems/wordpress-admin/components.md`" in short, short[-400:])
        check("brief: a PHP file that draws no screen brings nothing", brief("r", repos, ["includes/class-sync.php"], tmp) == "", "")
        check("brief: an admin template brings it", brief("r", repos, ["includes/admin/settings.php"], tmp) != "", "")
        check("brief: a stylesheet the change deletes brings nothing", brief("r", repos, ["assets/gone.css"], tmp) == "", "")
        os.makedirs(os.path.join(tmp, "docs", "design-system"))
        with open(os.path.join(tmp, "docs", "design-system", "README.md"), "w", encoding="utf-8") as fh:
            fh.write("\u00e1" * 6000)
        with open(repos, "w", encoding="utf-8") as fh:
            fh.write("design-system:\n  r: local\n")
        got = brief("r", repos, ["assets/admin.css"], tmp, limit=8000)
        check("brief: the limit counts bytes (6000 characters, 12000 bytes, past 8000)", "### docs/design-system/README.md" not in got and "Not inlined" in got, got[-300:])
    for pattern, bad in ((r"(?P<x>a)", True), (r"(?i)a", True), (r"a\Z", True), (r"a++", True), (r"(?>a)", True),
                         (r"(?<![\w.-])\d+\+?", False), (r"(?:^|[{;])\s*(?!--)a", False), (r"\\Z", False)):
        check(f"js: {pattern} {'is' if bad else 'is not'} refused", bool(js_problems(pattern)) == bad, js_problems(pattern))
    check("normalise: hex in lower case and six digits, numbers without zeros",
          [normalise(v) for v in ("#DDD", "#2271B1", "#0003", "16px", "1.50em", ".5rem", "-2px", 600, "50%")]
          == ["#dddddd", "#2271b1", "#00000033", "16px", "1.5em", "0.5rem", "-2px", "600", "50%"], "")
    flat = flatten(tree)
    got = suggestions(flat, ["color"])
    check("suggest: what a screen uses first, the palette after", got.get("#1d2327") == ["--dx-color-text", "--dx-color-grey-9"], got)
    check("suggest: only the groups named", "4px" not in got and suggestions(flat, ["space"]).get("4px") == ["--dx-space-block", "--dx-space-1"], suggestions(flat, ["space"]))
    check("rules: `tokens` that name nothing are refused", check_rules({"rules": [dict(good["rules"][0], tokens="colour")]}, flat) == ["no-important: `tokens`: colour is no token or group of tokens.json"], "")
    check("rules: a pattern JavaScript reads otherwise is refused", any("stylelint" in g for g in check_rules({"rules": [dict(good["rules"][0], pattern=r"(?i)!\s*important")]})), "")
    conf = json.loads(stylelint_config("t", {"rules": [dict(good["rules"][0], tokens="color"), good["rules"][1],
                                                        dict(good["rules"][0], id="php-only", **{"applies-to": "php"})]}, flat))
    opts = conf["rules"]["diluxone/design-system"][1]
    check("stylelint.json: the CSS pattern rules only, with what to suggest", [r["id"] for r in opts["rules"]] == ["no-important"] and opts["rules"][0]["suggest"]["#2271b1"] == ["--dx-color-accent"], opts)
    check("stylelint.json: the rule's own pattern, word for word", opts["rules"][0]["pattern"] == good["rules"][0]["pattern"], opts)
    for name in systems():
        files, problems = check_system(name)
        check(f"design-systems/{name}: tokens, rules and fixtures are sound", not problems, problems)
        for file in ("tokens.css", "stylelint.json"):
            out = os.path.join(SYSTEMS, name, "dist", file)
            check(f"design-systems/{name}: dist/{file} is in step", os.path.isfile(out) and open(out, encoding="utf-8").read() == files.get(file), "run python3 scripts/design-tokens.py build")
    check("wordpress-admin is there", "wordpress-admin" in systems(), systems())
    # C4 (#152): a rules.yml changed and not built again fails the check.
    real = SYSTEMS
    with tempfile.TemporaryDirectory() as tmp:
        SYSTEMS = os.path.join(tmp, "design-systems")
        shutil.copytree(os.path.join(real, "wordpress-admin"), os.path.join(SYSTEMS, "wordpress-admin"))
        rules_path = os.path.join(SYSTEMS, "wordpress-admin", "rules.yml")
        with open(rules_path, encoding="utf-8") as fh:
            text = fh.read()
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write(text.replace("severity: warning", "severity: error", 1))
        saved = sys.stdout
        sys.stdout = open(os.devnull, "w")
        try:
            stale = build("wordpress-admin", check=True)
            build("wordpress-admin")
            fresh = build("wordpress-admin", check=True)
        finally:
            sys.stdout.close()
            sys.stdout = saved
        SYSTEMS = real
    check("build --check fails when rules.yml and dist/stylelint.json disagree, and build puts them in step", (stale, fresh) == (1, 0), (stale, fresh))
    saved, sys.stderr = sys.stderr, open(os.devnull, "w")
    try:
        usage = [main(["build", "--system"]), main(["build", "--system", "--check"])]
    finally:
        sys.stderr.close()
        sys.stderr = saved
    check("build --system with no name is a usage error, not every system", usage == [64, 64], usage)
    if not failed:
        print("all tests passed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv[:1] == ["brief"]:
        opts = dict(zip(argv[1::2], argv[2::2]))
        known = {"--repo", "--repos", "--changed", "--root"}
        if len(argv) % 2 == 0 or not {"--repo", "--repos", "--changed"} <= set(opts) or set(opts) - known:
            print(__doc__, file=sys.stderr)
            return 64
        with open(opts["--changed"], encoding="utf-8") as fh:
            changed = [line.strip() for line in fh if line.strip()]
        sys.stdout.write(brief(opts["--repo"], opts["--repos"], changed, opts.get("--root", ".")))
        return 0
    if argv[:1] == ["build"]:
        rest = argv[1:]
        only = None
        if "--system" in rest:
            i = rest.index("--system") + 1
            if i >= len(rest) or rest[i].startswith("--"):
                print(__doc__, file=sys.stderr)
                return 64
            only = rest[i]
        return build(only, "--check" in rest)
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
