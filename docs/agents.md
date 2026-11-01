# The flow, for an agent

How a change reaches a DiluxOne repository, written for an AI agent (and for the person who points it at a repository). It is the same for the maintainer's agents and for someone contributing from a fork. Every repository's `AGENTS.md` opens with the short version of these rules; this page is the long one, with the commands.

## Before you start

- You need `git` and `gh` (signed in), and a checkout of this repository beside the one you work in: `git clone https://github.com/DiluxOne/.github ../.github`. The commands below are `bash ../.github/scripts/dx.sh <step>`; call it `dx` for short.
- Read the repository's `AGENTS.md`: its own rules come after the organisation's.
- In a fork, `dx` sends issues and pull requests to the upstream repository on its own.

## 1. An accepted issue

Nothing starts without one: features, fixes, docs and maintenance alike, the maintainer's own work too.

- Look for an open issue that already describes the change.
- If there is none, open one: `dx issue --bug|--feature|--docs|--task --title "…" --body-file issue.md`, or on GitHub with the matching form. The kind becomes the issue's **Type** (Bug, Feature, Docs, Task). Write it in English: what is wrong or missing, what you expected, why it matters. For a bug, the steps, versions and logs. An issue the maintainer will accept carries a PRD: the sections of [`policy/issue-schema.yml`](../policy/issue-schema.yml) (`### Problem`, `### Scope`, `### Out of scope`, `### Acceptance criteria` with one `C1: Given …, when …, then …` per line, `### Criticality`), in that order and nothing outside them; `python3 scripts/issue-schema.py check < issue.md` says what is missing. A reporter's form (bug, feature) may come before them.
- **Check it before asking for acceptance.** When an issue opens and every time it is edited, the bot checks it against the schema and labels it `awaiting-acceptance` (complete, the maintainer decides) or `incomplete` (a comment says what is missing, #353). Ask the maintainer to accept it only when it carries `awaiting-acceptance`; never a bug the reproduction confirmed and handed to its lane, which the lane fixes with no acceptance and which loses that label (#427); run `python3 scripts/issue-schema.py check < issue.md` before you open or edit it, so it does not reach them incomplete. An `incomplete` issue that is accepted anyway loses the label, with a comment that names who added it.
- **An incomplete issue asks its questions.** The `incomplete` comment asks one question per missing part (the problem, the scope, what is out of scope, how each criterion is verified); answer them in a comment, as its author or someone who decides, and the bot rewrites the issue with the answers, shows what changed, and labels it `awaiting-acceptance` once it passes (#588). Anyone else's comment is summarised apart, as data.
- **Wait until a maintainer accepts it** with the `accepted` label. Never add it yourself, and never ask a bot to: the gate ignores a label a bot added. Who may add `accepted` and `autopilot:continue`, answer the autopilot and correct the credits is the setting `who-decides` (#588, org.yml and repos.yml: the code owners of what the change touches by default, the person who accepted it, or every writer; each with write access, and maintain for the credits): anyone else's label comes off with a comment that names who may. Editing an accepted issue's PRD withdraws the acceptance: it is `awaiting-acceptance` (or `incomplete`) again, and the bot says what changed since the seal. The issue triage may answer first: "not planned for the free plugin", "already planned", a question. That is the answer to the change as proposed; do not start it.

When the maintainer accepts an issue in a repository where the autopilot is on, the autopilot may take it: it writes the Spec, opens a draft pull request (label `autopilot`) with one box per criterion, and ticks each box as that criterion's commit lands. Follow it there and on the issue's board; do not start a pull request of your own for the same issue unless a maintainer assigned it to you before the autopilot started (the claim above). The same goes for a reported bug the reproduction confirmed: dilux-bot opens an issue of its own for the fix ("The bug reproduced from #n", `lane:bugfix-reproduced`), accepted by policy, and the autopilot works it; never run its reproduction test outside the sandbox (`scripts/repro-sandbox.sh` for a unit test, `scripts/repro-run.sh run-ref` for any other way, #397), since it was written from an outsider's text. A maintainer who takes an autopilot pull request over adds `needs-human`, removes `autopilot` and then pushes a commit of their own to its branch from a clone (the push runs the checks again; a label alone does not, and a commit made in GitHub's web editor is committed by `web-flow`, who is not a maintainer): from then on it is the maintainer's, and the size cap for authors outside the maintainers no longer applies to it.

## Who writes the code

**The autopilot does, in GitHub Actions.** Once an issue is accepted, the autopilot writes the change in GitHub Actions and opens its pull request. Nobody writes it on their own machine: not the maintainer, not the maintainer's agents, not someone working from a fork or a clone. This is the same rule for everyone.

**The one exception is a claim.** Someone who wants to write their own solution claims the issue first. They comment `/claim` on it, or tick "I want to work on this myself" in its form (#488): dilux-bot labels it `claimed`, names them, and says the dates, and the autopilot does not start on it (it is refused, with why, once the autopilot has started; a maintainer can hand it over with `/yield @login`). The steps below (a branch, `make pre-pr`, a pull request) are then theirs. A claim with no pull request and no push is reminded at 7 days and released at 10 (one comment saying "still on it" extends it once, never past 30 days), `/unclaim` releases it at once, and every release starts the autopilot, so an accepted issue is never held by nobody. A person with no merged pull request in the organisation holds one claim at a time, three with one. A maintainer's agent claims the same way before it works an issue by hand. Without a claim, an agent does not edit code locally: it opens or improves the issue, answers the autopilot's questions on its pull request, accepts or merges where the person it works for may, and, when the autopilot stops, gives it a hint and adds `autopilot:continue`. It never finishes the autopilot's pull request by hand.

The sections from here on are for the person who claimed the issue.

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
- Commit as Conventional Commits: `type(scope): subject`, **72 characters or fewer** (CI rejects more than 100; measure it), no trailing period. Bodies are plain paragraphs, one line each, never hard-wrapped. A model is never a co-author: end with `Assisted-by: <model> (<maker>)`, e.g. `Assisted-by: Claude Opus 5.5 (Anthropic)`, never a `Co-Authored-By:` naming a model (CONTRIBUTING.md, "Who signs what"); `Claude-Session:` is rejected. Credit the people whose proposals the change uses in the description's Credits block.
- A `docs` pull request may change only documentation. From outside the maintainers, only a `feat` may add new functionality (a plugin's settings, REST routes, AJAX endpoints, admin pages, post types, taxonomies, hooks, shortcodes, blocks): it needs a Feature issue. Such a pull request also changes at most 600 lines (translations and lock files aside): split a bigger change, each part with its issue (an autopilot pull request a maintainer took over counts as the maintainer's, and the organisation's bot from a branch of the same repository has no cap).

## 4. Check it

Fill in What changes and Why in `.git/dx/pr.md`, then `dx check`. It runs what CI will: first the repository's `make pre-pr`, every check its pull request and its merge queue run, one after the other (#479: every repository has one, whatever its stack; what it covers is its kind's pack, `kinds/<kind>/pack.yml` `pre-pr`, whose `pre-pr-make` the organisation writes into the repository's `dx.mk`, which its Makefile includes (`sync-repos.py pre-pr`), or its own `.github/review-policy.yml` `pre-pr` when it has no kind; in a repository without one it says so, and fails once org.yml `pre-pr` is `required`), then the conventions, the description, and the Claude review on your own account. Fix every blocker and major it lists (a pre-existing one, in code you did not touch, is listed but never stops you), commit, and run it again until it says "Ready for a pull request".

## 5. The pull request

Only when the person you work for says so: `dx pr`. It pushes the branch and opens the pull request upstream with that description. End anything you write on GitHub with one line saying AI took part: `🤖 AI-generated · <model> (<maker>)` when you wrote it, `🤖 AI-assisted · <model> (<maker>)` when a person did with your help. Never "Generated with …".

When something waits on a person, say who does what, with the full URL, one per line. To a maintainer: the action and its link ("Add `accepted` to https://github.com/DiluxOne/<repo>/issues/<n>", "Approve and merge https://github.com/DiluxOne/<repo>/pull/<n>"), never "the issue needs accepting" alone. To someone working from a fork or a clone, who cannot accept, approve or merge: never a maintainer's step; tell them a maintainer will review it and answer soon, with the link to where it waits.

Then CI runs the same checks. If you opened it before the issue was accepted, its gate fails; it runs again on its own when a maintainer accepts the issue, where the repository's `issues.yml` has the `accepted` job; otherwise push a commit (editing the description does not re-run it). On a fork's pull request the review does not run (no secret reaches code from a fork); a maintainer reviews it. Answer a review thread by fixing the code and pushing, or by replying with `@dilux-bot` (from a branch of the repository). A finding you do not fix is dismissed with a reply that starts with `wrong:`, `intentional:` or `does not matter:` and why, so the weekly digest counts it for what it was. Every conversation is resolved before a merge.

## Never

- Push to `main`, create or move a tag, or approve a release. A release is the issue "Release X.Y.Z" a person accepts: open one only when the person you work for says so, and never accept it.
- Add `accepted`, change an issue's Type to get past the gate, or start a change whose issue is not accepted.
- Put secrets, keys or personal data in a commit, an issue or a log.
