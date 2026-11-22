#!/usr/bin/env python3
"""Whether the review examined every changed file it was shown (#953).

The review's answer (claude-review.yml, step `claude`) carries `examined`,
one entry per changed file: `{"file": <path>, "checked": <what was
checked>}`. The files it must cover are the ones the brief showed it,
`shown-files.txt`, written by scripts/review-brief.sh (the diff's range,
lockfiles and generated files left out). A shown file with no entry is a
review that did not finish, never a clean one.

  review-examined.py missing REVIEW SHOWN
        print each file of SHOWN (one path per line) that the answer in
        REVIEW (JSON) has no `examined` entry for, one per line, and exit 1
        when any is missing; 0 when the answer covers them all; 2 when a
        file cannot be read. Paths are compared exactly, after decoding a
        name git C-quoted (`"caf\\303\\251.md"`, a non-ASCII path written
        by `git diff --name-only`, or echoed from the diff's header) and
        stripping a leading `./`.
  review-examined.py --test   self-test
"""
import json
import sys


ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def unquote(path):
    """A name as git C-quotes it (core.quotepath: a non-ASCII byte or a
    control character as an octal escape, the whole name in double
    quotes) decoded to the name itself; any other text as it is. Pure."""
    if len(path) < 2 or path[0] != '"' or path[-1] != '"':
        return path
    body, out, i = path[1:-1], bytearray(), 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out += c.encode("utf-8")
            i += 1
        elif len(octal := body[i + 1:i + 4]) == 3 and all(d in "01234567" for d in octal):
            out.append(int(octal, 8) & 0xFF)
            i += 4
        elif body[i + 1:i + 2] in ESCAPES:
            out.append(ESCAPES[body[i + 1]])
            i += 2
        else:
            return path
    return out.decode("utf-8", errors="surrogateescape")


def norm(path):
    """A path as compared: a C-quoted name decoded, a leading `./`
    stripped, nothing else. Pure."""
    p = unquote(str(path or "").strip())
    while p.startswith("./"):
        p = p[2:]
    return p


def missing(review, shown):
    """The shown files the answer has no `examined` entry for, in the
    order shown. An answer that is not an object, or has no list, misses
    every file. Pure."""
    entries = review.get("examined") if isinstance(review, dict) else None
    done = {norm(e.get("file")) for e in entries if isinstance(e, dict)} if isinstance(entries, list) else set()
    out = []
    for f in shown:
        p = norm(f)
        if p and p not in done and p not in out:
            out.append(p)
    return out


def read_shown(path):
    """The paths of a shown-files list, one per line, blanks left out."""
    with open(path, encoding="utf-8") as fh:
        return [norm(line) for line in fh if norm(line)]


def main(argv):
    if argv[:1] == ["--test"]:
        return test()
    if len(argv) != 3 or argv[0] != "missing":
        print(__doc__, file=sys.stderr)
        return 2
    try:
        with open(argv[1], encoding="utf-8") as fh:
            text = fh.read()
        shown = read_shown(argv[2])
    except OSError as e:
        print(f"review-examined.py: {e}", file=sys.stderr)
        return 2
    try:
        review = json.loads(text)
    except ValueError:
        review = None
    left = missing(review, shown)
    for f in left:
        print(f)
    return 1 if left else 0


def test():
    import os
    import subprocess
    import tempfile
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r}, want {want!r}")
        else:
            print(f"ok   {name}")

    both = {"examined": [{"file": "a.py", "checked": "x"}, {"file": "./lib/b.py", "checked": "y"}]}
    check("an answer that covers every file misses none", missing(both, ["a.py", "lib/b.py"]), [])
    check("a file with no entry is missing", missing({"examined": [{"file": "a.py", "checked": "x"}]}, ["a.py", "lib/b.py"]), ["lib/b.py"])
    check("no examined list misses every file", missing({"findings": []}, ["a.py", "b.py"]), ["a.py", "b.py"])
    check("an answer that is not an object misses every file", missing(None, ["a.py"]), ["a.py"])
    check("a leading ./ in the list is stripped", missing({"examined": [{"file": "a.py"}]}, ["./a.py"]), [])
    check("paths are compared exactly, not by suffix", missing({"examined": [{"file": "b.py"}]}, ["lib/b.py"]), ["lib/b.py"])
    check("an entry that is not an object counts for nothing", missing({"examined": ["a.py"]}, ["a.py"]), ["a.py"])
    check("nothing shown, nothing missing", missing({}, []), [])
    check("a file listed twice is named once", missing({}, ["a.py", "a.py"]), ["a.py"])
    quoted = '"docs/caf\\303\\251 \\"x\\".md"'
    check("a C-quoted name decodes to the name itself", unquote(quoted), 'docs/café "x".md')
    check("a C-quoted shown file matches its real name", missing({"examined": [{"file": 'docs/café "x".md'}]}, [quoted]), [])
    check("a C-quoted shown file matches its quoted echo", missing({"examined": [{"file": quoted}]}, [quoted]), [])
    check("a missing C-quoted file is named decoded", missing({}, [quoted]), ['docs/café "x".md'])
    check("a name in quotes that is not a C-quoted one is kept", unquote('"a\\qb"'), '"a\\qb"')
    with tempfile.TemporaryDirectory() as d:
        review, shown = os.path.join(d, "review.json"), os.path.join(d, "shown-files.txt")
        with open(review, "w", encoding="utf-8") as fh:
            json.dump({"examined": [{"file": "a.py", "checked": "x"}]}, fh)
        with open(shown, "w", encoding="utf-8") as fh:
            fh.write("a.py\n\nb.py\n")
        out = subprocess.run([sys.executable, __file__, "missing", review, shown], capture_output=True, text=True)
        check("the command names the missing file and exits 1", (out.returncode, out.stdout), (1, "b.py\n"))
        with open(shown, "w", encoding="utf-8") as fh:
            fh.write("a.py\n")
        out = subprocess.run([sys.executable, __file__, "missing", review, shown], capture_output=True, text=True)
        check("the command passes an answer that covers them all", (out.returncode, out.stdout), (0, ""))
        with open(shown, "w", encoding="utf-8") as fh:
            fh.write('a.py\n"caf\\303\\251.md"\n')
        with open(review, "w", encoding="utf-8") as fh:
            json.dump({"examined": [{"file": "a.py"}, {"file": "café.md"}]}, fh)
        out = subprocess.run([sys.executable, __file__, "missing", review, shown], capture_output=True, text=True)
        check("the command matches a C-quoted line of the list", (out.returncode, out.stdout), (0, ""))
        out = subprocess.run([sys.executable, __file__, "missing", review, os.path.join(d, "none.txt")], capture_output=True, text=True)
        check("an unreadable list exits 2", out.returncode, 2)
    if fails:
        print("\n".join(fails))
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
