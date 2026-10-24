"""#366: a failed assertion on an element that exists is read as an element
never found. Written from the report as the reproduction's writer would
(#376); it failed on the commit before the fix (e16c3f5) and passes since.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(tmp_path, message, details):
    path = tmp_path / "junit.xml"
    path.write_text('<testsuites><testsuite><testcase name="x" classname="issue-69.spec.ts">'
                    f'<failure message="{message}">{details}</failure></testcase></testsuite></testsuites>')
    return str(path)


def test_a_failed_tohavecss_on_an_element_that_exists_is_reproduced(tmp_path):
    details = ("Locator: .diluxone-users-account--guest a.diluxone-users-button\nExpected: &quot;none&quot;\n"
               "Received: &quot;underline&quot;\nCall log:\n  - Expect &quot;toHaveCSS&quot; with timeout 10000ms\n"
               "  - waiting for locator('.diluxone-users-account--guest a.diluxone-users-button')\n")
    junit = report(tmp_path, "Error: expect(locator).toHaveCSS(expected) failed", details)
    assert load("repro-ways").verdict(junit, "issue-69.spec.ts") == "reproduced"


def test_an_element_never_found_is_still_no_verdict(tmp_path):
    details = "Locator: .nope\nExpected: visible\nReceived: &lt;element(s) not found&gt;\nCall log:\n  - waiting for locator('.nope')\n"
    junit = report(tmp_path, "Error: expect(locator).toBeVisible() failed", details)
    assert load("repro-ways").verdict(junit, "issue-69.spec.ts") == "broken"
