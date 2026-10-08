# The flow, for an agent

How a change reaches a DiluxOne repository, written for an AI agent (and for the person who points it at a repository). It is the same for the maintainer's agents and for someone contributing from a fork. Every repository's `AGENTS.md` opens with the short version of these rules; this page is the long one, with the commands.

## Before you start

- You need `git` and `gh` (signed in), and a checkout of this repository beside the one you work in: `git clone https://github.com/DiluxOne/.github ../.github`. The commands below are `bash ../.github/scripts/dx.sh <step>`; call it `dx` for short.
- Read the repository's `AGENTS.md`: its own rules come after the organisation's.
- In a fork, `dx` sends issues and pull requests to the upstream repository on its own.

## 1. An accepted issue

Nothing starts without one: features, fixes, docs and maintenance alike, the maintainer's own work too.

- Look for an open issue that already describes the change.
- If there is none, open one: `dx issue --bug|--feature|--docs|--task --title "…" --body-file issue.md`, or on GitHub with the matching form. The kind becomes the issue's **Type** (Bug, Feature, Docs, Task). Write it in English: what is wrong or missing, what you expected, why it matters. For a bug, the steps, versions and logs.
- **Wait until a maintainer accepts it** with the `accepted` label. Never add it yourself, and never ask a bot to: the gate ignores a label a bot added. The issue triage may answer first: "not planned for the free plugin", "already planned", a question. That is the answer to the change as proposed; do not start it.

## 2. A branch for it

`dx start <number>` checks that the issue is open and accepted and creates the branch `<type>/<number>-<slug>` from the default branch, with the type its Type asks for:

| The issue's Type | The pull request's type |
| --- | --- |
| Feature | `feat` (or any type with `!` for a breaking change) |
| Bug | `fix` |
| Docs | `docs` |
| Task | `refactor`, `test`, `ci`, `build`, `chore`, `perf` or `style`, as fits (`--type`) |

CI holds you to it: a `feat` or `!` pull request must close a Feature, a `fix` a Bug. It also writes the pull request's description to `.git/dx/pr.md`, already closing the issue.

## 3. The change

- Follow the repository's `AGENTS.md`, its plan and its tests.
- Commit as Conventional Commits: `type(scope): subject`, **72 characters or fewer** (CI rejects more than 100; measure it), no trailing period. Bodies are plain paragraphs, one line each, never hard-wrapped. `Co-Authored-By:` is fine; `Claude-Session:` is rejected.
- A `docs` pull request may change only documentation. From outside the maintainers, a pull request changes at most 600 lines (translations and lock files aside): split a bigger change, each part with its issue.

## 4. Check it

Fill in What changes and Why in `.git/dx/pr.md`, then `dx check`. It runs what CI will: the conventions, the description, and the Claude review on your own account. Fix every blocker and major it lists, commit, and run it again until it says "Ready for a pull request".

## 5. The pull request

Only when the person you work for says so: `dx pr`. It pushes the branch and opens the pull request upstream with that description. End anything you write on GitHub with one line saying AI took part: `🤖 AI-generated · <model> (<maker>)` when you wrote it, `🤖 AI-assisted · <model> (<maker>)` when a person did with your help. Never "Generated with …".

Then CI runs the same checks. If you opened it before the issue was accepted, its gate fails; it runs again on its own when a maintainer accepts the issue (editing the description does not re-run it). On a fork's pull request the review does not run (no secret reaches code from a fork); a maintainer reviews it. Answer a review thread by fixing the code and pushing, or by replying with `@dilux-bot` (from a branch of the repository). Every conversation is resolved before a merge.

## Never

- Push to `main`, create or move a tag, or approve a release.
- Add `accepted`, change an issue's Type to get past the gate, or start a change whose issue is not accepted.
- Put secrets, keys or personal data in a commit, an issue or a log.
