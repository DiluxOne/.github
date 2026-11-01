#!/usr/bin/env python3
"""Who decides (#588): whose word steers the autopilot, and who may add
`accepted`, `autopilot:continue`, `/coauthor` and `/uncoauthor`.

The setting `who-decides` is org.yml's, with a repository's exception in
repos.yml (`repos.<name>.who-decides`); `codeowners` when neither says:

  codeowners  the code owners of the files the change touches, from the
              repository's CODEOWNERS on its default branch (.github/,
              the root, docs/; the last rule that matches a file wins). The
              files are the open pull request's, else the Spec's `Spec:
              files`, else (no Spec yet) the owners of the catch-all rule
              (`*`); with none of those, `writers`. A repository with no
              CODEOWNERS file is `writers`. Only people named in it count:
              a team (`@org/team`) decides nothing, and a file only teams
              own lets nobody but an admin decide (it fails closed).
  acceptor    whoever gave the newest acceptance (its seal's `accepted_by`);
              before any, anyone with write access gives the first one.
  writers     anyone with write access, as before #588.

Every value needs each action's own floor too, read live: write access
(`admin`, `maintain`, `write`) to answer, accept and continue; `maintain`
or `admin` to correct the credits. A value only narrows the floor, never
widens it. An admin always decides: they can change the setting anyway.

  deciders.py setting            the value in force for GITHUB_REPOSITORY
  deciders.py may ACTION LOGIN   exit 0 when LOGIN may (ACTION: answer,
                                 accepted, continue, credits), 1 when not;
                                 prints why, naming who may
  deciders.py list ACTION        the logins on stdin (one per line) that
                                 may, one per line
  deciders.py --test             self-test

Environment: GH_TOKEN; GITHUB_REPOSITORY (owner/name); NUMBER (the issue);
PR (its pull request, when the caller knows it; else the open one that
closes the issue). DX_ORG_YML and DX_REPOS_YML stand in for org.yml and
repos.yml, and DECIDERS_FIXTURE (a JSON file: roles, codeowners, files,
acceptor) for GitHub, in the self-test. Exit 2 when what decides could not
be read: the caller refuses, never takes it for yes.
"""
import base64
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")

VALUES = ("codeowners", "acceptor", "writers")
DEFAULT = "codeowners"
WRITE = ("admin", "maintain", "write")
MAINTAIN = ("admin", "maintain")
# Each action's floor (#588, choice 4a): `writers` widens none of them.
FLOORS = {"answer": WRITE, "accepted": WRITE, "continue": WRITE, "credits": MAINTAIN}
WHAT = {"answer": "answer the autopilot", "accepted": "add `accepted`", "continue": "add `autopilot:continue`",
        "credits": "correct the credits (`/coauthor`, `/uncoauthor`)"}
# Where GitHub reads a CODEOWNERS file, in its order.
CODEOWNERS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


# --- the setting -----------------------------------------------------------

def setting(org_conf, repos_conf, name):
    """`who-decides` for repository NAME: its repos.yml entry, else
    org.yml's, else `codeowners`. An unknown value is an error, never a
    guess."""
    sys.path.insert(0, HERE)
    import repos_conf as rc
    value = rc.value(repos_conf or {}, name, "who-decides")
    if value is None:
        value = (org_conf or {}).get("who-decides")
    value = DEFAULT if value is None else value
    if value not in VALUES:
        raise ValueError(f"who-decides is {value!r}: one of {', '.join(VALUES)}")
    return value


# --- CODEOWNERS (pure) -------------------------------------------------------

def parse_codeowners(text):
    """[(pattern, [owners])], in the file's order. A line's `#` starts a
    comment; a pattern with no owner says the files have none."""
    rules = []
    for line in (text or "").splitlines():
        line = re.sub(r"(^|\s)#.*$", "", line).strip()
        if not line:
            continue
        parts = line.split()
        rules.append((parts[0], parts[1:]))
    return rules


def _glob(pattern):
    """GitHub's CODEOWNERS pattern as a regular expression over a path from
    the repository's root (gitignore's rules, without `!` and `[ ]`)."""
    anchored = pattern.startswith("/") or "/" in pattern.strip("/")
    directory = pattern.endswith("/")
    p = pattern.strip("/")
    out, i = [], 0
    while i < len(p):
        if p.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif p.startswith("/**", i) and i + 3 == len(p):
            out.append("/.*")
            i += 3
        elif p.startswith("**", i):
            out.append(".*")
            i += 2
        elif p[i] == "*":
            out.append("[^/]*")
            i += 1
        elif p[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(p[i]))
            i += 1
    head = "^" if anchored else "^(?:.*/)?"
    tail = "/.*$" if directory else "(?:/.*)?$"
    return re.compile(head + "".join(out) + tail)


def matches(pattern, path):
    return bool(_glob(pattern).match(path.lstrip("/")))


def owners_of(rules, path):
    """The owners of PATH: the last rule that matches it wins."""
    found = []
    for pattern, owners in rules:
        if matches(pattern, path):
            found = owners
    return found


def people(owners):
    """The logins among owners (lowercase): never a team nor an e-mail."""
    return {o[1:].lower() for o in owners if o.startswith("@") and "/" not in o}


def teams(owners):
    return {o for o in owners if o.startswith("@") and "/" in o}


def catch_all(rules):
    """The owners of the catch-all rule (`*`), the last one, if any."""
    return next((o for p, o in reversed(rules) if p in ("*", "/*", "**", "/**")), [])


def spec_files(body):
    """The paths the Spec's `Spec: files` names, one per line: the first
    word of each, or what its backticks hold."""
    out = []
    m = re.search(r"^### Spec: files\s*$(.*?)(?=^### |\Z)", body or "", re.M | re.S)
    for line in (m.group(1) if m else "").splitlines():
        line = line.strip().lstrip("-*").strip()
        if not line:
            continue
        tick = re.match(r"`([^`]+)`", line)
        word = tick.group(1) if tick else line.split()[0].rstrip(",;:")
        if word and not word.startswith("("):
            out.append(word)
    return out


# --- the decision (pure) -----------------------------------------------------

def who_may(value, action, owners=(), acceptor=""):
    """Who may do ACTION, in words, for the comment that refuses someone."""
    floor = "the maintain or admin role" if FLOORS[action] == MAINTAIN else "write access"
    if value == "codeowners" and owners:
        return f"the code owners of what it touches ({', '.join('@' + o for o in sorted(owners))}) with {floor}, or an admin"
    if value == "codeowners":
        return "an admin: the code owners of what it touches are only teams, which decide nothing here (who-decides in org.yml or repos.yml)"
    if value == "acceptor" and acceptor:
        return f"@{acceptor}, who accepted it, with {floor}, or an admin"
    return f"anyone with {floor} to the repository"


def decide(value, action, login, role, codeowners=None, files=(), acceptor=""):
    """Whether LOGIN (with ROLE on the repository, read live) may do ACTION
    under `who-decides` VALUE: {ok, value, why, who}. CODEOWNERS is the
    file's text, None when the repository has none; FILES the change's;
    ACCEPTOR the newest seal's `accepted_by`. Pure."""
    effective = "writers" if value == "codeowners" and codeowners is None else value
    owners, only_teams = set(), False
    if effective == "codeowners":
        rules = parse_codeowners(codeowners)
        listed = [owners_of(rules, f) for f in files]
        owners = set().union(*(people(o) for o in listed)) if listed else set()
        if not owners and any(teams(o) for o in listed):
            only_teams = True
        elif not owners:
            # Nothing touched yet, or no owner of what is: the catch-all's.
            owners = people(catch_all(rules))
            only_teams = not owners and bool(teams(catch_all(rules)))
            if not owners and not only_teams:
                effective = "writers"
    if effective == "acceptor" and not acceptor:
        # The first acceptance (#588, choice 2a): anyone with write.
        effective = "writers"
    who = who_may(effective, action, owners, acceptor)
    me = (login or "").lower()
    out = {"value": value, "who": who}
    if role not in FLOORS[action]:
        return dict(out, ok=False, why=f"@{login} has {role or 'no'} access here; who may {WHAT[action]}: {who}.")
    if role == "admin" or effective == "writers":
        return dict(out, ok=True, why=f"@{login} may {WHAT[action]} ({role}, who-decides: {value}).")
    if effective == "acceptor" and me == acceptor.lower():
        return dict(out, ok=True, why=f"@{login} accepted it and may {WHAT[action]} ({role}).")
    if effective == "codeowners" and me in owners:
        return dict(out, ok=True, why=f"@{login} owns what it touches and may {WHAT[action]} ({role}).")
    return dict(out, ok=False, why=f"@{login} is not among those who decide here (who-decides: {value}); who may {WHAT[action]}: {who}.")


# --- reading GitHub ----------------------------------------------------------

def _gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return out.stdout


class Live:
    """What the decision reads from GitHub, once per run; DECIDERS_FIXTURE
    stands in for it."""

    def __init__(self, repo, number="", pr=""):
        self.repo, self.number, self.pr = repo, str(number or ""), str(pr or "")
        self.fixture = None
        if os.environ.get("DECIDERS_FIXTURE"):
            with open(os.environ["DECIDERS_FIXTURE"], encoding="utf-8") as fh:
                self.fixture = json.load(fh)
        self._roles = {}

    def role(self, login):
        if self.fixture is not None:
            return (self.fixture.get("roles") or {}).get(login, "none")
        if login not in self._roles:
            if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?", login or ""):
                self._roles[login] = "none"
            else:
                try:
                    self._roles[login] = _gh("api", f"repos/{self.repo}/collaborators/{login}/permission", "--jq", ".role_name").strip() or "none"
                except RuntimeError:
                    self._roles[login] = "none"
        return self._roles[login]

    def codeowners(self):
        """The CODEOWNERS file's text on the default branch (the contents
        API with no ref), never a pull request's; None when there is none.
        Any other failure raises: it is never taken for "none"."""
        if self.fixture is not None:
            return self.fixture.get("codeowners")
        for path in CODEOWNERS:
            try:
                data = json.loads(_gh("api", f"repos/{self.repo}/contents/{path}"))
            except RuntimeError as err:
                if "404" in str(err) or "Not Found" in str(err):
                    continue
                raise
            return base64.b64decode(data.get("content") or "").decode("utf-8", "replace")
        return None

    def files(self):
        """The change's files: the open pull request's, else the Spec's."""
        if self.fixture is not None:
            return list(self.fixture.get("files") or [])
        pr = self.pr
        if not pr and self.number:
            refs = json.loads(_gh("issue", "view", self.number, "--repo", self.repo, "--json", "closedByPullRequestsReferences"))
            opened = [str(r["number"]) for r in refs.get("closedByPullRequestsReferences") or [] if r.get("state", "OPEN") == "OPEN"]
            pr = opened[-1] if opened else ""
        if pr:
            names = [l for l in _gh("api", "--paginate", f"repos/{self.repo}/pulls/{pr}/files", "--jq", ".[].filename").splitlines() if l]
            if names:
                return names
        if self.number:
            body = json.loads(_gh("api", f"repos/{self.repo}/issues/{self.number}")).get("body") or ""
            return spec_files(body)
        return []

    def acceptor(self):
        """The newest seal's `accepted_by`; "" before any, or a lane's."""
        if self.fixture is not None:
            return self.fixture.get("acceptor") or ""
        if not self.number:
            return ""
        sys.path.insert(0, HERE)
        import receipts
        last = receipts.last_seal(self.repo, int(self.number)) or {}
        by = str(last.get("accepted_by") or "")
        return "" if by.startswith("policy") and " " in by else by


def load_yaml(path):
    if not os.path.exists(path):
        return {}
    sys.path.insert(0, HERE)
    import org
    return org.load(path) or {}


def value_for(repo):
    org_conf = load_yaml(os.environ.get("DX_ORG_YML") or os.path.join(ROOT, "org.yml"))
    repos = load_yaml(os.environ.get("DX_REPOS_YML") or os.path.join(ROOT, "repos.yml"))
    return setting(org_conf, repos, repo.split("/", 1)[-1])


def context(live, value):
    """(codeowners, files, acceptor) a value needs, read only when it does."""
    if value == "codeowners":
        text = live.codeowners()
        return text, (live.files() if text is not None else []), ""
    if value == "acceptor":
        return None, [], live.acceptor()
    return None, [], ""


# --- the self-test -----------------------------------------------------------

def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    fix = os.path.join(HERE, "fixtures", "deciders")
    owners = open(os.path.join(fix, "CODEOWNERS"), encoding="utf-8").read()
    rules = parse_codeowners(owners)
    check("codeowners: the last rule that matches wins", owners_of(rules, "scripts/deciders.py"), ["@scripter"])
    check("codeowners: the catch-all owns the rest", owners_of(rules, "README.md"), ["@boss"])
    check("codeowners: a directory rule covers what is under it", owners_of(rules, "docs/a/b.md"), ["@writer"])
    check("codeowners: an unanchored name matches at any depth", owners_of(rules, "x/y/Makefile"), ["@builder"])
    check("codeowners: an anchored pattern only from the root", (owners_of(rules, "workflows/x.yml"), owners_of(rules, ".github/workflows/x.yml")), (["@boss"], ["@acme/ci"]))
    check("codeowners: a team is no person", (people(["@acme/ci", "@Boss", "a@b.c"]), teams(["@acme/ci", "@boss"])), ({"boss"}, {"@acme/ci"}))
    check("spec_files: the first word, or the backticks", spec_files("### Spec: files\n\n- scripts/a.py (new)\n- `b c.md`\n\n### Spec: tests\n\n- x\n"), ["scripts/a.py", "b c.md"])
    # C1: `codeowners`, and a collaborator with write access who owns none
    # of the files the change touches.
    d = decide("codeowners", "answer", "dev", "write", owners, ["scripts/deciders.py"])
    check("C1: codeowners refuses a writer who owns nothing the change touches", d["ok"], False)
    check("C1: and says who may", "@scripter" in d["why"] and "who-decides: codeowners" in d["why"], True)
    check("C1: the owner of a touched file decides", decide("codeowners", "answer", "scripter", "write", owners, ["scripts/deciders.py"])["ok"], True)
    check("C1: an owner without write access does not (the floor)", decide("codeowners", "answer", "scripter", "triage", owners, ["scripts/deciders.py"])["ok"], False)
    check("C1: an admin always decides", decide("codeowners", "answer", "root", "admin", owners, ["scripts/deciders.py"])["ok"], True)
    check("C1: nothing touched yet: the catch-all's owners", (decide("codeowners", "answer", "boss", "write", owners, [])["ok"], decide("codeowners", "answer", "dev", "write", owners, [])["ok"]), (True, False))
    check("C1: only teams own it: nobody but an admin (fails closed)",
          (decide("codeowners", "answer", "dev", "maintain", owners, [".github/workflows/a.yml"])["ok"], "only teams" in decide("codeowners", "answer", "dev", "write", owners, [".github/workflows/a.yml"])["why"]), (False, True))
    check("C1: a CODEOWNERS with no catch-all and nothing owned: writers", decide("codeowners", "answer", "dev", "write", "docs/ @writer\n", ["src/a.py"])["ok"], True)
    with open(os.path.join(fix, "comments.json"), encoding="utf-8") as fh:
        logins = sorted({c["author"]["login"] for c in json.load(fh)})
    import subprocess as sp
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        def cli(args, fixture, org_yml="", repos_yml="", stdin=""):
            fx, oy, ry = (os.path.join(t, n) for n in ("fx.json", "org.yml", "repos.yml"))
            with open(fx, "w", encoding="utf-8") as fh:
                json.dump(fixture, fh)
            for p, text in ((oy, org_yml), (ry, repos_yml)):
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(text or "{}\n")
            env = dict(os.environ, DECIDERS_FIXTURE=fx, DX_ORG_YML=oy, DX_REPOS_YML=ry, GITHUB_REPOSITORY="o/r", NUMBER="7")
            out = sp.run([sys.executable, os.path.abspath(__file__), *args], input=stdin, capture_output=True, text=True, env=env)
            return out.returncode, out.stdout.strip()
        roles = {"boss": "admin", "dev": "write", "scripter": "write", "stranger": "read"}
        base = {"roles": roles, "codeowners": owners, "files": ["scripts/deciders.py"]}
        check("C1 cli: may answer refuses the writer outside, exit 1", cli(["may", "answer", "dev"], base)[0], 1)
        check("C1 cli: list keeps only those who decide", cli(["list", "answer"], base, stdin="\n".join(logins)), (0, "boss\nscripter"))
        # C2: a repository's `writers` over the organisation's `codeowners`.
        check("C2: repos.yml's who-decides wins over org.yml's", setting({"who-decides": "codeowners"}, {"repos": {"r": {"kinds": [], "who-decides": "writers"}}}, "r"), "writers")
        check("C2: another repository keeps the organisation's", setting({"who-decides": "acceptor"}, {"repos": {"r": {"kinds": [], "who-decides": "writers"}}}, "s"), "acceptor")
        over = ("who-decides: codeowners\n", "repos:\n  r:\n    kinds: []\n    who-decides: writers\n")
        check("C2 cli: with writers over codeowners, a writer's answer is taken", cli(["may", "answer", "dev"], base, *over),
              (0, "@dev may answer the autopilot (write, who-decides: writers)."))
        check("C2 cli: setting says the value in force", cli(["setting"], base, *over), (0, "writers"))
        check("C2 cli: and still never someone without write", cli(["may", "answer", "stranger"], base, *over)[0], 1)
        # C3: no setting anywhere, and no CODEOWNERS file: `writers`.
        check("C3: no setting is codeowners", setting({}, {}, "r"), "codeowners")
        check("C3: codeowners with no CODEOWNERS file is writers", decide("codeowners", "answer", "dev", "write", None, ["a.py"])["ok"], True)
        check("C3 cli: no setting, no CODEOWNERS: a writer's answer is taken", cli(["may", "answer", "dev"], dict(base, codeowners=None))[0], 0)
        check("C3 cli: and the list is every writer", cli(["list", "answer"], dict(base, codeowners=None), stdin="\n".join(logins)), (0, "boss\ndev\nscripter"))
        # C4: `accepted` and `autopilot:continue` by someone outside.
        for action, label in (("accepted", "add `accepted`"), ("continue", "add `autopilot:continue`")):
            rc, why = cli(["may", action, "dev"], dict(base, files=[]))
            check(f"C4 cli: may {action} refuses a writer outside, naming who may {label}", (rc, f"who may {label}: the code owners of what it touches (@boss)" in why), (1, True))
            check(f"C4 cli: may {action} refuses someone without write, naming who may", cli(["may", action, "stranger"], dict(base, codeowners=None))[1],
                  f"@stranger has read access here; who may {label}: anyone with write access to the repository.")
        acc = dict(base, codeowners=None, acceptor="boss", roles=dict(roles, root="admin"))
        check("C4 cli: acceptor: once accepted, only the acceptor (or an admin) re-accepts or continues",
              [cli(["may", "continue", w], acc, "who-decides: acceptor\n")[0] for w in ("boss", "dev", "root")], [0, 1, 0])
        check("C4 cli: acceptor: the refusal names the acceptor", "@boss, who accepted it" in cli(["may", "continue", "dev"], acc, "who-decides: acceptor\n")[1], True)
        check("C4 cli: acceptor: before any acceptance, any writer gives the first", cli(["may", "accepted", "dev"], dict(acc, acceptor=""), "who-decides: acceptor\n")[0], 0)
        check("C4 (choice 4a): the credits keep their floor of maintain, whatever the value",
              (cli(["may", "credits", "dev"], acc, "who-decides: writers\n")[0], decide("writers", "credits", "m", "maintain")["ok"]), (1, True))
        check("cli: an unknown value is an error (exit 2), never a yes", cli(["may", "answer", "dev"], base, "who-decides: everyone\n")[0], 2)
    # C3: only GitHub's "not found" is no CODEOWNERS; any other failure is
    # never read as none (which would open the decision to every writer).
    global _gh
    real, seen = _gh, []

    def fake(*args):
        seen.append(args[1])
        if args[1].endswith("/.github/CODEOWNERS") or args[1].endswith("/contents/CODEOWNERS"):
            raise RuntimeError("HTTP 404: Not Found")
        if fail:
            raise RuntimeError("HTTP 502: Bad Gateway")
        return json.dumps({"content": base64.b64encode(b"* @boss\n").decode()})
    try:
        _gh = fake
        fail = False
        live = Live("o/r")
        live.fixture = None
        check("C3: GitHub's three places, in its order; the first found is read",
              (live.codeowners(), [s.rsplit("/contents/", 1)[1] for s in seen]), ("* @boss\n", list(CODEOWNERS)))
        fail = True
        try:
            live.codeowners()
            check("C3: a failure to read is no missing file", "none", "raised")
        except RuntimeError:
            check("C3: a failure to read is no missing file", "raised", "raised")
    finally:
        _gh = real
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    try:
        value = value_for(repo)
    except ValueError as err:
        print(f"::error::{err}")
        return 2
    if argv[:1] == ["setting"]:
        print(value)
        return 0
    if len(argv) >= 2 and argv[0] in ("may", "list") and argv[1] in FLOORS:
        action = argv[1]
        live = Live(repo, os.environ.get("NUMBER", ""), os.environ.get("PR", ""))
        try:
            codeowners, files, acceptor = context(live, value)
            if argv[0] == "may" and len(argv) == 3:
                d = decide(value, action, argv[2], live.role(argv[2]), codeowners, files, acceptor)
                print(d["why"])
                return 0 if d["ok"] else 1
            if argv[0] == "list" and len(argv) == 2:
                for login in sorted({l.strip() for l in sys.stdin if l.strip()}):
                    if decide(value, action, login, live.role(login), codeowners, files, acceptor)["ok"]:
                        print(login)
                return 0
        except (RuntimeError, OSError, ValueError, KeyError) as err:
            print(f"::error::Who decides could not be read: {str(err)[:300]}")
            return 2
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
