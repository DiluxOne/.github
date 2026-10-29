#!/usr/bin/env python3
"""Who signs what (#491): the organisation's rule on authorship, as code.

A model is never a co-author: a commit written with its help carries
`Assisted-by: <model> (<maker>)`. A person is: whoever wrote commits of the
pull request, or proposed what it used (the issue's "Proposed solution", a
comment on the issue), as the description's Credits block lists them.

  credits.py models            the `Co-authored-by` lines on stdin (commit
                               messages, a description) that name a model,
                               one per line with the `Assisted-by:` line to
                               use instead; exit 1 when there is one
  credits.py block             the Credits block of the description on
                               stdin, one `login kind` per line; exit 1 when
                               the description has none
  credits.py write FILE        the description on stdin with its Credits
                               block set to FILE's entries (`- @login: kind
                               (link)`); exit 1 when FILE has a line that is
                               not one
  credits.py command BY OUT    the description on stdin with the comment in
                               COMMENT applied (`/coauthor @login`,
                               `/uncoauthor @login`, BY the maintainer),
                               written to OUT; what changed on stdout
  credits.py body REPO PR [MERGER]
                               the squash's body: the description, then
                               under `---------` the trailers of the Credits
                               block and the branch commits' human
                               co-authors (gh, GH_TOKEN; exit 1, loudly,
                               when GitHub cannot be read: the merge waits)
  credits.py trailers REPO PR [MERGER]
                               only those trailers, one per line
  credits.py --test            self-test

The Credits block sits in the description's "🙌 Credits" section, between
its markers, one person per line:

  <!-- dx-credits -->
  - @login: co-author (https://github.com/o/r/issues/1#issuecomment-2)
  <!-- /dx-credits -->

`co-author` writes `Co-authored-by`, `suggested` `Suggested-by` and
`reported` `Reported-by`, each with GitHub's noreply address of the account
(`<id>+<login>@users.noreply.github.com`, read from the API, never a
private e-mail). Never a co-author: a model, dilux-bot, Dependabot, any
`[bot]` or Bot account, the maintainer who accepted the issue it closes and
the one who merges it.
"""
import json
import os
import re
import subprocess
import sys

# The makers whose models sign as co-authors, and how to tell them: an
# address of theirs, or a name that is the model's and nothing else
# ("Claude", "Claude Opus 5.5", "GitHub Copilot"), never a person who shares
# the first name ("Claude Dupont <claude@example.org>").
MAKERS = {
    "Anthropic": {"names": ("claude",), "domains": ("anthropic.com",)},
    "OpenAI": {"names": ("chatgpt", "codex", "openai", "gpt"), "domains": ("openai.com",)},
    "GitHub": {"names": ("copilot", "github copilot"), "domains": ()},
    "Google": {"names": ("gemini", "bard", "jules"), "domains": ()},
    "Anysphere": {"names": ("cursor", "cursor agent"), "domains": ("cursor.com", "cursor.sh")},
    "Cognition": {"names": ("devin",), "domains": ("cognition.ai",)},
    "Aider": {"names": ("aider",), "domains": ("aider.chat",)},
}
# What may follow a model's name and still be the model: its family, its
# version, the product around it.
MODEL_WORDS = {"code", "opus", "sonnet", "haiku", "fable", "instant", "agent", "assistant", "ai", "cli",
               "pro", "flash", "ultra", "mini", "nano", "turbo", "max", "bot", "[bot]", "swe", "chat", "coding"}
TRAILER_RE = re.compile(r"^\s*co-authored-by:\s*(?P<name>[^<\n]*?)\s*(?:<(?P<email>[^>\n]*)>)?\s*$", re.I)


def model_maker(name, email):
    """The maker when this co-author is a model, else None."""
    name, email = (name or "").strip().lower(), (email or "").strip().lower()
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    local = email.split("@", 1)[0].split("+", 1)[-1]
    for maker, known in MAKERS.items():
        if any(domain == d or domain.endswith("." + d) for d in known["domains"]):
            return maker
        # GitHub's noreply form of a model's account: 1234+Copilot@users.noreply.github.com.
        if domain == "users.noreply.github.com" and local.removesuffix("[bot]") in known["names"]:
            return maker
        for model in known["names"]:
            if name == model or name.startswith(model + " ") or name.startswith(model + "-"):
                rest = name[len(model):].replace("-", " ").split()
                if all(w in MODEL_WORDS or re.fullmatch(r"[\d.o]+[a-z]?|v?\d[\w.]*", w) for w in rest):
                    return maker
            if name.endswith(" " + model) and name.split()[0] in ("github", "openai", "google", "anthropic"):
                return maker
    return None


def models(text):
    """[(trailer, the Assisted-by line to use)] for every Co-authored-by in
    text that names a model."""
    found = []
    for line in text.replace("\r", "").split("\n"):
        m = TRAILER_RE.match(line)
        if not m:
            continue
        maker = model_maker(m["name"], m["email"])
        if maker:
            model = m["name"].strip() or maker
            found.append((line.strip(), f"Assisted-by: {model} ({maker})"))
    return found


HEAD = "## 🙌 Credits"
START = "<!-- dx-credits -->"
END = "<!-- /dx-credits -->"
KINDS = {"co-author": "Co-authored-by", "suggested": "Suggested-by", "reported": "Reported-by"}
# The most lines a block is read for: a huge one is cut, not a denial.
MAX_ENTRIES = 50
LOGIN = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?"
ENTRY_RE = re.compile(rf"^\s*[-*]\s*@(?P<login>{LOGIN}):\s*(?P<kind>co-author|suggested|reported)\b\s*(?:\((?P<note>[^()\n]{{0,300}})\))?\s*$", re.I)
COMMAND_RE = re.compile(rf"^\s*/(?P<cmd>coauthor|uncoauthor)(?P<who>(?:\s+@{LOGIN})+)\s*$", re.I)
NOREPLY_RE = re.compile(r"^(?:\d+\+)?(?P<login>[^@+]+)@users\.noreply\.github\.com$", re.I)
# The organisation's own bots by login, whatever the API says of them.
BOTS = {"dilux-bot", "dependabot", "github-actions", "renovate"}


def entry_line(e):
    return f"- @{e['login']}: {e['kind']}" + (f" ({e['note']})" if e.get("note") else "")


def has_block(body):
    """Whether the description holds the Credits markers, in order."""
    body = body or ""
    return START in body and END in body.split(START, 1)[1]


def parse_entries(text):
    """[{login, kind, note}] from the lines of text that are entries, at
    most MAX_ENTRIES, one per login (case-insensitively: the strongest kind
    wins); the rest are ignored."""
    out = {}
    rank = list(KINDS)
    for line in (text or "").replace("\r", "").split("\n")[:MAX_ENTRIES * 4]:
        m = ENTRY_RE.match(line)
        if not m:
            continue
        e = {"login": m["login"], "kind": m["kind"].lower(), "note": (m["note"] or "").strip()}
        key = e["login"].lower()
        if key not in out and len(out) >= MAX_ENTRIES:
            continue
        if key not in out or rank.index(e["kind"]) < rank.index(out[key]["kind"]):
            out[key] = e
    return list(out.values())


def read_block(body):
    """The Credits block's entries, [] when there is none."""
    if not has_block(body):
        return []
    return parse_entries(body.split(START, 1)[1].split(END, 1)[0])


def set_block(body, entries):
    """The description with its Credits block holding entries; a
    description with none gets the section, before "How I tested it", else
    before the AI line, else at the end."""
    inner = "".join(entry_line(e) + "\n" for e in entries)
    block = f"{START}\n{inner}{END}"
    body = (body or "").replace("\r", "")
    if has_block(body):
        before, rest = body.split(START, 1)
        return before + block + rest.split(END, 1)[1]
    section = f"{HEAD}\n\n{block}\n\n"
    for anchor in ("## 🧪 How I tested it", "🤖 AI-"):
        at = body.find("\n" + anchor)
        if at >= 0:
            return body[:at + 1] + section + body[at + 1:]
    return body.rstrip("\n") + ("\n\n" if body.strip() else "") + section.rstrip("\n") + "\n"


def command(body, comment, by):
    """(the description, [what changed]) with the comment's `/coauthor
    @login` and `/uncoauthor @login` lines applied; any other text is
    ignored, and a command that changes nothing says so."""
    entries = read_block(body)
    changed, said = False, []
    for line in (comment or "").replace("\r", "").split("\n"):
        m = COMMAND_RE.match(line)
        if not m:
            continue
        for login in re.findall(rf"@({LOGIN})", m["who"]):
            have = next((e for e in entries if e["login"].lower() == login.lower()), None)
            if m["cmd"].lower() == "coauthor":
                if have and have["kind"] == "co-author":
                    said.append(f"@{login} is already a co-author.")
                    continue
                if have:
                    have.update(kind="co-author", note=f"/coauthor by @{by}")
                else:
                    if len(entries) >= MAX_ENTRIES:
                        said.append(f"@{login} is not added: the block holds {MAX_ENTRIES} people already.")
                        continue
                    entries.append({"login": login, "kind": "co-author", "note": f"/coauthor by @{by}"})
                said.append(f"@{login} is a co-author now.")
            else:
                if not have:
                    said.append(f"@{login} was not in the Credits block.")
                    continue
                entries.remove(have)
                said.append(f"@{login} is no longer credited.")
            changed = True
    if not changed:
        return body, said
    return set_block(body, entries), said


def _noreply_login(email):
    m = NOREPLY_RE.match((email or "").strip())
    return m["login"] if m else ""


def is_bot(login, user=None):
    low = (login or "").lower()
    return low.endswith("[bot]") or low in BOTS or ((user or {}).get("type") == "Bot")


def _clean_name(name):
    return " ".join(re.sub(r"[<>\x00-\x1f]", "", name or "").split())


def compose(entries, users, messages, excluded=(), author=""):
    """The squash's trailers: the block's people as their kind, resolved in
    users ({login lower: the API's user}), then the commits' human
    `Co-authored-by` lines, never a model, a bot, an excluded login (the
    maintainer who accepted, the one who merges) or the author, each person
    once (by account or address, case-insensitively), the strongest kind
    kept. Pure."""
    skip = {x.lower() for x in excluded if x} | ({author.lower()} if author else set())
    seen_logins, seen_mails = set(), set()
    out = []

    def from_block(kinds):
        for e in entries:
            if e["kind"] not in kinds:
                continue
            user = users.get(e["login"].lower())
            if user is None:
                raise KeyError(f"@{e['login']} was not read from GitHub")
            login = user.get("login") or e["login"]
            if login.lower() in skip or is_bot(login, user) or login.lower() in seen_logins:
                continue
            name = _clean_name(user.get("name")) or login
            if model_maker(name, ""):
                continue
            mail = f"{user['id']}+{login}@users.noreply.github.com"
            seen_logins.add(login.lower())
            seen_mails.add(mail.lower())
            out.append(f"{KINDS[e['kind']]}: {name} <{mail}>")

    # Co-authors first, the block's then the commits', then the lesser
    # credits of whoever is not one already.
    from_block(("co-author",))
    for line in "\n".join(messages).replace("\r", "").split("\n"):
        m = TRAILER_RE.match(line)
        if not m or not m["email"]:
            continue
        name, mail = m["name"].strip(), m["email"].strip()
        login = _noreply_login(mail)
        if model_maker(name, mail) or "[bot]" in (name + mail).lower() or is_bot(login):
            continue
        if (login and (login.lower() in skip or login.lower() in seen_logins)) or mail.lower() in seen_mails:
            continue
        seen_mails.add(mail.lower())
        if login:
            seen_logins.add(login.lower())
        out.append(f"Co-authored-by: {_clean_name(name) or login or mail} <{mail}>")
    from_block(("suggested",))
    from_block(("reported",))
    return out


def squash_body(description, trailers):
    """The description, then the trailers under GitHub's own separator."""
    body = (description or "").replace("\r", "").rstrip("\n")
    if trailers:
        body += ("\n\n" if body else "") + "---------\n\n" + "\n".join(trailers)
    return body


def gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {out.stderr.strip()[:300]}")
    return out.stdout


def body_of(repo, pr, merger="", trailers_only=False):
    """The squash's body for a pull request, read from GitHub (or only its
    trailers)."""
    data = json.loads(gh("api", f"repos/{repo}/pulls/{pr}"))
    messages = gh("api", f"repos/{repo}/pulls/{pr}/commits", "--paginate", "--jq", ".[].commit.message").split("\n")
    excluded = {merger, os.environ.get("DX_BOT_LOGIN", "")}
    issues = gh("pr", "view", str(pr), "--repo", repo, "--json", "closingIssuesReferences", "--jq", ".closingIssuesReferences[].number").split()
    for n in issues:
        jq = '.[] | select(.event == "labeled" and .label.name == "accepted") | .actor.login'
        excluded |= set(gh("api", f"repos/{repo}/issues/{n}/timeline", "--paginate", "--jq", jq).split())
    entries = read_block(data.get("body") or "")
    users = {}
    for e in entries:
        if e["login"].lower() in {x.lower() for x in excluded if x} or is_bot(e["login"]):
            users[e["login"].lower()] = {"login": e["login"], "id": 0, "type": "Bot"}
            continue
        users[e["login"].lower()] = json.loads(gh("api", f"users/{e['login']}", "--jq", "{login, id, name, type}"))
    trailers = compose(entries, users, messages, excluded, (data.get("user") or {}).get("login", ""))
    return "".join(t + "\n" for t in trailers) if trailers_only else squash_body(data.get("body") or "", trailers)


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    # C1: Claude's own trailer is a model's, with the line to use instead.
    check("C1: Claude's trailer names a model",
          models("fix: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"),
          [("Co-Authored-By: Claude <noreply@anthropic.com>", "Assisted-by: Claude (Anthropic)")])
    check("C1: a model by its address alone", [m[1] for m in models("Co-authored-by: Bot <x@openai.com>")], ["Assisted-by: Bot (OpenAI)"])
    check("C1: a model with its version", [m[1] for m in models("co-authored-by: Claude Opus 5.5 <a@b.c>")], ["Assisted-by: Claude Opus 5.5 (Anthropic)"])
    check("C1: Copilot's noreply account", [m[1] for m in models("Co-authored-by: Copilot <175728472+Copilot@users.noreply.github.com>")], ["Assisted-by: Copilot (GitHub)"])
    check("C1: the known makers' names", [bool(models(f"Co-authored-by: {n} <x@y.z>")) for n in ("Gemini", "ChatGPT", "Codex", "Cursor Agent", "GitHub Copilot", "GPT-5")], [True] * 6)
    check("C1: CRLF endings", len(models("Co-authored-by: Claude <noreply@anthropic.com>\r\n")), 1)
    # C2: a person is a co-author, and Assisted-by is the line to use.
    check("C2: a person and Assisted-by pass",
          models("feat: x\n\nAssisted-by: Claude Opus 5.5 (Anthropic)\nCo-authored-by: Ana Pérez <12+ana@users.noreply.github.com>\n"), [])
    check("C2: a person who shares a model's first name", models("Co-authored-by: Claude Dupont <claude@example.org>"), [])
    check("C2: a person's noreply address", models("Co-authored-by: Gem <9+gemini-fan@users.noreply.github.com>"), [])
    check("C2: the words, not a trailer", models("We asked Claude <noreply@anthropic.com> about it."), [])
    # The Credits block (C3).
    desc = "## 📝 What changes\n\nx\n\n## 🧪 How I tested it\n\ny\n\n🤖 AI-generated · Claude Opus 5.5 (Anthropic)"
    check("C3: a description with no block has none", (has_block(desc), read_block(desc)), (False, []))
    one = set_block(desc, [{"login": "ana", "kind": "co-author", "note": "https://github.com/o/r/issues/1"}])
    check("C3: set_block adds the section before How I tested it",
          one.split("## 🧪")[0].endswith(f"{HEAD}\n\n{START}\n- @ana: co-author (https://github.com/o/r/issues/1)\n{END}\n\n"), True)
    check("C3: and reads back", read_block(one), [{"login": "ana", "kind": "co-author", "note": "https://github.com/o/r/issues/1"}])
    check("C3: set again replaces it, once", (set_block(one, []).count(START), read_block(set_block(one, []))), (1, []))
    check("C3: an empty block is still a block", has_block(set_block(desc, [])), True)
    check("C3: malformed lines are ignored, the strongest kind kept",
          parse_entries("- @ana: reported\n- @ANA: co-author\n- @bob: author\n- bob: suggested\nrm -rf /\n- @c: suggested (x)"),
          [{"login": "ANA", "kind": "co-author", "note": ""}, {"login": "c", "kind": "suggested", "note": "x"}])
    check("C3: a huge block is cut", len(parse_entries("".join(f"- @u{i}: reported\n" for i in range(500)))), MAX_ENTRIES)
    users = {"ana": {"login": "ana", "id": 12, "name": "Ana Pérez", "type": "User"},
             "bob": {"login": "bob", "id": 34, "name": None, "type": "User"},
             "cy": {"login": "cy", "id": 56, "name": "Cy", "type": "User"},
             "dee": {"login": "dee", "id": 78, "name": "Dee", "type": "User"}}
    claude = "fix: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    check("C3: the issue's author in the block is a co-author by the noreply address, no model",
          compose([{"login": "ana", "kind": "co-author"}], users, [claude]),
          ["Co-authored-by: Ana Pérez <12+ana@users.noreply.github.com>"])
    check("C3: the name falls back to the login", compose([{"login": "bob", "kind": "co-author"}], users, []),
          ["Co-authored-by: bob <34+bob@users.noreply.github.com>"])
    check("C3: suggested and reported, after the co-authors",
          compose([{"login": "cy", "kind": "reported"}, {"login": "bob", "kind": "suggested"}, {"login": "ana", "kind": "co-author"}], users, []),
          ["Co-authored-by: Ana Pérez <12+ana@users.noreply.github.com>", "Suggested-by: bob <34+bob@users.noreply.github.com>",
           "Reported-by: Cy <56+cy@users.noreply.github.com>"])
    try:
        compose([{"login": "zed", "kind": "co-author"}], users, [])
        check("C3: a person GitHub did not return fails, never dropped", "no error", "KeyError")
    except KeyError:
        check("C3: a person GitHub did not return fails, never dropped", "KeyError", "KeyError")
    check("C3: the squash body: the description, the separator, the trailers",
          squash_body("A.\r\n", ["Co-authored-by: X <1+x@users.noreply.github.com>"]),
          "A.\n\n---------\n\nCo-authored-by: X <1+x@users.noreply.github.com>")
    check("C3: no trailers, the description alone", squash_body("A.\n", []), "A.")
    # C4: two commenters whose proposals the change used, one of them also a
    # commit's co-author under another casing: one line each.
    two = [{"login": "cy", "kind": "co-author", "note": "https://github.com/o/r/issues/7#issuecomment-1"},
           {"login": "dee", "kind": "co-author", "note": "https://github.com/o/r/issues/7#issuecomment-2"}]
    commits = ["feat: x (C1)\n\nCo-authored-by: CY <56+CY@users.noreply.github.com>", "fix: y\n\nco-authored-by: Dee <78+dee@USERS.noreply.github.com>\nCo-authored-by: Eve <eve@example.org>",
               "fix: z\n\nCo-authored-by: Eve <EVE@example.org>"]
    check("C4: two commenters, each once, and a commit's other person once",
          compose(two, users, commits),
          ["Co-authored-by: Cy <56+cy@users.noreply.github.com>", "Co-authored-by: Dee <78+dee@users.noreply.github.com>", "Co-authored-by: Eve <eve@example.org>"])
    check("C4: a co-author is not also suggested or reported",
          compose([{"login": "cy", "kind": "reported"}, {"login": "CY", "kind": "co-author"}, {"login": "dee", "kind": "suggested"}], users, ["Co-authored-by: Dee <78+dee@users.noreply.github.com>"]),
          ["Co-authored-by: Cy <56+cy@users.noreply.github.com>", "Co-authored-by: Dee <78+dee@users.noreply.github.com>"])
    # C5: a maintainer's /coauthor and /uncoauthor.
    base = set_block(desc, [{"login": "ana", "kind": "reported", "note": "https://github.com/o/r/issues/7"}])
    added, said = command(base, "/coauthor @bob", "boss")
    check("C5: /coauthor @x adds them as a co-author, and says so",
          (read_block(added), said), ([{"login": "ana", "kind": "reported", "note": "https://github.com/o/r/issues/7"},
                                       {"login": "bob", "kind": "co-author", "note": "/coauthor by @boss"}], ["@bob is a co-author now."]))
    again, said2 = command(added, "/coauthor @BOB", "boss")
    check("C5: idempotent: a co-author already changes nothing", (again, said2), (added, ["@BOB is already a co-author."]))
    check("C5: /coauthor of someone credited otherwise makes them a co-author",
          [e["kind"] for e in read_block(command(base, "/coauthor @ana", "boss")[0])], ["co-author"])
    removed, said3 = command(added, "/uncoauthor @bob", "boss")
    check("C5: /uncoauthor @x removes them", (read_block(removed), said3), (read_block(base), ["@bob is no longer credited."]))
    check("C5: /uncoauthor of someone absent changes nothing", command(base, "/uncoauthor @zed", "boss"), (base, ["@zed was not in the Credits block."]))
    check("C5: several people, several lines", [e["login"] for e in read_block(command(base, "/coauthor @bob @cy\n/uncoauthor @ana", "boss")[0])], ["bob", "cy"])
    check("C5: unknown text is ignored", [command(base, t, "boss") for t in ("thanks /coauthor @bob", "/coauthor bob", "/coauthors @bob", "/coauthor @bob; rm -rf /", "")],
          [(base, [])] * 5)
    check("C5: a description with no block gets one", read_block(command(desc, "/coauthor @bob", "boss")[0]),
          [{"login": "bob", "kind": "co-author", "note": "/coauthor by @boss"}])
    # C4: what the merge passes to --body, read from GitHub (gh faked).
    pr_body = "## 📝 What changes\n\nx\n\n" + set_block("", two + [{"login": "boss", "kind": "co-author"}, {"login": "dependabot[bot]", "kind": "co-author"}])
    calls = []

    def fake_gh(*args):
        calls.append(args)
        if args[:2] == ("api", "repos/o/r/pulls/9"):
            return json.dumps({"body": pr_body, "user": {"login": "dilux-bot[bot]"}})
        if args[:2] == ("api", "repos/o/r/pulls/9/commits"):
            return "\n".join(commits) + "\nfix: w\n\nCo-Authored-By: Claude <noreply@anthropic.com>\nCo-authored-by: boss <1+boss@users.noreply.github.com>\n"
        if args[:2] == ("pr", "view"):
            return "7\n"
        if args[:2] == ("api", "repos/o/r/issues/7/timeline"):
            return "boss\n"
        if args[0] == "api" and args[1].startswith("users/"):
            return json.dumps(users[args[1].split("/", 1)[1].lower()])
        raise RuntimeError(f"unexpected gh {args}")
    global gh
    real_gh, gh = gh, fake_gh
    try:
        got = body_of("o/r", "9", "merger")
        only = body_of("o/r", "9", "", True)
    finally:
        gh = real_gh
    check("C4: the squash body: the description, then each person once, no model, no bot, not the maintainer who accepted",
          got.split("---------\n\n", 1)[1].split("\n"),
          ["Co-authored-by: Cy <56+cy@users.noreply.github.com>", "Co-authored-by: Dee <78+dee@users.noreply.github.com>", "Co-authored-by: Eve <eve@example.org>"])
    check("C4: the description is kept verbatim before the separator", got.startswith(pr_body.rstrip("\n") + "\n\n---------\n\n"), True)
    check("C4: trailers alone", only, "Co-authored-by: Cy <56+cy@users.noreply.github.com>\nCo-authored-by: Dee <78+dee@users.noreply.github.com>\nCo-authored-by: Eve <eve@example.org>\n")
    check("C4: neither the bot nor the excluded maintainer is looked up", [a[1] for a in calls if a[0] == "api" and a[1].startswith("users/")].count("users/boss"), 0)
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv == ["models"]:
        found = models(sys.stdin.read())
        for trailer, use in found:
            print(f"{trailer}\t{use}")
        return 1 if found else 0
    if argv == ["block"]:
        body = sys.stdin.read()
        for e in read_block(body):
            print(f"{e['login']} {e['kind']}")
        return 0 if has_block(body) else 1
    if argv[:1] == ["write"] and len(argv) == 2:
        text = open(argv[1], encoding="utf-8").read()
        bad = [l for l in text.replace("\r", "").split("\n") if l.strip() and not ENTRY_RE.match(l)]
        if bad:
            print(f"Not an entry (- @login: co-author|suggested|reported (link)): {bad[0][:200]}", file=sys.stderr)
            return 1
        sys.stdout.write(set_block(sys.stdin.read(), parse_entries(text)))
        return 0
    if argv[:1] == ["command"] and len(argv) == 3:
        body, said = command(sys.stdin.read(), os.environ.get("COMMENT", ""), argv[1])
        with open(argv[2], "w", encoding="utf-8") as fh:
            fh.write(body)
        print("\n".join(f"- {line}" for line in said))
        return 0
    if argv[:1] in (["body"], ["trailers"]) and len(argv) in (3, 4):
        try:
            sys.stdout.write(body_of(argv[1], argv[2], argv[3] if len(argv) == 4 else "", argv[0] == "trailers"))
        except (RuntimeError, KeyError, ValueError) as err:
            print(f"::error::The credits could not be read from GitHub ({err}); nothing merges until they can.", file=sys.stderr)
            return 1
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
