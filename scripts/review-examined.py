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
        file cannot be read. Paths are compared exactly, after stripping a
        leading `./`.
  review-examined.py --test   self-test
"""
import json
import sys


def norm(path):
    """A path as compared: a leading `./` stripped, nothing else. Pure."""
    p = str(path or "").strip()
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
        out = subprocess.run([sys.executable, __file__, "missing", review, os.path.join(d, "none.txt")], capture_output=True, text=True)
        check("an unreadable list exits 2", out.returncode, 2)
    if fails:
        print("\n".join(fails))
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
