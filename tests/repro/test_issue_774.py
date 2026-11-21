"""#774: the release lane accepts every scenario's issue at the same moment, and
each acceptance writes its PRD seal on the receipts branch (scripts/receipts.py
`put`, #561). The branch takes one commit at a time and answers a write that
meets another with HTTP 409. Every seal must still be written: a seal lost is an
issue the autopilot then refuses as "unsealed", and no board carries the mark."""
import base64
import importlib.util
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

WRITERS = 8  # the release scenarios that fail with "unsealed" in the report
COMMIT = 0.01  # seconds one commit holds the branch
SCALE = 0.04  # a back-off of the script's seconds is slept this fraction as long
# The API path a write is put at: repos/<owner>/<repo>/contents/<path>.
CONTENTS = re.compile(r"repos/[^/]+/[^/]+/contents/(?P<path>.+)")


def load(name):
    sys.path.insert(0, str(ROOT / "scripts"))  # receipts.py imports its sibling org.py
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_seal_of_issues_accepted_at_the_same_moment_is_written():
    receipts = load("receipts")
    branch = {}
    head = threading.Lock()

    def api(*args, data=None):
        path = next(m["path"] for a in args if (m := CONTENTS.fullmatch(a)))
        if not head.acquire(blocking=False):
            raise RuntimeError("gh: is at abc but expected def (HTTP 409)")
        try:
            time.sleep(COMMIT)
            branch[path] = base64.b64decode(data["content"])
        finally:
            head.release()
        return {"content": {"path": path}}

    start = threading.Barrier(WRITERS)
    paths = [f"issues/{n}/prd-2026-11-15T00:00:00Z.json" for n in range(1, WRITERS + 1)]

    def accept(path):
        start.wait()
        try:
            receipts.put("o/r", path, {"kind": "prd-seal"}, "seal", api=api, nap=lambda s: time.sleep(s * SCALE))
        except RuntimeError:
            pass  # the seal is lost: the assertion below says which

    threads = [threading.Thread(target=accept, args=(p,)) for p in paths]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(branch) == sorted(paths)
