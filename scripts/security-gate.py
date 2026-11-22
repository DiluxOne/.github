#!/usr/bin/env python3
"""The security gate (#956): one deterministic check for every repository.

Leaked secrets (gitleaks), insecure code with the OWASP Top 10 and language
rules (Semgrep), dependencies with known vulnerabilities (osv-scanner) and
GitHub workflows (zizmor), on what the change adds or modifies. It runs the
same way in `make pre-pr` (dx.mk, scripts/pre-pr.py render), in the pull
request's check (.github/workflows/security-gate.yml) and for the review's
brief (review-brief.sh SECURITY=). What it runs (the tools pinned to a
version and a SHA-256, the rules, the severities, the caps) is data in
policy/security-gate.yml; a kind adds rules or excludes paths in its pack's
`security:` key. No kind is named here.

Each finding is one of:
  new           on a line the change adds or modifies; for osv-scanner, a
                vulnerability the head's lockfile has and the base's has not
  pre-existing  anything else: listed, never failing the gate
  suppressed    matched by an entry of the repository's
                .github/review-suppressions.yml ({rule, file, fingerprint,
                reason}, the same file as the review rules' `sniff` entries)

The setting is org.yml `security-gate`: `off` runs nothing, `report` always
exits 0, `block` exits 1 on a new finding of a level in the policy's
`block` (critical, high).

  security-gate.py install          download the pinned tools and rules into
                                    ${XDG_CACHE_HOME:-~/.cache}/dx/security-gate/<digest>,
                                    checking each SHA-256; nothing under `off`
  security-gate.py run [--base REF] [--json OUT] [--mode MODE] [--repo DIR]
                                    the gate on DIR (.) against the merge
                                    base of REF (DX_BASE, else origin/HEAD,
                                    origin/main or main) and HEAD: the
                                    report (the most severe first, capped),
                                    the full result as JSON in OUT
  security-gate.py report FILE      the capped report of a result's JSON
  security-gate.py mode             the setting: off, report or block
  security-gate.py where            the cache directory of this policy
  security-gate.py --test           self-test
"""
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CENTRAL = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import policy as pol  # noqa: E402  the YAML reader and the packs (scripts/policy.py)

POLICY = os.path.join(CENTRAL, "policy", "security-gate.yml")
SUPPRESSIONS = os.path.join(".github", "review-suppressions.yml")
MODES = ("off", "report", "block")
LEVELS = ("critical", "high", "medium", "low")
STATUSES = ("new", "pre-existing", "suppressed")
TOOLS = ("gitleaks", "semgrep", "osv-scanner", "zizmor")
# The lockfiles osv-scanner reads, by name (its extractors').
LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock",
             "Pipfile.lock", "poetry.lock", "uv.lock", "pdm.lock", "requirements.txt", "go.mod", "Cargo.lock",
             "Gemfile.lock", "gradle.lockfile", "pom.xml", "mix.lock", "pubspec.lock", "packages.lock.json",
             "conan.lock", "renv.lock", "bun.lock", "deno.lock"}
WORKFLOW_RE = re.compile(r"^(?:\.github/workflows/[^/]+|(?:.*/)?action)\.ya?ml$")
CLASSES = ("leaked secrets, the OWASP Top 10 patterns its Semgrep rules cover, dependencies with known "
           "vulnerabilities and unsafe GitHub workflows")


def load_policy(path=POLICY):
    data = pol.load_yaml(path)
    if not isinstance(data, dict) or not data.get("tools"):
        raise SystemExit(f"security-gate: {path} has no `tools`")
    return data


# --- the setting -------------------------------------------------------------

def mode_of(org_conf):
    """org.yml `security-gate`: off, report or block (report when unset)."""
    value = (org_conf or {}).get("security-gate")
    value = "report" if value in (None, "") else str(value)
    if value not in MODES:
        raise ValueError(f"org.yml `security-gate` is `{value}`: off, report or block")
    return value


def mode():
    return mode_of(pol.load_yaml(os.path.join(CENTRAL, "org.yml")))


# --- install -----------------------------------------------------------------

def platform_key(system=None, machine=None):
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)
    return f"{system}-{arch}"


def digest(data):
    """The cache's name for a policy: what it downloads, hashed. Pure."""
    what = {"tools": data.get("tools"), "rules": data.get("rules")}
    return hashlib.sha256(json.dumps(what, sort_keys=True).encode()).hexdigest()[:16]


def cache_dir(data, env=os.environ):
    base = env.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "dx", "security-gate", digest(data))


def installed(data, env=os.environ):
    marker = os.path.join(cache_dir(data, env), "installed")
    return os.path.isfile(marker) and open(marker).read().strip() == digest(data)


def fetch(url, sha256):
    """The bytes at URL, or SystemExit when their SHA-256 is not SHA256."""
    req = urllib.request.Request(url, headers={"User-Agent": "dx-security-gate"})
    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310  a pinned https URL
        body = resp.read()
    got = hashlib.sha256(body).hexdigest()
    if got != sha256:
        raise SystemExit(f"security-gate: {url} has SHA-256 {got}, not the pinned {sha256}: refusing it")
    return body


def install_tool(name, tool, where, key, python=sys.executable):
    builds = tool.get("builds") or {}
    if key not in builds:
        raise SystemExit(f"security-gate: {name} {tool['version']} has no pinned build for {key} (policy/security-gate.yml)")
    build = builds[key]
    url = str(tool["url"]).format(version=tool["version"], asset=build["asset"])
    body = fetch(url, build["sha256"])
    bindir = os.path.join(where, "bin")
    os.makedirs(bindir, exist_ok=True)
    target = os.path.join(bindir, tool["binary"])
    kind = tool.get("kind")
    if kind == "binary":
        with open(target, "wb") as fh:
            fh.write(body)
    elif kind == "tarball":
        with tarfile.open(fileobj=io.BytesIO(body)) as tar:
            member = next((m for m in tar.getmembers() if m.isfile() and os.path.basename(m.name) == tool["binary"]), None)
            if member is None:
                raise SystemExit(f"security-gate: {url} holds no {tool['binary']}")
            with open(target, "wb") as fh:
                fh.write(tar.extractfile(member).read())
    elif kind == "wheel" and not tool.get("pip"):
        with zipfile.ZipFile(io.BytesIO(body)) as whl:
            member = next((n for n in whl.namelist() if re.search(r"\.data/scripts/" + re.escape(tool["binary"]) + "$", n)), None)
            if member is None:
                raise SystemExit(f"security-gate: {url} holds no {tool['binary']}")
            with open(target, "wb") as fh:
                fh.write(whl.read(member))
    elif kind == "wheel":
        wheel = os.path.join(where, url.rsplit("/", 1)[1])
        with open(wheel, "wb") as fh:
            fh.write(body)
        lib = os.path.join(where, name)
        subprocess.run([python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-input", "--ignore-installed",
                        "--target", lib, wheel], check=True)
        os.remove(wheel)
        with open(target, "w") as fh:
            fh.write("#!/bin/sh\n# The pinned " + name + " (scripts/security-gate.py install).\n"
                     f'PATH="{lib}/bin:$PATH" PYTHONPATH="{lib}" exec "{python}" -c '
                     "'import sys; from semgrep.console_scripts.entrypoint import main; sys.exit(main())' \"$@\"\n"
                     if name == "semgrep" else
                     f'PYTHONPATH="{lib}" exec "{lib}/bin/{tool["binary"]}" "$@"\n')
    else:
        raise SystemExit(f"security-gate: {name}: unknown kind {kind!r}")
    os.chmod(target, 0o755)


def install_rules(rules, where):
    body = fetch(str(rules["url"]).format(commit=rules["commit"]), rules["sha256"])
    out = os.path.join(where, "rules")
    shutil.rmtree(out, ignore_errors=True)
    langs = set(rules.get("languages") or [])
    exclude = [str(x).strip("/") + "/" for x in rules.get("exclude") or []]
    kept = 0
    with tarfile.open(fileobj=io.BytesIO(body)) as tar:
        for m in tar.getmembers():
            rel = m.name.split("/", 1)[1] if "/" in m.name else ""
            parts = rel.split("/")
            if (not m.isfile() or parts[0] not in langs or "security" not in parts[1:-1]
                    or not re.search(r"\.ya?ml$", rel) or re.search(r"\.(test|fixed)\.ya?ml$", rel)
                    or any(rel.startswith(e) for e in exclude)):
                continue
            path = os.path.join(out, *parts)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(tar.extractfile(m).read())
            kept += 1
    if not kept:
        raise SystemExit("security-gate: the rules tarball holds no rule for the languages listed")
    return kept


def install(data, env=os.environ):
    where = cache_dir(data, env)
    if installed(data, env):
        print(f"security-gate: the pinned tools are in {where}")
        return 0
    os.makedirs(where, exist_ok=True)
    key = platform_key()
    for name in TOOLS:
        install_tool(name, data["tools"][name], where, key)
        print(f"security-gate: {name} {data['tools'][name]['version']} installed, SHA-256 checked")
    kept = install_rules(data["rules"], where)
    print(f"security-gate: {kept} Semgrep rule files from semgrep-rules@{data['rules']['commit'][:12]}, SHA-256 checked")
    with open(os.path.join(where, "installed"), "w") as fh:
        fh.write(digest(data) + "\n")
    return 0


# --- the change --------------------------------------------------------------

def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=check).stdout


def default_base(repo, env=os.environ):
    """DX_BASE when set (the autopilot's and `dx check`'s), else the first
    of origin/HEAD, origin/main, main that exists."""
    for ref in ([env["DX_BASE"]] if env.get("DX_BASE") else []) + ["origin/HEAD", "origin/main", "main", "origin/master", "master"]:
        if subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "-q", ref + "^{commit}"], capture_output=True).returncode == 0:
            return ref
    raise SystemExit("security-gate: no base to compare with (origin/HEAD, origin/main or main): pass --base REF")


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def added_lines(diff):
    """{path: set(line)} of the lines a `git diff -U0` adds or modifies, by
    their number at the head; a deleted file is left out. Pure."""
    out, path = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:]
            path = None if name == "/dev/null" else (name[2:] if name.startswith("b/") else name)
            if path is not None:
                out.setdefault(path, set())
            continue
        m = HUNK.match(line)
        if m and path is not None:
            start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            out[path].update(range(start, start + count))
    return out


def fingerprint(code):
    """The first 12 hex digits of the SHA-1 of a line, whitespace collapsed:
    the review rules' fingerprint, of one line. Pure."""
    return hashlib.sha1(" ".join(str(code).split()).encode()).hexdigest()[:12]


def kind_of(repo):
    own = pol.load_yaml(os.path.join(repo, ".github", "review-policy.yml"))
    return (own if isinstance(own, dict) else {}).get("kind")


def pack_security(kind):
    """The kind's pack `security:` ({rules: [path], exclude: [glob]}), {} for none."""
    if not kind or not os.path.isfile(pol.pack_path(str(kind))):
        return {}
    sec = pol.load_yaml(pol.pack_path(str(kind))).get("security") or {}
    return sec if isinstance(sec, dict) else {}


# --- the tools' outputs, as findings -----------------------------------------

CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f  ]")


def clean(text, limit=300):
    """Text from a tool, safe in the brief: no control characters, no
    backticks (they would close the fence), one line, capped. Pure."""
    text = " ".join(CTRL.sub(" ", str(text or "")).replace("`", "'").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def level(table, value):
    table = table or {}
    return str(table.get(str(value), table.get(str(value).upper(), table.get("default", "medium"))))


def from_gitleaks(report, sev):
    out = []
    for f in report or []:
        out.append({"tool": "gitleaks", "rule": "gitleaks." + str(f.get("RuleID") or "secret"), "file": f.get("File") or "",
                    "line": int(f.get("StartLine") or 0), "severity": level(sev, "default"),
                    "message": clean(f.get("Description") or "A secret"),
                    "fix": "Take it out, rotate it, and read it from the environment or a secret store."})
    return out


def rule_id(check_id, configs=()):
    """Semgrep's check id without the dotted path of the configuration it
    came from (/home/x/rules/python/a.yaml's rule r is
    home.x.rules.python.r): the rule's own path in its rules. Pure."""
    check_id = str(check_id or "semgrep")
    for c in configs:
        dotted = ".".join(p for p in str(c).split(os.sep) if p) + "."
        if check_id.startswith(dotted):
            return check_id[len(dotted):]
    return check_id


def from_semgrep(report, sev, configs=()):
    out = []
    for r in (report or {}).get("results") or []:
        extra = r.get("extra") or {}
        meta = extra.get("metadata") or {}
        refs = meta.get("references") or []
        fix = extra.get("fix")
        fix = f"Replace it with: {fix}" if fix else ("See " + str(refs[0]) if refs else "Rewrite the line so the rule's pattern no longer holds.")
        out.append({"tool": "semgrep", "rule": rule_id(r.get("check_id"), configs), "file": r.get("path") or "",
                    "line": int((r.get("start") or {}).get("line") or 0), "severity": level(sev, extra.get("severity")),
                    "message": clean(extra.get("message")), "fix": clean(fix)})
    return out


def osv_level(sev, vuln, group_max):
    named = ((vuln.get("database_specific") or {}).get("severity") or "")
    if named:
        return level(sev, named)
    try:
        score = float(group_max)
    except (TypeError, ValueError):
        return level(sev, "default")
    return "critical" if score >= 9 else "high" if score >= 7 else "medium" if score >= 4 else "low"


def fixed_versions(vuln, name):
    out = []
    for aff in vuln.get("affected") or []:
        if (aff.get("package") or {}).get("name") not in (None, name):
            continue
        for rng in aff.get("ranges") or []:
            out += [str(e["fixed"]) for e in rng.get("events") or [] if e.get("fixed")]
    return out


def from_osv(report, sev, lines_of=None):
    """Findings of osv-scanner's JSON; LINES_OF(file) gives the lockfile's
    lines, to point at the package's."""
    out = []
    for res in (report or {}).get("results") or []:
        path = (res.get("source") or {}).get("path") or ""
        lines = lines_of(path) if lines_of else []
        for pkg in res.get("packages") or []:
            p = pkg.get("package") or {}
            name, version = str(p.get("name") or ""), str(p.get("version") or "")
            groups = pkg.get("groups") or []
            line = next((i + 1 for i, text in enumerate(lines) if name and name in text), 0)
            for v in pkg.get("vulnerabilities") or []:
                vid = str(v.get("id") or "")
                group = next((g for g in groups if vid in (g.get("ids") or []) or vid in (g.get("aliases") or [])), {})
                fixes = fixed_versions(v, name)
                fix = (f"Upgrade {name} to {fixes[-1]} or later." if fixes else f"No fixed version of {name} yet: replace it or remove it.")
                out.append({"tool": "osv-scanner", "rule": vid, "file": path, "line": line, "package": f"{name}@{version}",
                            "severity": osv_level(sev, v, group.get("max_severity")),
                            "message": clean(f"{name} {version}: {v.get('summary') or vid}"), "fix": clean(fix)})
    return out


def from_zizmor(report, sev):
    out = []
    for f in report or []:
        loc = next((l for l in f.get("locations") or [] if (l.get("symbolic") or {}).get("kind") == "Primary"),
                   (f.get("locations") or [{}])[0])
        key = ((loc.get("symbolic") or {}).get("key") or {}).get("Local") or {}
        path = key.get("given_path") or key.get("verbatim_path") or key.get("prefix") or ""
        point = ((loc.get("concrete") or {}).get("location") or {}).get("start_point") or {}
        severity = (f.get("determinations") or {}).get("severity")
        out.append({"tool": "zizmor", "rule": "zizmor." + str(f.get("ident") or "audit"), "file": path,
                    "line": int(point.get("row") or 0) + 1, "severity": level(sev, severity),
                    "message": clean(f.get("desc") or (loc.get("symbolic") or {}).get("annotation")),
                    "fix": clean("Pass the value through env: and read it as a shell variable; see " + str(f.get("url") or "zizmor's docs")
                                 if f.get("ident") == "template-injection" else "See " + str(f.get("url") or "zizmor's documentation"))})
    return out


# --- running them ------------------------------------------------------------

def tool_path(name, data, env=os.environ):
    """The pinned tool from the cache, else NAME on PATH (the self-test's
    stubs; `install` puts the pinned one first)."""
    pinned = os.path.join(cache_dir(data, env), "bin", data["tools"][name]["binary"])
    return pinned if os.path.isfile(pinned) else (shutil.which(name, path=env.get("PATH")) or name)


def call(argv, timeout, env=None, cwd=None):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd)
    except FileNotFoundError:
        raise SystemExit(f"security-gate: {argv[0]} is not installed: run `security-gate.py install`")
    except subprocess.TimeoutExpired:
        raise SystemExit(f"security-gate: {os.path.basename(argv[0])} ran past {timeout}s")


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        return json.loads(text) if text.strip() else default
    except (OSError, ValueError):
        return default


def repo_path(path, root):
    """A tool's path for a file, from the repository's root."""
    path = str(path)
    if os.path.isabs(path):
        path = os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    return path[2:] if path.startswith("./") else path


def stage(repo, rev, paths, into):
    """Write each PATH as it is at REV under INTO; the paths written."""
    out = []
    for path in paths:
        got = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"], capture_output=True)
        if got.returncode != 0:
            continue
        dest = os.path.join(into, path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(got.stdout)
        out.append(path)
    return out


def scan(repo, base, data, env=os.environ):
    """Every finding of the tools on the files the change touches, each with
    its status and fingerprint, and the merge base."""
    merge_base = git(repo, "merge-base", base, "HEAD").strip()
    adds = added_lines(git(repo, "diff", "-U0", "--no-color", "--no-ext-diff", merge_base, "HEAD"))
    sec = pack_security(kind_of(repo))
    excluded = [str(x) for x in sec.get("exclude") or []]
    files = sorted(p for p in adds if not (excluded and pol.matches(p, excluded)))
    sev = data.get("severities") or {}
    timeout = int(data.get("timeout") or 600)
    findings = []
    with tempfile.TemporaryDirectory() as tmp:
        head_dir, base_dir, out_dir = (os.path.join(tmp, d) for d in ("head", "base", "out"))
        for d in (head_dir, base_dir, out_dir):
            os.makedirs(d)
        staged = stage(repo, "HEAD", files, head_dir)
        if staged:
            report = os.path.join(out_dir, "gitleaks.json")
            call([tool_path("gitleaks", data, env), "dir", "--no-banner", "--redact", "--exit-code", "0",
                  "--report-format", "json", "--report-path", report, head_dir], timeout, env)
            found = from_gitleaks(read_json(report, []), sev.get("gitleaks"))
            configs = [os.path.join(cache_dir(data, env), "rules")] + [os.path.join(repo, str(r)) for r in sec.get("rules") or []]
            argv = [tool_path("semgrep", data, env), "scan", "--json", "--metrics", "off", "--disable-version-check",
                    "--quiet", "--no-git-ignore", "--timeout", "30"]
            for c in configs:
                argv += ["--config", c]
            # Run from the staged tree, so its paths are the repository's.
            ran = call(argv + ["."], timeout, dict(env, SEMGREP_SEND_METRICS="off"), cwd=head_dir)
            found += from_semgrep(json.loads(ran.stdout) if ran.stdout.strip().startswith("{") else {}, sev.get("semgrep"), configs)
            flows = [p for p in staged if WORKFLOW_RE.match(p)]
            if flows:
                ran = call([tool_path("zizmor", data, env), "--format", "json", "--offline", "--no-progress", *flows],
                           timeout, env, cwd=head_dir)
                found += from_zizmor(json.loads(ran.stdout) if ran.stdout.strip().startswith("[") else [], sev.get("zizmor"))
            for f in found:
                f["file"] = repo_path(f["file"], head_dir)
            findings += found
            locks = [p for p in staged if os.path.basename(p) in LOCKFILES]
            if locks:
                had = stage(repo, merge_base, locks, base_dir)
                before = set()
                if had:
                    ran = call([tool_path("osv-scanner", data, env), "scan", "source", "--format", "json"]
                               + [a for p in had for a in ("-L", os.path.join(base_dir, p))], timeout, env)
                    for f in from_osv(json.loads(ran.stdout) if ran.stdout.strip().startswith("{") else {}, sev.get("osv-scanner")):
                        before.add((repo_path(f["file"], base_dir), f["package"], f["rule"]))
                ran = call([tool_path("osv-scanner", data, env), "scan", "source", "--format", "json"]
                           + [a for p in locks for a in ("-L", os.path.join(head_dir, p))], timeout, env)

                def lines_of(path):
                    path = os.path.join(head_dir, path)
                    try:
                        return open(path, encoding="utf-8", errors="replace").read().splitlines()
                    except OSError:
                        return []
                for f in from_osv(json.loads(ran.stdout) if ran.stdout.strip().startswith("{") else {}, sev.get("osv-scanner"), lines_of):
                    f["file"] = repo_path(f["file"], head_dir)
                    f["status"] = "pre-existing" if (f["file"], f["package"], f["rule"]) in before else "new"
                    findings.append(f)
        heads = {}
        for f in findings:
            if f["file"] not in heads:
                path = os.path.join(head_dir, f["file"])
                heads[f["file"]] = open(path, encoding="utf-8", errors="replace").read().splitlines() if os.path.isfile(path) else []
            lines = heads[f["file"]]
            code = f.get("package") or (lines[f["line"] - 1] if 0 < f["line"] <= len(lines) else "")
            f["fingerprint"] = fingerprint(code)
            if "status" not in f:
                f["status"] = "new" if f["line"] in adds.get(f["file"], set()) else "pre-existing"
    suppress(findings, suppressions(repo))
    return findings, merge_base


def suppressions(repo):
    """The `rule:` entries of the repository's suppressions file, each with
    a reason; an entry with no reason suppresses nothing."""
    data = pol.load_yaml(os.path.join(repo, SUPPRESSIONS))
    entries = (data or {}).get("suppressions") if isinstance(data, dict) else None
    out = []
    for e in entries or []:
        if isinstance(e, dict) and e.get("rule") and e.get("file") and e.get("fingerprint") and str(e.get("reason") or "").strip():
            out.append({k: str(e[k]) for k in ("rule", "file", "fingerprint", "reason")})
    return out


def suppress(findings, entries):
    """Mark each finding an entry covers `suppressed`, with its reason. Pure
    but for the marking."""
    for f in findings:
        for e in entries:
            if (e["rule"], e["file"], e["fingerprint"]) == (f["rule"], f["file"], f["fingerprint"]):
                f["status"], f["reason"] = "suppressed", e["reason"]
                break
    return findings


# --- the result --------------------------------------------------------------

def blocking(findings, data):
    levels = set(data.get("block") or ("critical", "high"))
    return [f for f in findings if f.get("status") == "new" and f.get("severity") in levels]


def ordered(findings):
    """The most severe first; new before pre-existing before suppressed. Pure."""
    def key(f):
        return (LEVELS.index(f["severity"]) if f.get("severity") in LEVELS else len(LEVELS),
                STATUSES.index(f["status"]) if f.get("status") in STATUSES else len(STATUSES),
                f.get("file") or "", int(f.get("line") or 0), f.get("rule") or "")
    return sorted(findings, key=key)


def line_of(f):
    """One finding in two lines: its level, file, line, rule, tool, status
    and fingerprint (what a suppression names), then what it is and its
    fix, each cut short. Pure."""
    where = f"{clean(f.get('file'), 160)}:{int(f.get('line') or 0)}"
    out = (f"- [{f.get('severity')}] {where} {clean(f.get('rule'), 120)} ({f.get('tool')}, {f.get('status')})"
           f" fp {clean(f.get('fingerprint'), 12)}\n")
    out += f"  {clean(f.get('message'), 90)} Fix: {clean(f.get('fix'), 100)}\n"
    if f.get("status") == "suppressed":
        out += f"  Suppressed: {clean(f.get('reason'), 120)}\n"
    return out


def report(result, caps=None):
    """The capped report: a head line, then the most severe findings, each
    with its file, line, rule, severity and fix, at most `findings` of them
    and `bytes` in all, then how many more. A suppression names the rule,
    the file and the fingerprint (`fp`) shown. Pure."""
    caps = caps or result.get("caps") or {}
    limit, size = int(caps.get("findings") or 30), int(caps.get("bytes") or 8192)
    findings = ordered(result.get("findings") or [])
    counts = {s: sum(1 for f in findings if f.get("status") == s) for s in STATUSES}
    head = (f"Security gate ({result.get('mode')}): {counts['new']} new, {counts['pre-existing']} pre-existing, "
            f"{counts['suppressed']} suppressed; {len(result.get('blocking') or [])} new at a blocking level"
            + (" (it fails the gate)" if result.get("mode") == "block" and result.get("blocking") else "") + ".\n")
    out, shown = head, 0
    for f in findings[:limit]:
        entry = line_of(f)
        rest = len(findings) - shown - 1
        tail = f"{rest} more not shown: the full list is in the gate's JSON.\n" if rest else ""
        if len((out + entry + tail).encode()) > size:
            break
        out += entry
        shown += 1
    if shown < len(findings):
        out += f"{len(findings) - shown} more not shown: the full list is in the gate's JSON.\n"
    return out


def run(repo, base, data, mode_value, env=os.environ):
    findings, merge_base = scan(repo, base, data, env)
    result = {"mode": mode_value, "base": merge_base, "caps": data.get("caps") or {}, "findings": ordered(findings)}
    result["blocking"] = [f["fingerprint"] for f in blocking(findings, data)]
    return result


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    if argv[:1] == ["mode"] and len(argv) == 1:
        print(mode())
        return 0
    if argv[:1] == ["where"] and len(argv) == 1:
        data = load_policy()
        print(cache_dir(data))
        return 0
    if argv[:1] == ["install"] and len(argv) == 1:
        if mode() == "off":
            print("security-gate: off (org.yml `security-gate`): nothing to install")
            return 0
        return install(load_policy())
    if argv[:1] == ["report"] and len(argv) == 2:
        sys.stdout.write(report(read_json(argv[1], {})))
        return 0
    if argv[:1] == ["run"]:
        opts, rest = {}, argv[1:]
        while rest:
            if rest[0] in ("--base", "--json", "--mode", "--repo") and len(rest) > 1:
                opts[rest[0][2:]], rest = rest[1], rest[2:]
            else:
                print(__doc__, file=sys.stderr)
                return 64
        value = opts.get("mode") or mode()
        if value not in MODES:
            print(f"security-gate: mode `{value}`: off, report or block", file=sys.stderr)
            return 64
        if value == "off":
            print("Security gate: off (org.yml `security-gate`): nothing runs.")
            return 0
        repo = os.path.abspath(opts.get("repo") or ".")
        data = load_policy()
        result = run(repo, opts.get("base") or default_base(repo), data, value)
        if opts.get("json"):
            os.makedirs(os.path.dirname(os.path.abspath(opts["json"])), exist_ok=True)
            with open(opts["json"], "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=1)
        sys.stdout.write(report(result))
        return 1 if value == "block" and result["blocking"] else 0
    print(__doc__, file=sys.stderr)
    return 64


def self_test():
    fails = []

    def check(name, got, want):
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        if got != want:
            fails.append(name)

    data = load_policy()
    check("the policy pins every tool", sorted(data["tools"]), sorted(TOOLS))
    for name, tool in data["tools"].items():
        check(f"{name} has a version and a SHA-256 per build", bool(tool.get("version")) and all(
            re.fullmatch(r"[0-9a-f]{64}", str(b.get("sha256") or "")) for b in (tool.get("builds") or {}).values()) and bool(tool.get("builds")), True)
    check("the rules are pinned to a commit and a SHA-256", (bool(re.fullmatch(r"[0-9a-f]{40}", str(data["rules"]["commit"]))),
                                                              bool(re.fullmatch(r"[0-9a-f]{64}", str(data["rules"]["sha256"])))), (True, True))
    check("the caps are 30 findings and 8 KB", (data["caps"]["findings"], data["caps"]["bytes"]), (30, 8192))
    check("critical and high block", sorted(data["block"]), ["critical", "high"])
    check("the setting: report when unset, the three values, anything else refused",
          (mode_of({}), mode_of({"security-gate": "off"}), mode_of({"security-gate": "block"})), ("report", "off", "block"))
    try:
        mode_of({"security-gate": "maybe"})
        check("a mode that is none of the three fails", "passed", "raised")
    except ValueError:
        check("a mode that is none of the three fails", "raised", "raised")
    check("org.yml's own value is one of the three", mode() in MODES, True)
    check("platforms", (platform_key("Linux", "x86_64"), platform_key("Darwin", "arm64"), platform_key("Linux", "aarch64")),
          ("linux-x64", "darwin-arm64", "linux-arm64"))
    diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -2,0 +3,2 @@\n+x\n+y\n@@ -9 +11 @@\n-z\n+w\n"
            "diff --git a/gone b/gone\n--- a/gone\n+++ /dev/null\n@@ -1 +0,0 @@\n-q\n"
            "diff --git a/new.txt b/new.txt\n--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+n\n")
    check("the added and modified lines, by their number at the head", added_lines(diff), {"a.py": {3, 4, 11}, "new.txt": {1}})
    check("a Semgrep rule's id loses the path of its configuration",
          (rule_id("tmp.c.rules.python.lang.security.audit.eval-detected", ["/tmp/c/rules"]), rule_id("x.y", ["/a"])),
          ("python.lang.security.audit.eval-detected", "x.y"))
    check("a fingerprint ignores whitespace", (fingerprint("  a =  b "), len(fingerprint("x"))), (fingerprint("a = b"), 12))
    check("text from a tool loses backticks and control characters", clean("a `b`\x1b[31m\nc"), "a 'b' [31m c")
    fixtures = os.path.join(CENTRAL, "tests", "workflows", "fixtures", "security-gate")
    if os.path.isdir(fixtures):
        sev = data["severities"]
        g = from_gitleaks(read_json(os.path.join(fixtures, "gitleaks.json"), []), sev["gitleaks"])
        check("gitleaks' recorded output gives a critical finding with its rule and line", [(f["rule"], f["severity"], f["line"] > 0) for f in g][:1],
              [(g[0]["rule"], "critical", True)] if g else [])
        s = from_semgrep(read_json(os.path.join(fixtures, "semgrep.json"), {}), sev["semgrep"])
        check("Semgrep's recorded output gives a high finding", any(f["severity"] == "high" for f in s), True)
        z = from_zizmor(read_json(os.path.join(fixtures, "zizmor.json"), []), sev["zizmor"])
        check("zizmor's recorded output names the template injection", any(f["rule"] == "zizmor.template-injection" for f in z), True)
        o = from_osv(read_json(os.path.join(fixtures, "osv-scanner.json"), {}), sev["osv-scanner"])
        check("osv-scanner's recorded output gives a critical vulnerability with a fix", any(f["severity"] == "critical" and f["fix"].startswith("Upgrade") for f in o), True)
    many = [{"tool": "semgrep", "rule": f"r{i}", "file": "a.py", "line": i, "severity": LEVELS[i % 4], "status": "new",
             "message": "m" * 200, "fix": "f" * 200, "fingerprint": "0" * 12} for i in range(45)]
    text = report({"mode": "report", "findings": many, "blocking": []}, {"findings": 30, "bytes": 8192})
    check("the report keeps at most 8 KB", len(text.encode()) <= 8192, True)
    check("and says how many more", bool(re.search(r"^\d+ more not shown", text, re.M)), True)
    sup = suppress([dict(many[0])], [{"rule": "r0", "file": "a.py", "fingerprint": "0" * 12, "reason": "test data"}])
    check("an entry with a reason suppresses its finding", (sup[0]["status"], sup[0]["reason"]), ("suppressed", "test data"))
    print("all tests passed" if not fails else f"{len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
