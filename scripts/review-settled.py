#!/usr/bin/env python3
"""A review finding settled outside the code (#699 C5).

Someone who decides answers a review finding with a decision outside the
code (a sub-issue, a choice the PRD leaves to them): review-reply.yml's
reply says so, and carries this hidden mark, written by dilux-bot, which
names the finding, the answer and the head it was settled at. The review
then runs again on the same head: claude-review.yml does not reuse its
verdict while a settlement newer than it exists, and passes the settled
findings to the reviewer with the settled threads, so it does not raise
them again.

  review-settled.py mark FINDING URL SHA   the mark, one line, for the reply
  review-settled.py read SHA               COMMENTS (a JSON file: the pull
        request's comments and review comments, as the REST API lists
        them), BOT (dilux-bot's login: no one else's mark counts), RECORD
        (a JSON file: the review's last record): JSON {ids, newer,
        threads}: the marks at SHA, whether one is newer than the record
        (not in its `settled`), and the settled findings for the brief
  review-settled.py --test                 self-test
"""
import json
import os
import re
import sys

MARK_RE = re.compile(r"<!-- dx-settled (\{.*?\}) -->")


def mark(finding, url, sha):
    """The hidden mark: JSON no comment can close. Pure."""
    data = json.dumps({"finding": str(finding)[:300], "url": str(url)[:300], "sha": str(sha)[:40]}, ensure_ascii=False)
    return "<!-- dx-settled " + data.replace("<", "\\u003c").replace(">", "\\u003e").replace("--", "-\\u002d") + " -->"


def settlements(comments, bot, sha):
    """The marks dilux-bot wrote at SHA: [{id, finding, url}], in order.
    Pure."""
    out = []
    for c in comments or []:
        if ((c.get("user") or {}).get("login") or "") != bot:
            continue
        for m in MARK_RE.finditer(c.get("body") or ""):
            try:
                data = json.loads(m.group(1))
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("sha") == sha:
                out.append({"id": c.get("id"), "finding": str(data.get("finding") or ""), "url": str(data.get("url") or "")})
    return out


def read(comments, bot, sha, record):
    """{ids, newer, threads}: whether a settlement at SHA is newer than the
    review's record (its `settled` ids), and the settled findings as the
    brief's settled threads read them. Pure."""
    found = settlements(comments, bot, sha)
    seen = set((record or {}).get("settled") or []) if isinstance(record, dict) else set()
    ids = [s["id"] for s in found]
    threads = [{"path": None, "line": None, "finding": s["finding"],
                "replies": [{"author": "someone who decides", "body": f"Settled outside the code: {s['url']}"}]} for s in found]
    return {"ids": ids, "newer": any(i not in seen for i in ids), "threads": threads}


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        if got == want:
            print(f"ok   {name}")
        else:
            print(f"FAIL {name}: got {got!r}, want {want!r}")
            failed = 1

    m = mark("Credits <!-- x --> are wrong", "https://github.com/o/r/pull/9#issuecomment-1", "a" * 40)
    check("the mark is one hidden comment, whatever the finding says", (m.count("<!--"), m.count("-->"), "\n" in m), (1, 1, False))
    bot = "dilux-bot[bot]"
    c = lambda i, body, who=bot: {"id": i, "user": {"login": who}, "body": body}
    got = settlements([c(1, "ok\n\n" + m), c(2, m, "mallory"), c(3, mark("x", "u", "b" * 40))], bot, "a" * 40)
    check("only dilux-bot's marks, at this head, are read back as written",
          (got, ), ([{"id": 1, "finding": "Credits <!-- x --> are wrong", "url": "https://github.com/o/r/pull/9#issuecomment-1"}], ))
    r = read([c(1, m)], bot, "a" * 40, {"sha": "a" * 40, "settled": []})
    check("a settlement the record did not read is newer: the review runs again", (r["ids"], r["newer"]), ([1], True))
    check("one it read is not", read([c(1, m)], bot, "a" * 40, {"settled": [1]})["newer"], False)
    check("none, or an old record with no list: nothing newer, or every one", (read([], bot, "a" * 40, {})["newer"], read([c(1, m)], bot, "a" * 40, None)["newer"]), (False, True))
    check("the settled findings, as the brief's settled threads", r["threads"][0]["finding"], "Credits <!-- x --> are wrong")
    if not failed:
        print("all tests passed")
    return failed


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv[:1] == ["mark"] and len(argv) == 4:
        print(mark(*argv[1:]))
        return 0
    if argv[:1] == ["read"] and len(argv) == 2:
        def load(key, default):
            try:
                with open(os.environ.get(key) or "", encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, ValueError):
                return default
        print(json.dumps(read(load("COMMENTS", []), os.environ.get("BOT", ""), argv[1], load("RECORD", None))))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
