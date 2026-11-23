"""#966: the "What waits" view fails on almost every event. `scripts/waiting.py
fetch` asked GitHub's GraphQL search for 50 issues and pull requests per page
with all their fields; the organisation grew, the first page took more than
GitHub's 10 s, GitHub answered HTTP 504 and gh printed only `unexpected end of
JSON input`. Nothing retried, so one slow page failed the job.

A fake `gh`, first on PATH, answers `api graphql` the way real gh does with
`--include`: a 504 status line and exit 1 for a page larger than it accepts,
else the next items of a 60-item organisation, as many as were asked for."""
import json
import os
import re
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import waiting  # noqa: E402

TOTAL = 60
FAKE = r'''#!/usr/bin/env python3
import json, os, re, sys
args = sys.argv[1:]
fields = {}
for i, a in enumerate(args):
    if a in ("-f", "-F", "--raw-field", "--field") and i + 1 < len(args):
        k, _, v = args[i + 1].partition("=")
        fields[k] = v
size = int(fields["first"]) if "first" in fields else int(re.search(r"first: (\d+), after", fields["query"]).group(1))
with open(os.environ["FAKE_GH_LOG"], "a") as fh:
    fh.write(f"{size}\n")
include = "--include" in args or "-i" in args
limit = int(os.environ["FAKE_GH_LIMIT"])
if size > limit:
    if include:
        sys.stdout.write("HTTP/2.0 504 Gateway Timeout\r\nContent-Type: text/html\r\n\r\n")
    sys.stderr.write("unexpected end of JSON input\n")
    sys.exit(1)
start = int(fields.get("after") or 0)
total = int(os.environ["FAKE_GH_TOTAL"])
end = min(start + size, total)
body = json.dumps({"data": {"search": {"pageInfo": {"hasNextPage": end < total, "endCursor": str(end)},
                   "nodes": [{"__typename": "Issue", "number": n} for n in range(start + 1, end + 1)]}}})
if include:
    sys.stdout.write("HTTP/2.0 200 OK\r\nContent-Type: application/json; charset=utf-8\r\n\r\n")
sys.stdout.write(body)
'''


def fake_gh(tmp_path, monkeypatch, limit):
    """A fake gh on PATH that refuses pages larger than `limit`; returns the
    file it logs each asked page size to."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(FAKE)
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    log = tmp_path / "sizes"
    log.write_text("")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    monkeypatch.setenv("FAKE_GH_LIMIT", str(limit))
    monkeypatch.setenv("FAKE_GH_TOTAL", str(TOTAL))
    return log


def fetch():
    try:
        return waiting.fetch("DiluxOne"), None
    except Exception as err:  # noqa: BLE001  at the base it raises: fail on an assertion instead
        return None, err


def sizes(log):
    return [int(s) for s in log.read_text().split()]


def test_c1_a_504_page_is_asked_again_smaller_and_every_item_comes_back(tmp_path, monkeypatch):
    # The fake refuses the first size the script asks for, whatever it is.
    log = fake_gh(tmp_path, monkeypatch, limit=10**6)
    fetch()
    first = sizes(log)[0]
    log.write_text("")
    monkeypatch.setenv("FAKE_GH_LIMIT", str(first - 1))
    items, err = fetch()
    assert err is None, f"fetch failed on a 504 of a {first}-item page instead of asking again smaller: {err}"
    numbers = [i["number"] for i in items]
    assert sorted(numbers) == list(range(1, TOTAL + 1)), numbers
    assert len(numbers) == len(set(numbers)), "an item came back twice"
    asked = sizes(log)
    assert asked[0] == first and len(asked) > 1 and asked[1] < first, asked
