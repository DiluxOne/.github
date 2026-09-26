#!/usr/bin/env python3
"""The next version of a repository, from the labels of what merged.

Deterministic and auditable: nothing here reads a commit message or asks a
model. The last release is the highest tag shaped X.Y.Z (or <prefix>X.Y.Z with
--tag-prefix, `v` for this repository). Every pull request
merged into the base branch after it carries a `type:*` label the review set
(or a person corrected) and, optionally, a `version:major|minor|patch` label a
person set to force the bump. The bump is the largest one asked for:

    version:major, type:breaking -> major
    version:minor, type:feat     -> minor
    version:patch, type:fix|perf -> patch
    anything else                -> no release pending

A development build carries the version that is coming, `<next>-dev.<N>`,
where N counts the commits on the base branch since the last tag. When nothing
is pending the coming version is the next patch, because a release, when it
comes, is at least that; `pending` says which case it is.

    next-version.py [--repo OWNER/REPO] [--base main] [--tag-prefix v] [--exclude-tag X.Y.Z] [--json]
    next-version.py --test

Needs `gh` logged in (or GH_TOKEN). Exit 0 with the answer, 2 on a bad
argument, 1 when GitHub could not be read or a pull request carries a
`version:*` label that is not major, minor or patch: a version is never
guessed.
"""

import argparse
import json
import re
import subprocess
import sys

RELEASE_TAG = r"^(\d+)\.(\d+)\.(\d+)$"
BUMP_OF_TYPE = {"breaking": "major", "feat": "minor", "fix": "patch", "perf": "patch"}
RANK = {"none": 0, "patch": 1, "minor": 2, "major": 3}


def parse(tag, prefix=""):
    """(major, minor, patch) of a <prefix>X.Y.Z tag, or None."""
    tag = tag or ""
    if not tag.startswith(prefix):
        return None
    m = re.match(RELEASE_TAG, tag[len(prefix):])
    return tuple(int(x) for x in m.groups()) if m else None


def bump_of(labels):
    """The bump one pull request asks for, from its labels.

    A version:* label set by a person wins over the review's type:*.
    """
    forced = [l[len("version:"):] for l in labels if l.startswith("version:")]
    for b in forced:
        if b not in ("major", "minor", "patch"):
            raise ValueError("the label version:%s is not version:major, version:minor or version:patch" % b)
    if forced:
        return max(forced, key=RANK.__getitem__)
    types = [l[len("type:"):] for l in labels if l.startswith("type:")]
    return max((BUMP_OF_TYPE.get(t, "none") for t in types), key=RANK.__getitem__, default="none")


def apply(version, bump):
    major, minor, patch = version
    if bump == "major":
        return (major + 1, 0, 0)
    if bump == "minor":
        return (major, minor + 1, 0)
    if bump == "patch":
        return (major, minor, patch + 1)
    return version


def decide(last, pulls, commits_since):
    """The answer, from data only. `pulls` is [(number, [labels])]."""
    per_type = {}
    bump = "none"
    for number, labels in pulls:
        try:
            b = bump_of(labels)
        except ValueError as e:
            raise ValueError("#%d: %s" % (number, e))
        per_type.setdefault(b, []).append(number)
        if RANK[b] > RANK[bump]:
            bump = b
    pending = bump != "none"
    nxt = apply(last, bump if pending else "patch")
    fmt = lambda v: "%d.%d.%d" % v
    return {
        "last": fmt(last),
        "bump": bump,
        "pending": pending,
        "next": fmt(nxt),
        "dev": "%s-dev.%d" % (fmt(nxt), commits_since),
        "commits_since": commits_since,
        "pulls": {k: sorted(v) for k, v in per_type.items()},
    }


def gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        sys.stderr.write(out.stderr)
        sys.exit(1)
    return out.stdout


def read_github(repo, base, prefix, exclude=None):
    """The facts from GitHub. `exclude` is a tag to leave out of the search
    for the last release: the one being released right now, when it exists."""
    tags = json.loads(gh("api", "repos/%s/tags" % repo, "--paginate", "--slurp"))
    versions = [v for page in tags for v in (parse(t["name"], prefix) for t in page if t["name"] != exclude) if v]
    last = max(versions) if versions else (0, 0, 0)
    if versions:
        compare = json.loads(gh("api", "repos/%s/compare/%s%d.%d.%d...%s" % ((repo, prefix) + last + (base,))))
        commits_since = int(compare["ahead_by"])
        shas = {c["sha"] for c in compare["commits"]}
        # compare lists at most 250 commits; past that the count is still
        # right, and the pull requests are then taken by merge date alone.
        shas = shas if len(shas) == commits_since else None
        merged_after = compare["base_commit"]["commit"]["committer"]["date"]
    else:
        # No release yet: every merged pull request counts, and N counts
        # every commit on the branch (the last page number at one per page).
        head = gh("api", "-i", "repos/%s/commits?sha=%s&per_page=1" % (repo, base))
        m = re.search(r'[?&]page=(\d+)>; rel="last"', head)
        commits_since = int(m.group(1)) if m else 1
        shas, merged_after = None, None
    pages = json.loads(gh("api", "repos/%s/pulls?state=closed&base=%s&per_page=100" % (repo, base), "--paginate", "--slurp"))
    pulls = []
    for p in (p for page in pages for p in page):
        if not p.get("merged_at"):
            continue
        if shas is not None:
            if p.get("merge_commit_sha") not in shas:
                continue
        elif merged_after and not p["merged_at"] > merged_after:
            # Past what compare lists: by date, strictly after the tag's commit.
            continue
        pulls.append((p["number"], [l["name"] for l in p["labels"]]))
    return last, sorted(pulls), commits_since


def self_test():
    import unittest

    class T(unittest.TestCase):
        def test_parse(self):
            self.assertEqual(parse("1.2.3"), (1, 2, 3))
            self.assertIsNone(parse("v1.2.3"))
            self.assertEqual(parse("v1.2.3", "v"), (1, 2, 3))
            self.assertIsNone(parse("1.2.3", "v"))
            self.assertIsNone(parse("1.2.3-rc1"))
            self.assertIsNone(parse("1.2"))

        def test_bump_of(self):
            self.assertEqual(bump_of(["type:feat", "risk:low"]), "minor")
            self.assertEqual(bump_of(["type:fix"]), "patch")
            self.assertEqual(bump_of(["type:perf"]), "patch")
            self.assertEqual(bump_of(["type:breaking"]), "major")
            self.assertEqual(bump_of(["type:docs"]), "none")
            self.assertEqual(bump_of([]), "none")
            self.assertEqual(bump_of(["type:docs", "version:major"]), "major")
            self.assertEqual(bump_of(["type:breaking", "version:patch"]), "patch")
            with self.assertRaises(ValueError):
                bump_of(["version:nonsense", "type:breaking"])

        def test_decide(self):
            d = decide((1, 0, 0), [(4, ["type:test"]), (5, ["type:ci"]), (6, ["type:ci"])], 3)
            self.assertEqual((d["bump"], d["pending"], d["next"], d["dev"]), ("none", False, "1.0.1", "1.0.1-dev.3"))
            d = decide((1, 0, 0), [(7, ["type:feat"]), (8, ["type:fix"])], 5)
            self.assertEqual((d["bump"], d["next"], d["dev"]), ("minor", "1.1.0", "1.1.0-dev.5"))
            self.assertEqual(d["pulls"], {"minor": [7], "patch": [8]})
            d = decide((1, 0, 0), [(7, ["type:feat"]), (9, ["type:docs", "version:major"])], 2)
            self.assertEqual(d["next"], "2.0.0")
            d = decide((2, 3, 4), [(1, ["type:fix"])], 1)
            self.assertEqual(d["next"], "2.3.5")
            d = decide((0, 0, 0), [], 0)
            self.assertEqual((d["last"], d["next"], d["dev"]), ("0.0.0", "0.0.1", "0.0.1-dev.0"))

        def test_monotonic(self):
            # A bigger bump only ever raises the coming version.
            last = (1, 4, 2)
            versions = [decide(last, [(1, ["type:" + t])], 1)["next"] for t in ("docs", "fix", "feat", "breaking")]
            self.assertEqual(versions, ["1.4.3", "1.4.3", "1.5.0", "2.0.0"])
            self.assertEqual(sorted(versions, key=lambda v: tuple(map(int, v.split(".")))), versions)

    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(T))
    sys.exit(0 if result.wasSuccessful() else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", help="OWNER/REPO (default: the repository of the current directory)")
    ap.add_argument("--base", default="main")
    ap.add_argument("--tag-prefix", default="", help="what precedes X.Y.Z in the release tags (this repository: v)")
    ap.add_argument("--exclude-tag", default=None, help="a tag to ignore when looking for the last release: the one being released")
    ap.add_argument("--json", action="store_true", help="print the answer as JSON")
    ap.add_argument("--test", action="store_true", help="run the self-tests and exit")
    a = ap.parse_args()
    if a.test:
        self_test()
    repo = a.repo or gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()
    last, pulls, commits_since = read_github(repo, a.base, a.tag_prefix, a.exclude_tag)
    try:
        d = decide(last, pulls, commits_since)
    except ValueError as e:
        sys.stderr.write("error: %s\n" % e)
        sys.exit(1)
    if a.json:
        print(json.dumps(d, indent=2))
        return
    print("last release: %s" % d["last"])
    for b in ("major", "minor", "patch", "none"):
        if d["pulls"].get(b):
            print("  %-6s %s" % (b, ", ".join("#%d" % n for n in d["pulls"][b])))
    if d["pending"]:
        print("pending: a %s release, %s" % (d["bump"], d["next"]))
    else:
        print("pending: nothing to release (the next patch would be %s)" % d["next"])
    print("dev build: %s (%d commits since %s)" % (d["dev"], d["commits_since"], d["last"]))


if __name__ == "__main__":
    main()
