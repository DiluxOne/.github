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
  credits.py --test            self-test
"""
import re
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
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
