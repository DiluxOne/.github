"""Run a workflow's step as the runner does, with stubs (#845).

A workflow's test finds its step through YAML (`step`), runs the step's
`run:` in bash (`run`) with stub commands on PATH that record their calls
(`gh`, a helper script, `sleep`), and asserts on what the step did: the
calls, its exit code and what it wrote to `$GITHUB_OUTPUT`. It never cuts
the workflow's text between two literals (scripts/literal-slices.py).

    from steps import step, run
    s = step("claude-review.yml", "scope")
    ran = run(s, tmp_path, stubs={"gh": 'echo "[]"'}, env={"PR": "8"})
    assert ran.code == 0 and ran.output["mode"] == "full"
    assert ["gh", "api", "repos/o/r/issues/8/comments", "--paginate"] in ran.calls

Not a test file: pytest collects only `test_*.py`."""
import json
import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")
# A GitHub expression's tokens, for `evaluate`.
TOKEN = re.compile(r"\s*(\|\||&&|==|!=|!|\(|\)|,|'[^']*'|[A-Za-z_][A-Za-z0-9_.*-]*)")


FUNCS = {"contains": lambda seq, x: x in seq, "startsWith": lambda s, p: s.startswith(p),
         "toJSON": lambda v: json.dumps(v), "cancelled": lambda: False, "always": lambda: True}


def evaluate(expr, ctx):
    """A GitHub expression of `==`, `!=`, `!`, `&&`, `||`, the functions in
    FUNCS, strings and context paths, on CTX ({path: value}). Pure."""
    expr, out, pos = expr.strip(), [], 0
    while pos < len(expr):
        m = TOKEN.match(expr, pos)
        assert m, f"cannot read {expr[pos:]!r}"
        tok, pos = m.group(1), m.end()
        if tok in ("&&", "||", "!"):
            out.append({"&&": " and ", "||": " or ", "!": " not "}[tok])
        elif tok in ("==", "!=", "(", ")", ","):
            out.append(tok)
        elif tok.startswith("'"):
            out.append(repr(tok[1:-1]))
        elif tok in FUNCS:
            out.append(tok)
        else:
            assert tok in ctx, f"no {tok} in the event"
            out.append(repr(ctx[tok]))
    return eval("".join(out), {"__builtins__": {}, **FUNCS})

# The stub every recorded command is: it writes its argv as one JSON line,
# then runs the body the test gave it, with the same arguments.
STUB = """#!/usr/bin/env bash
python3 -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "{name}" "$@" >> "$DX_CALLS"
{body}
"""


HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def sections(markdown):
    """{heading: body} of a markdown text, split at its headings (any level;
    a body runs to the next heading). The text before the first heading is
    under "". Pure."""
    out, name, body, fenced = {}, "", [], False
    for line in markdown.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        m = None if fenced else HEADING.match(line)
        if m:
            out[name] = "\n".join(body).strip("\n")
            name, body = m.group(2), []
        else:
            body.append(line)
    out[name] = "\n".join(body).strip("\n")
    return out


def numbered(text):
    """[item] of the numbered list items (`1. ...`, with their continuation
    lines) in TEXT, in order. Pure."""
    items, current = [], None
    for line in text.splitlines():
        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            current = [m.group(1)]
            items.append(current)
        elif current is not None and line.strip():
            current.append(line.strip())
        elif current is not None:
            current = None
    return [" ".join(i) for i in items]


def workflow(name):
    """The workflow .github/workflows/NAME (or a path from the root), as YAML."""
    path = ROOT / name if "/" in name else ROOT / ".github" / "workflows" / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def steps_of(wf, job=None):
    """[(job, step)] of a workflow (or of one of its jobs)."""
    wf = workflow(wf) if isinstance(wf, str) else wf
    return [(name, s) for name, j in (wf.get("jobs") or {}).items() if job in (None, name)
            for s in (j.get("steps") or [])]


def step(wf, key, job=None):
    """The one step whose `id` or `name` is KEY in workflow WF."""
    found = [s for _, s in steps_of(wf, job) if key in (s.get("id"), s.get("name"))]
    assert len(found) == 1, f"{len(found)} steps are `{key}` in {wf if isinstance(wf, str) else 'the workflow'}"
    return found[0]


def expand(text, exprs):
    """TEXT with each `${{ expr }}` replaced by EXPRS[expr] ('' when absent)."""
    return EXPR.sub(lambda m: str(exprs.get(m.group(1), "")), str(text))


class Ran:
    def __init__(self, proc, output, calls, temp):
        self.code, self.stdout, self.stderr = proc.returncode, proc.stdout, proc.stderr
        self.output, self.calls, self.temp = output, calls, temp

    def of(self, name):
        """The recorded calls of the stub NAME, without the name."""
        return [c[1:] for c in self.calls if c[0] == name]


def outputs(text):
    """{key: value} of a `$GITHUB_OUTPUT` file (key=value and key<<EOF)."""
    out, lines, i = {}, text.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^([A-Za-z0-9_-]+)<<(.+)$", line)
        if m:
            end = lines.index(m.group(2), i + 1)
            out[m.group(1)] = "\n".join(lines[i + 1:end])
            i = end + 1
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            out[key] = value
        i += 1
    return out


def run(s, tmp_path, env=None, stubs=None, exprs=None, files=None, central=True):
    """Run step S's `run:` in bash -eo pipefail, as the runner does.

    ENV overrides the step's `env:` (whose `${{ }}` are expanded from EXPRS);
    STUBS maps a command name to the bash body of its stub (it is on PATH
    first and records each call); FILES maps a path under the work directory
    to its text; with CENTRAL, `.dx-central` is this repository."""
    tmp_path = Path(tmp_path)
    work, bin_dir, temp = tmp_path / "work", tmp_path / "bin", tmp_path / "temp"
    for d in (work, bin_dir, temp):
        d.mkdir(parents=True, exist_ok=True)
    if central and not (work / ".dx-central").exists():
        (work / ".dx-central").symlink_to(ROOT)
    for rel, text in (files or {}).items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text, encoding="utf-8")
    for name, body in (stubs or {}).items():
        path = bin_dir / name
        path.write_text(STUB.format(name=name, body=body), encoding="utf-8")
        path.chmod(0o755)
    calls, output = tmp_path / "calls.jsonl", tmp_path / "output"
    calls.write_text("")
    output.write_text("")
    exprs = exprs or {}
    full = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "RUNNER_"))}
    full.update({k: expand(v, exprs) for k, v in (s.get("env") or {}).items()})
    full.update({"GITHUB_OUTPUT": str(output), "GITHUB_ENV": str(tmp_path / "env"), "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
                 "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "100", "GITHUB_WORKSPACE": str(work),
                 "RUNNER_TEMP": str(temp), "DX_CALLS": str(calls), "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
    full.update(env or {})
    script = tmp_path / "step.sh"
    script.write_text(expand(s["run"], exprs), encoding="utf-8")
    proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)], cwd=work, env=full,
                          capture_output=True, text=True, timeout=120)
    recorded = [json.loads(line) for line in calls.read_text().splitlines() if line.strip()]
    return Ran(proc, outputs(output.read_text()), recorded, temp)
