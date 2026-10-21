#!/usr/bin/env python3
"""Whether a report is reproduced now, or waits for a person (#287).

A stranger's report starts a paid run with no person in between, so a flood
stops here: at most MAX issues opened in the repository in 24 hours (not by
the bot) and MAX_AUTHOR by the report's author. A maintainer's report, the
nightly review's (dilux-bot's), and a run a maintainer started (adding
`repro:run`) are never held: every bug found is worked. A count that could
not be read (empty) holds the report, never lets it through.

    repro-cap.py decide   AUTHOR, AUTHOR_ROLE, SENDER_ROLE (role_name, read
                          live, or empty), ALL, MINE (the counts, or empty),
                          MAX, MAX_AUTHOR: prints run=true|false and why
    repro-cap.py --test
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import org  # noqa: E402  the organisation's App, from org.yml (#191, #197)

BOT = org.BOT
MAINTAINERS = ("admin", "maintain", "write")


def decide(author, author_role, sender_role, all_, mine, cap, cap_author):
    """(run, why). Pure."""
    if author == BOT:
        return True, "the nightly review's report is never held"
    if author_role in MAINTAINERS:
        return True, "a maintainer's report is never held"
    if sender_role in MAINTAINERS:
        return True, "a maintainer asked for it"
    if not str(all_).isdigit() or not str(mine).isdigit():
        return False, "the counts could not be read; it waits for a person"
    if int(mine) > cap_author:
        return False, f"its author opened {mine} issues in 24 hours (cap {cap_author}); it waits for a person"
    if int(all_) > cap:
        return False, f"{all_} issues were opened in 24 hours (cap {cap}); it waits for a person"
    return True, f"{all_} of {cap} today, {mine} of {cap_author} by its author"


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    run = lambda *a: decide(*a)[0]
    check("a stranger within both caps runs", run("x", "read", "", "5", "1", 20, 3), True)
    check("past the author's cap, or the repository's, it waits", (run("x", "read", "", "5", "4", 20, 3), run("x", "read", "", "21", "1", 20, 3)), (False, False))
    check("the bot's, a maintainer's, or one a maintainer asked for always runs",
          (run(BOT, "", "", "999", "999", 20, 3), run("boss", "admin", "", "999", "999", 20, 3), run("x", "read", "maintain", "999", "999", 20, 3)), (True, True, True))
    check("a count that could not be read holds it", (run("x", "read", "", "", "1", 20, 3), run("x", "read", "", "5", "", 20, 3)), (False, False))
    # #197: another organisation's App, named by its DX_BOT_LOGIN (org.py).
    import subprocess
    env = dict(os.environ, DX_BOT_LOGIN="acme-bot[bot]", DX_BOT_APP="acme-bot", DX_BOT_ID="7",
               AUTHOR="acme-bot[bot]", AUTHOR_ROLE="", SENDER_ROLE="", ALL="999", MINE="999")
    out = subprocess.run([sys.executable, os.path.abspath(__file__), "decide"], env=env, capture_output=True, text=True).stdout.strip()
    check("#197: another organisation's App's report always runs", out, "run=true")
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv == ["decide"]:
        e = os.environ.get
        ok, why = decide(e("AUTHOR", ""), e("AUTHOR_ROLE", ""), e("SENDER_ROLE", ""), e("ALL", ""), e("MINE", ""),
                         int(e("MAX", "20")), int(e("MAX_AUTHOR", "3")))
        print(f"run={'true' if ok else 'false'}")
        print(why, file=sys.stderr)
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
