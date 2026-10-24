"""Every workflow's Node (#387): wp-env 12 needs 22.13 or later, so no job
sets up an older one."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FLOOR = (22, 13)


def setup_node_versions():
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        jobs = yaml.safe_load(path.read_text(encoding="utf-8")).get("jobs") or {}
        for name, job in jobs.items():
            for step in job.get("steps") or []:
                if str(step.get("uses", "")).startswith("actions/setup-node@"):
                    yield f"{path.name} {name}", str((step.get("with") or {}).get("node-version", ""))


def version(text):
    return tuple(int(n) for n in re.findall(r"\d+", text)[:2]) + (0,) * (2 - len(re.findall(r"\d+", text)[:2]))


def test_every_setup_node_is_at_least_22_13():
    found = list(setup_node_versions())
    assert found, "no actions/setup-node step found"
    old = [(where, v) for where, v in found if version(v) < FLOOR]
    assert not old, f"Node older than 22.13 (wp-env 12 will not start): {old}"


def test_a_version_reads_as_major_and_minor():
    assert version("20") == (20, 0) < FLOOR
    assert version("22.13") == FLOOR
    assert version("24") > FLOOR
