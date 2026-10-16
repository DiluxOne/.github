#!/usr/bin/env python3
"""The organisation's rules (rules/*.md, #187): every file holds to its header.

Each rule is a Markdown file with a YAML header (rules/README.md):

  id           the file's name without .md
  level        mandatory | standard
  applies_to   {all: true}, or {kinds: [...], roles: [...]} (kinds from kinds/)
  enforced_by  a list of `review` and `check: <name>`

and a body that says what the rule asks. The organisation's block of
AGENTS.md (agents-block.md) and rules/README.md name every rule, so an agent
in any repository reads them and a person finds them.

Usage:
  rules.py check   every rule in rules/ (exit 1, with the reasons, otherwise)
  rules.py --test  self-test
"""
import os
import re
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LEVELS = ("mandatory", "standard")
KEYS = {"id", "level", "applies_to", "enforced_by"}


def header(text):
    """The YAML header and the body of a rule, or (None, text) without one."""
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    if not m:
        return None, text
    return yaml.safe_load(m.group(1)), m.group(2)


def problems(name, text, kinds):
    """What is wrong with one rule file; empty when it holds."""
    head, body = header(text)
    if not isinstance(head, dict):
        return [f"{name}: no YAML header between --- lines"]
    out = []
    if set(head) != KEYS:
        out.append(f"{name}: the header has {sorted(head)}, not {sorted(KEYS)}")
    if head.get("id") != name[:-3]:
        out.append(f"{name}: id {head.get('id')!r} is not the file's name")
    if head.get("level") not in LEVELS:
        out.append(f"{name}: level {head.get('level')!r} is not one of {', '.join(LEVELS)}")
    applies = head.get("applies_to")
    if applies == {"all": True}:
        pass
    elif not isinstance(applies, dict) or not applies or set(applies) - {"kinds", "roles"}:
        out.append(f"{name}: applies_to is {{all: true}} or names kinds and roles")
    else:
        for key, values in applies.items():
            if not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
                out.append(f"{name}: applies_to.{key} is a list of names")
        for kind in applies.get("kinds") or []:
            if isinstance(kind, str) and kind not in kinds:
                out.append(f"{name}: kind {kind!r} has no pack in kinds/")
    enforced = head.get("enforced_by")
    if not isinstance(enforced, list) or not enforced:
        out.append(f"{name}: enforced_by lists at least one way it is held")
    else:
        for way in enforced:
            ok = way == "review" or (isinstance(way, dict) and list(way) == ["check"] and isinstance(way["check"], str) and way["check"])
            if not ok:
                out.append(f"{name}: enforced_by {way!r} is neither `review` nor `check: <name>`")
    if not body.strip():
        out.append(f"{name}: no text after the header")
    return out


def check(root):
    """Every problem with the rules under root; empty when they all hold."""
    rules_dir = os.path.join(root, "rules")
    kinds = {d for d in os.listdir(os.path.join(root, "kinds")) if os.path.isdir(os.path.join(root, "kinds", d))}
    names = sorted(f for f in os.listdir(rules_dir) if f.endswith(".md") and f != "README.md")
    block = open(os.path.join(root, "agents-block.md"), encoding="utf-8").read()
    index = open(os.path.join(rules_dir, "README.md"), encoding="utf-8").read()
    out = []
    if not names:
        out.append("rules/: no rule")
    for name in names:
        out += problems(name, open(os.path.join(rules_dir, name), encoding="utf-8").read(), kinds)
        if f"rules/{name}" not in block:
            out.append(f"{name}: agents-block.md does not name rules/{name}")
        if f"]({name})" not in index:
            out.append(f"{name}: rules/README.md does not list it")
    return out


def self_test():
    fails = 0

    def t(label, got, want):
        nonlocal fails
        ok = got == want
        print(("ok  " if ok else "FAIL") + "  " + label + ("" if ok else f": got {got!r}, want {want!r}"))
        fails += 0 if ok else 1

    good = "---\nid: test-first\nlevel: mandatory\napplies_to: {all: true}\nenforced_by: [review]\n---\nWrite the test first.\n"
    kinds = {"wordpress-plugin"}
    t("a rule with its header holds", problems("test-first.md", good, kinds), [])
    t("no header", problems("x.md", "Just text.\n", kinds), ["x.md: no YAML header between --- lines"])
    t("the id is the file's name", problems("other.md", good.replace("id: test-first", "id: other"), kinds), [])
    t("an id that is not the file's name", problems("x.md", good, kinds), ["x.md: id 'test-first' is not the file's name"])
    t("a field missing", len(problems("test-first.md", good.replace("enforced_by: [review]\n", ""), kinds)) > 0, True)
    t("a field of its own is not allowed", problems("test-first.md", good.replace("level:", "owner: me\nlevel:"), kinds)[0].startswith("test-first.md: the header has"), True)
    t("an unknown level", problems("test-first.md", good.replace("mandatory", "optional"), kinds), ["test-first.md: level 'optional' is not one of mandatory, standard"])
    t("standard is a level", problems("test-first.md", good.replace("mandatory", "standard"), kinds), [])
    t("applies to roles", problems("test-first.md", good.replace("{all: true}", "{roles: [front]}"), kinds), [])
    t("applies to a kind with its pack", problems("test-first.md", good.replace("{all: true}", "{kinds: [wordpress-plugin], roles: [back]}"), kinds), [])
    t("a kind with no pack", problems("test-first.md", good.replace("{all: true}", "{kinds: [web-app]}"), kinds), ["test-first.md: kind 'web-app' has no pack in kinds/"])
    t("all: false is not a scope", problems("test-first.md", good.replace("{all: true}", "{all: false}"), kinds), ["test-first.md: applies_to is {all: true} or names kinds and roles"])
    t("an empty list of roles", problems("test-first.md", good.replace("{all: true}", "{roles: []}"), kinds), ["test-first.md: applies_to.roles is a list of names"])
    t("held by a named check and the review", problems("test-first.md", good.replace("[review]", "[check: secret-scan, review]"), kinds), [])
    t("held by something else", problems("test-first.md", good.replace("[review]", "[the agent]"), kinds), ["test-first.md: enforced_by 'the agent' is neither `review` nor `check: <name>`"])
    t("held by nothing", problems("test-first.md", good.replace("[review]", "[]"), kinds), ["test-first.md: enforced_by lists at least one way it is held"])
    t("a header and no text", problems("test-first.md", good.replace("Write the test first.\n", ""), kinds), ["test-first.md: no text after the header"])

    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, "rules"))
        os.makedirs(os.path.join(root, "kinds", "wordpress-plugin"))

        def write(path, text):
            with open(os.path.join(root, path), "w", encoding="utf-8") as fh:
                fh.write(text)

        write("rules/test-first.md", good)
        write("rules/README.md", "| [test-first](test-first.md) | mandatory |\n")
        write("agents-block.md", "Read [test-first](https://example.org/rules/test-first.md).\n")
        t("check: a repository whose rules hold", check(root), [])
        write("agents-block.md", "No rules named.\n")
        t("check: a rule the AGENTS.md block does not name", check(root), ["test-first.md: agents-block.md does not name rules/test-first.md"])
        write("agents-block.md", "Read [test-first](https://example.org/rules/test-first.md).\n")
        write("rules/README.md", "No list.\n")
        t("check: a rule the index does not list", check(root), ["test-first.md: rules/README.md does not list it"])
        os.remove(os.path.join(root, "rules", "test-first.md"))
        t("check: no rule at all", check(root), ["rules/: no rule"])

    print("all passed" if not fails else f"{fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        sys.exit(self_test())
    if sys.argv[1:] == ["check"]:
        found = check(ROOT)
        for line in found:
            print(line)
        sys.exit(1 if found else 0)
    print(__doc__.split("Usage:")[1].rstrip(), file=sys.stderr)
    sys.exit(2)
