"""#558: in a repository other than DiluxOne/.github the autopilot's Spec prompt
does not stop for a path under scripts/, kinds/ or policy/: a person merges it."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_product_repository_s_fix_under_scripts_is_not_a_reason_to_stop():
    autopilot = load("autopilot")
    prompt = autopilot.prompt_spec("DiluxOne/diluxone-fm", 267, "### Problem\n\nx")

    assert "a path under .github/, policy/, scripts/ or kinds/" not in prompt
    assert "a person merges" in prompt
