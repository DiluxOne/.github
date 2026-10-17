#!/usr/bin/env python3
"""The version in production, which a security patch starts from (#247).

A security fix is applied to the last version in production, never to the
default branch with whatever has piled up there since. A version is in
production when it is a published GitHub release, not a draft and not a
pre-release, whose tag is a plain X.Y.Z (with or without a `v`), the highest
such one. Where the repository's kind publishes somewhere else as well
(`release.stable` in its pack: wordpress.org's stable version for a
WordPress plugin), that place must say the same version; when it does not,
there is no version in production to patch, and a person settles it.

  production-version.py --kind KIND [--repo OWNER/REPO] [--slug SLUG] [--json]
      prints the version, its tag and the patch after it; exit 1, saying
      why, when there is none or the two places disagree
  production-version.py --test

Environment: GH_TOKEN (contents: read). The kind and the pack are read from
the checkout of DiluxOne/.github this script lives in.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def production(releases):
    """(tag, (x, y, z)) of the highest published, non-draft, non-pre-release
    plain X.Y.Z release, or None."""
    best = None
    for r in releases:
        if r.get("draft") or r.get("prerelease"):
            continue
        m = TAG.match(r.get("tag_name") or "")
        if not m:
            continue
        v = tuple(int(x) for x in m.groups())
        if best is None or v > best[1]:
            best = (r["tag_name"], v)
    return best


def decide(releases, stable):
    """(result, why). stable: None when the kind publishes nowhere else, ""
    when it publishes nothing yet, or the version it publishes."""
    best = production(releases)
    if not best:
        return None, "no published X.Y.Z release that is not a draft nor a pre-release"
    tag, v = best
    version = ".".join(map(str, v))
    if stable is not None and stable != version:
        where = "nothing is published there" if stable == "" else f"it says {stable}"
        return None, f"the last release is {version}, but {where}: a person settles which one is in production"
    return {"tag": tag, "version": version, "patch": f"{v[0]}.{v[1]}.{v[2] + 1}"}, "ok"


def pack_stable(kind):
    """The kind's `release.stable`, or None when the kind names none. A kind
    asked for that cannot be read fails: the check is never skipped quietly."""
    if not re.fullmatch(r"[a-z0-9-]+", kind or ""):
        raise ValueError(f"not a kind: {kind!r}")
    import yaml  # an ImportError fails too
    path = os.path.join(HERE, "..", "kinds", kind, "pack.yml")
    if not os.path.isfile(path):
        raise ValueError(f"no pack for the kind {kind!r}")
    with open(path, encoding="utf-8") as fh:
        return ((yaml.safe_load(fh) or {}).get("release") or {}).get("stable")


def fetch_stable(spec, slug, opener=urllib.request.urlopen):
    """The version the pack's place publishes: "" when it publishes nothing
    (404 or no field); an error that is not a 404 raises."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug or ""):
        raise ValueError(f"not a slug: {slug!r}")
    url = spec["url"].replace("{slug}", slug)
    try:
        with opener(url, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return ""
        raise
    if not isinstance(data, dict) or data.get("error"):
        return ""
    return str(data.get(spec.get("field") or "version") or "")


def releases(repo):
    out = subprocess.run(["gh", "api", f"repos/{repo}/releases", "--paginate", "--jq", ".[]"], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return [json.loads(l) for l in out.stdout.splitlines() if l.strip()]


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    rel = [{"tag_name": "1.4.0", "prerelease": True}, {"tag_name": "dev", "prerelease": True},
           {"tag_name": "1.3.0"}, {"tag_name": "1.10.2"}, {"tag_name": "1.9.9"},
           {"tag_name": "2.0.0", "draft": True}, {"tag_name": "1.11.0-rc.1"}, {"tag_name": "1.10.2-dev.3"}]
    check("the highest plain X.Y.Z that is neither a draft nor a pre-release, numerically", production(rel), ("1.10.2", (1, 10, 2)))
    check("a `v` prefix counts and is kept", production([{"tag_name": "v5.19.0"}, {"tag_name": "v5.9.0"}]), ("v5.19.0", (5, 19, 0)))
    check("nothing published is no version", decide([{"tag_name": "dev", "prerelease": True}], None)[0], None)
    check("the patch is the next Z", decide(rel, None)[0], {"tag": "1.10.2", "version": "1.10.2", "patch": "1.10.3"})
    check("the other place agreeing keeps it", decide(rel, "1.10.2")[0]["version"], "1.10.2")
    check("the other place disagreeing is no version, and says both",
          (decide(rel, "1.9.9")[0], "1.10.2" in decide(rel, "1.9.9")[1], "1.9.9" in decide(rel, "1.9.9")[1]), (None, True, True))
    check("nothing published there is no version", decide(rel, "")[0], None)

    class Resp:
        def __init__(self, body):
            self.body = body
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return self.body.encode()
    spec = {"url": "https://x/?s={slug}", "field": "version"}
    seen = []
    check("fetch_stable: the field, from the url with the slug", fetch_stable(spec, "diluxone-users", lambda u, timeout: seen.append(u) or Resp('{"version": "1.2.0"}')), "1.2.0")
    check("fetch_stable: the slug goes into the url", seen, ["https://x/?s=diluxone-users"])
    check("fetch_stable: an error answer is nothing published", fetch_stable(spec, "a", lambda u, timeout: Resp('{"error": "Plugin not found."}')), "")
    def nf(u, timeout):
        raise urllib.error.HTTPError(u, 404, "nf", {}, None)
    check("fetch_stable: a 404 is nothing published", fetch_stable(spec, "a", nf), "")
    def boom(u, timeout):
        raise urllib.error.HTTPError(u, 502, "bad", {}, None)
    try:
        fetch_stable(spec, "a", boom)
        check("fetch_stable: another error fails, never reads as nothing published", "no error", "an error")
    except urllib.error.HTTPError:
        check("fetch_stable: another error fails, never reads as nothing published", True, True)
    try:
        fetch_stable(spec, "../x")
        check("fetch_stable: a slug that is not one is refused", "no error", "an error")
    except ValueError:
        check("fetch_stable: a slug that is not one is refused", True, True)
    for bad in ("", "../x", "no-such-kind"):
        try:
            pack_stable(bad)
            check(f"pack_stable: {bad!r} fails, never skips the check", "no error", "an error")
        except ValueError:
            check(f"pack_stable: {bad!r} fails, never skips the check", True, True)
    real = pack_stable("wordpress-plugin")
    check("the WordPress pack checks against wordpress.org's version", ("api.wordpress.org" in real["url"], "{slug}" in real["url"], real["field"]), (True, True, "version"))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--slug", default="")
    ap.add_argument("--kind", required=True, help="the repository's kind (its pack says where else production is published)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        spec = pack_stable(a.kind)
    except (ValueError, ImportError) as exc:
        print(f"the kind's pack cannot be read ({exc}): no version is trusted unchecked", file=sys.stderr)
        return 1
    stable = None
    if spec:
        if not a.slug:
            print(f"the {a.kind} kind checks the version in production against {spec['url']}: --slug is needed", file=sys.stderr)
            return 1
        stable = fetch_stable(spec, a.slug)
    result, why = decide(releases(a.repo), stable)
    if not result:
        print(why, file=sys.stderr)
        return 1
    print(json.dumps(result) if a.json else result["version"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
