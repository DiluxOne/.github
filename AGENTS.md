# AGENTS.md

<!-- dx:org:start (kept in step by DiluxOne/.github, scripts/sync-repos.py; edit it there) -->
## The organisation's rules (the same in every DiluxOne repository)

You are working in a DiluxOne repository. Whoever you work for (the
maintainer, or someone contributing from a fork), these hold here, and the
step-by-step flow with its commands is in
[DiluxOne/.github, `docs/agents.md`](https://github.com/DiluxOne/.github/blob/main/docs/agents.md):

1. **Nothing starts without an accepted issue.** Find the issue, or open one
   with the form that fits (it sets the issue's Type: Bug, Feature, Docs or
   Task), and wait until a maintainer adds the `accepted` label. Never add it
   yourself. The pull request says `Closes #<number>`; CI fails it otherwise.
2. **The pull request's type fits the issue's Type**: `feat` (or any `!`)
   closes a Feature, `fix` a Bug; other types close any accepted issue.
3. **Branch** `<type>/<number>-<short-kebab>`; **commit and title** as a
   Conventional Commit of 72 characters or fewer (CI rejects more than 100);
   bodies are plain paragraphs, never hard-wrapped; no `Claude-Session:`.
4. **Check before the pull request** (`dx check`, or the repository's
   `make pre-pr`) and open it (`dx pr`) only when the person you work for
   says so.
5. **Never** push to `main`, create or move a tag, or approve a release.
6. **Say AI took part** with one line at the end of what you write on GitHub:
   `🤖 AI-generated · <model> (<maker>)` when you wrote it,
   `🤖 AI-assisted · <model> (<maker>)` when a person did with your help.
   Never "Generated with …".
<!-- dx:org:end -->

Rules for any coding agent working in `DiluxOne/.github`.

- This repository defines how every DiluxOne repository is checked, reviewed,
  merged and released. A mistake here reaches all of them at once. Every change
  is high risk and is merged by a human, except one that touches only the
  pages people read (README.md, profile/, and docs/ but what agents and the
  review read as rules: docs/agents.md, docs/architecture.md,
  docs/testing-and-quality.md), which can merge on its own like a docs change
  anywhere (.github/review-policy.yml).
- Workflows are reusable (`on: workflow_call`) unless they are specific to this
  repository. Name them after what they do; add a stack suffix (`-wp`) only
  when the steps are stack-specific.
- Nothing is hard-wired to one kind of project. What is specific to a kind
  (its review profile, rules, settings, the list of its workflows) lives in
  its pack, `kinds/<kind>/`, as data; scripts and workflows read it from
  there. A rejection a review sends back becomes one entry in the kind's
  `rules.yml`, with its source and its fixtures, never a new script or
  workflow (`kinds/README.md`).
- Pin every third-party action to a full commit SHA with the version in a
  comment (`uses: owner/action@<sha> # vX.Y.Z`). Declare the minimum
  `permissions:`. Pass untrusted text (titles, branch names) through `env:`,
  never `${{ }}` inside a `run:` script.
- Nothing that runs with secrets may run on a fork's code.
- Branches, PR titles and commits follow Conventional Commits; CI enforces it.
  Write headers of 72 characters or fewer: 100 is where CI and the commit-msg
  hook reject them, not a target. Measure a header before committing it
  (`printf %s "$subject" | wc -m`) instead of finding out from the hook.
  PR descriptions use the template sections (What changes and Why are
  required); commit and PR bodies are plain paragraphs, never hard-wrapped.
- When you write a pull request, issue or comment, end it with the AI line from
  CONTRIBUTING.md ("Saying that AI was involved"), e.g.
  `🤖 AI-generated · Claude Opus 5.5 (Anthropic)`. Never "Generated with …".
- Never push to `main`, create or move tags, or change organisation settings.
- Before a pull request exists, run `scripts/local-review.sh` (CONTRIBUTING.md,
  "Review before the pull request"), fix every blocker and major listed in
  `.git/dx-review/findings.md` (and the minors that are cheap), commit, and
  run it again until it says "Ready for a pull request". Do not push, open a
  pull request or re-run a workflow unless the maintainer asked for it: every
  push to an open pull request is a paid review.
- A problem a review finds (local or on GitHub) that a test could have
  caught comes with that test, in the same pull request: what was found once
  is not left to the next review to find again. Every script carries its
  `--test`, run by the scripts job.
- Keep `README.md` (short: what this is, the flow, links), `docs/` (the
  details), `CONTRIBUTING.md`, `kinds/README.md`, the review
  profiles, the packs, the workflow templates and the workflow header
  comments in step with what the workflows do, in the same PR.
