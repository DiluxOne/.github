#!/usr/bin/env python3
"""Every setting the engine applies, from policy/settings-schema.yml (#568).

  settings.py overlay ENGINE_FILE ORG_FILE [--as PATH]
                       print ENGINE_FILE with the organisation's ORG_FILE laid
                       over it, by the schema's rules: a mapping merges key by
                       key, a value replaces, a list replaces unless the
                       schema marks it `add-only` (the engine's entries first,
                       then the organisation's new ones) or `by: name` (merged
                       by each entry's name), and a key marked `identity` is
                       never kept from the engine's. PATH is the file's path
                       in the engine (policy/autonomy.yml), else ENGINE_FILE's
  settings.py --test   self-test

Environment: DX_SETTINGS_SCHEMA, the schema to read (default:
policy/settings-schema.yml beside this script's directory; the engine's
own, never an organisation's).
"""
import copy
import fnmatch
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SCHEMA = os.path.join(ROOT, "policy", "settings-schema.yml")
# The most a configuration file may weigh: an alias bomb stops here.
MAX_BYTES = 1 << 20


def load(path):
    """A YAML file as data, with PyYAML where it is or yq; {} when missing."""
    if not path or not os.path.exists(path):
        return {}
    if os.path.getsize(path) > MAX_BYTES:
        raise ValueError(f"{path}: larger than {MAX_BYTES} bytes")
    try:
        import yaml
    except ImportError:
        yaml = None
    if yaml is not None:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    if shutil.which("yq"):
        out = subprocess.run(["yq", "-o=json", ".", path], check=True, capture_output=True, text=True).stdout
        return json.loads(out or "null")
    sys.exit(f"settings.py needs PyYAML or yq to read {path}")


def dump(data):
    """Data as YAML text, with PyYAML where it is or yq."""
    try:
        import yaml
    except ImportError:
        yaml = None
    if yaml is not None:
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000, default_flow_style=False)
    out = subprocess.run(["yq", "-P", "-o=yaml", ".", "-"], input=json.dumps(data), check=True, capture_output=True, text=True)
    return out.stdout


def schema(path=None):
    return load(path or os.environ.get("DX_SETTINGS_SCHEMA") or SCHEMA) or {}


def entries(conf, rel):
    """The schema's settings of the file REL (policy/autonomy.yml)."""
    out = []
    for pattern, settings in ((conf or {}).get("files") or {}).items():
        if fnmatch.fnmatchcase(rel, pattern):
            out.extend(settings or [])
    return out


def key_matches(key, path):
    """Whether a schema key (a.*.b, or `.` for the whole file) is PATH."""
    if key == ".":
        return not path
    parts = key.split(".")
    return len(parts) == len(path) and all(p == "*" or p == str(q) for p, q in zip(parts, path))


def rule(settings, path):
    for s in settings:
        if key_matches(str(s.get("key", "")), path):
            return s
    return {}


def merge(engine, theirs, settings, path=()):
    """THEIRS laid over ENGINE by the settings' rules. Pure."""
    r = rule(settings, list(path))
    if r.get("identity"):
        return copy.deepcopy(theirs)
    if isinstance(engine, dict) and isinstance(theirs, dict):
        out = copy.deepcopy(engine)
        for key, value in theirs.items():
            out[key] = merge(engine[key], value, settings, (*path, key)) if key in engine else copy.deepcopy(value)
        if not path:
            for s in settings:
                key = str(s.get("key", ""))
                if s.get("identity") and "." not in key and key in out and key not in theirs:
                    del out[key]
        return out
    if isinstance(engine, list) and isinstance(theirs, list):
        if r.get("merge") == "add-only":
            return copy.deepcopy(engine) + [copy.deepcopy(v) for v in theirs if v not in engine]
        by = r.get("by")
        if by and all(isinstance(v, dict) for v in engine + theirs):
            out = copy.deepcopy(engine)
            index = {v.get(by): n for n, v in enumerate(out)}
            for v in theirs:
                if v.get(by) in index:
                    out[index[v[by]]] = {**out[index[v[by]]], **copy.deepcopy(v)}
                else:
                    index[v.get(by)] = len(out)
                    out.append(copy.deepcopy(v))
            return out
    if r.get("merge") == "add-only" and isinstance(engine, list):
        raise ValueError(f"{'.'.join(map(str, path))}: a list, which an organisation only adds to")
    return copy.deepcopy(theirs)


def overlay(engine_file, org_file, rel=None, conf=None):
    rel = rel or os.path.relpath(os.path.abspath(engine_file), ROOT)
    return merge(load(engine_file), load(org_file), entries(conf if conf is not None else schema(), rel))


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    conf = schema()
    autonomy = entries(conf, "policy/autonomy.yml")
    check("the schema has the autonomy policy's settings", bool(rule(autonomy, ["lanes", "human-issue", "merge"])), True)
    check("a key with * is any lane", key_matches("lanes.*.accept", ["lanes", "x", "accept"]), True)
    check("but not deeper", key_matches("lanes.*.accept", ["lanes", "x", "accept", "y"]), False)
    check("`.` is the whole file", key_matches(".", []), True)
    engine = {"autopilot": True, "constitution": ["policy/**", "rules/**"], "person-merges": ["security"],
              "budgets-usd": {"autopilot-work": 20, "autopilot-fix": 10},
              "lanes": {"bugfix-reproduced": {"accept": "policy", "repositories": ["*"], "merge": {"max-risk": "medium", "max-complexity": "medium"}},
                        "human-issue": {"accept": "human", "merge": {"max-risk": "medium", "max-complexity": "high"}}}}
    got = merge(engine, {"lanes": {"bugfix-reproduced": {"accept": "human"}}}, autonomy)
    check("C1: one key set, only that key changes", got["lanes"]["bugfix-reproduced"], {**engine["lanes"]["bugfix-reproduced"], "accept": "human"})
    check("C1: every other key is the engine's", {k: v for k, v in got.items() if k != "lanes"}, {k: v for k, v in engine.items() if k != "lanes"})
    check("C1: and the other lanes", got["lanes"]["human-issue"], engine["lanes"]["human-issue"])
    got = merge(engine, {"lanes": {"human-issue": {"merge": {"max-risk": "low"}}}}, autonomy)
    check("a mapping merges key by key", got["lanes"]["human-issue"]["merge"], {"max-risk": "low", "max-complexity": "high"})
    got = merge(engine, {"budgets-usd": {"autopilot-work": 5}}, autonomy)
    check("a value replaces", got["budgets-usd"], {"autopilot-work": 5, "autopilot-fix": 10})
    got = merge(engine, {"lanes": {"bugfix-reproduced": {"repositories": ["a"]}}}, autonomy)
    check("B1: a list replaces the engine's", got["lanes"]["bugfix-reproduced"]["repositories"], ["a"])
    got = merge(engine, {"constitution": ["docs/**"], "person-merges": []}, autonomy)
    check("B1: an add-only list keeps the engine's entries, then adds", got["constitution"], ["policy/**", "rules/**", "docs/**"])
    check("B1: an add-only list cannot be emptied", got["person-merges"], ["security"])
    try:
        merge(engine, {"constitution": "none"}, autonomy)
        check("an add-only list replaced by a value fails", "merged", "ValueError")
    except ValueError:
        check("an add-only list replaced by a value fails", "ValueError", "ValueError")
    got = merge(engine, {"lanes": {"theirs": {"accept": "human"}}}, autonomy)
    check("a key the engine has not is added", got["lanes"]["theirs"], {"accept": "human"})
    orgs = entries(conf, "org.yml")
    got = merge({"org": "DiluxOne", "bot": {"app": "dilux-bot", "id": 1}, "maintainers": ["a"], "attribution": "warn"},
                {"org": "Acme", "bot": {"app": "acme-bot"}}, orgs)
    check("identity keys are never kept from the engine's", got, {"org": "Acme", "bot": {"app": "acme-bot"}, "attribution": "warn"})
    labels = entries(conf, "labels.yml")
    got = merge([{"name": "accepted", "color": "0E8A16"}, {"name": "claimed", "color": "5319E7"}],
                [{"name": "accepted", "description": "Acme's"}, {"name": "acme:own", "color": "000000"}], labels)
    check("labels merge by name", got, [{"name": "accepted", "color": "0E8A16", "description": "Acme's"}, {"name": "claimed", "color": "5319E7"}, {"name": "acme:own", "color": "000000"}])
    check("a kind's pack has its rules", rule(entries(conf, "kinds/web-app/pack.yml"), ["release", "publishes-to"]).get("org"), "any")
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        e, o = os.path.join(t, "e.yml"), os.path.join(t, "o.yml")
        with open(e, "w", encoding="utf-8") as fh:
            fh.write("a: 1\nmerge-queue: \"off\"\nb: {c: 2, d: 3}\n")
        with open(o, "w", encoding="utf-8") as fh:
            fh.write("b: {c: 4}\n")
        got = overlay(e, o, "x.yml", {})
        check("overlay: two files", got, {"a": 1, "merge-queue": "off", "b": {"c": 4, "d": 3}})
        check("overlay: written as YAML that reads the same", load_text(dump(got)), got)
        with open(o, "w", encoding="utf-8") as fh:
            fh.write("x" * (MAX_BYTES + 1))
        try:
            overlay(e, o, "x.yml", {})
            check("a file too large to be configuration fails", "read", "ValueError")
        except ValueError:
            check("a file too large to be configuration fails", "ValueError", "ValueError")
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def load_text(text):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as fh:
        fh.write(text)
    try:
        return load(fh.name)
    finally:
        os.unlink(fh.name)


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv[:1] == ["overlay"] and len(argv) in (3, 5) and (len(argv) == 3 or argv[3] == "--as"):
        try:
            sys.stdout.write(dump(overlay(argv[1], argv[2], argv[4] if len(argv) == 5 else None)))
        except (ValueError, OSError) as exc:
            print(f"::error::{argv[2]}: {exc}", file=sys.stderr)
            return 1
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
