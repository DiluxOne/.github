# Contributing to DiluxOne projects

Thanks for helping. This is the default guide for every DiluxOne repository; a repository with its own `CONTRIBUTING.md` adds project-specific rules (setup, tests, release) on top of this.

## Before you start

- **Questions about using a plugin** go to its wordpress.org support forum, not to issues.
- **Security problems** go through private vulnerability reporting, never a public issue. See [SECURITY.md](SECURITY.md).
- **Bugs and ideas** go to the repository's issues, using its templates.

## Pull requests

1. Create a branch from `main`: in your fork if you are an outside contributor, in the repository itself if you are a maintainer.
2. Make the change, with tests, and update any doc that describes what you changed.
3. Open a pull request against `main` and fill in the template (see "Writing the pull request" below).
4. Wait for CI. Pull requests are squash-merged: the PR title becomes the commit title on `main` and the PR description becomes its body.

Nothing reaches `main` without a green pull request, maintainers included.

## Branch names

`<type>/<short-kebab-description>`, for example `fix/sync-retry-count` or `docs/install-guide`. Dependabot's own `dependabot/…` branches are the only exception.

## Commit messages and PR titles

We follow [Conventional Commits](https://www.conventionalcommits.org/). The first line (and the PR title) is `<type>(<optional-scope>): <subject>`, with type one of `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`. Keep it short: aim for 72 characters, CI rejects anything over 100, and do not end it with a period.

The body explains **why**: the problem, the context, the alternatives you considered. Write it in plain paragraphs, **one line per paragraph, without hard-wrapping**: GitHub, where these messages are read, wraps them for you, and hard-wrapped lines show up broken there. The commit on `main` takes its body from the pull request description, so the commits on your branch can be short.

```
fix(sync): retry a failed file once before reporting it

A single network blip marked files as failed even when the next attempt would succeed, and the user had to retry the whole batch by hand.

Retrying once inside the same batch fixes the common case without hiding a real outage: a second failure is still reported.
```

A `Co-Authored-By:` trailer is fine when a person or a tool contributed substantially. Session links (`Claude-Session:`) are rejected by CI.

Titles stay plain Conventional Commits, without emoji: tools read the type, and Dependabot writes them too. Emoji belong in the description's section headings and in the release notes, which group changes by type on their own (✨ features, 🐛 fixes, 📝 docs…).

## Writing the pull request

The description becomes the commit body on `main`, so it is part of the project's history. Write it for the person who reads it in a year:

- **📝 What changes:** one or two sentences, in plain words. Required.
- **💡 Why:** the problem it solves, and a link to the issue (`Closes #123`). Required.
- **🧪 How I tested it:** what you ran and what you checked.
- **📸 Screenshots:** before and after, for anything visible.
- Short paragraphs, no walls of text, no copy of the diff. Friendly and direct.

CI fails a pull request whose "What changes" or "Why" is empty (bots' are exempt).

## What CI checks

Every pull request runs the conventions check (branch name, PR title, every commit and the description) and the project's quality gates.

Pull requests from branches of the repository (not drafts, not forks) are reviewed by Claude, which comments inline on blockers and majors, lists minor findings in its summary and labels the risk and complexity.

- The first review reads the whole change; later ones read only what you pushed since, so keep pushes meaningful. Editing the title or description does not trigger a new review; an edited description counts as unchecked (no auto-merge) until the next push or the `review:full` label.
- The review decides the type of the change from the diff and sets it as a `type:*` label; it corrects the title's type to match (the version number is computed from these labels). If it is wrong, set a different `type:*` label yourself: the bot keeps a label a person set.
- Low-risk changes (docs, tests, lockfiles) get the light model; everything else the strong one.
- After 5 automatic reviews the next push keeps the last verdict and a human merges: add the `review:full` label, then push or re-run the review, to ask for another full pass.
- It merges on its own only when the change touches only low-risk paths, the review rated it low risk and low complexity without blocking, the description matches the code (nothing claimed the diff does not do, no behaviour change left unsaid), the author is a trusted maintainer (or Dependabot), every required check is green and the policy has auto-merge on. Anything else, a maintainer merges.

A maintainer merging by hand runs `scripts/squash-merge.sh <owner/repo> <number>` from a checkout of [DiluxOne/.github](https://github.com/DiluxOne/.github): it commits the description as written plus the branch's `Co-authored-by` trailers, because GitHub's own squash message hard-wraps at 72 columns. Auto-merge does the same.

Every conversation must be resolved before a pull request merges, the review's included. Fix the code and push: the next review resolves its own threads that the push fixed. Or answer in the thread mentioning `@dilux-bot`: Claude replies there and resolves its thread when you show it is not a problem. A maintainer can also resolve a thread by hand, with a reply that says why.

Pull requests from **forks** are not reviewed automatically: the review runs with the organisation's keys, and no code from outside the repository runs with them. A maintainer reviews and merges them.

## How a change becomes a version

Nobody types a version number. The `type:*` label the review sets on each merged pull request decides the next one (`type:breaking` → major, `type:feat` → minor, `type:fix` or `type:perf` → patch; a maintainer's `version:major|minor|patch` label wins), and `main` keeps the last released version in its files between releases. In a repository that publishes (a WordPress plugin):

- **Every push to `main` produces a development build**, the shipped tree stamped `<next>-dev.<N>`, as an artifact of the *Release* run in the Actions tab. Anyone can download it and try what is coming; it is not a release.
- **The changelog is written as the changes merge.** A pull request that changes what a user sees adds its bullet to the newest entry of `readme.txt` (`= X.Y.Z =`, first line `Unreleased.`), in the same pull request.
- **The maintainer decides when it is ready** by removing the `Unreleased.` line in a pull request. That push to `main` waits for approval in the repository's `wordpress-org` environment; only its required reviewers can approve, and approving publishes. Until then, however many pull requests merge, nothing waits for anyone and nothing is published.
- **Outside contributors** need nothing more than the pull request: your change ships in the next version with its bullet in the changelog. You cannot approve a release, and you do not need to.

## AI tools

Use any tool you like; you sign the commit and you own every line. Read what you submit, run the tests yourself, and never paste secrets into an AI service. Agents follow the repository's `AGENTS.md`.

### Saying that AI was involved

When AI took part, say so in one sober line at the end of the pull request description, with the model and its maker. Because the description becomes the commit body on `main`, the line lands in the history too.

```text
🤖 AI-assisted · Claude Opus 5.5 (Anthropic)
```

- **AI-assisted:** a person wrote or directed the change and an AI helped.
- **AI-generated:** an AI wrote the change and a person reviewed it.
- Several models: `🤖 AI-generated · Claude Opus 5.5, Claude Sonnet 5 (Anthropic)`.
- The same line closes any issue or pull request comment an agent writes for someone.
- No product advertising: CI rejects a description that says "Generated with Claude Code" or similar.

The Claude review's comments carry the same kind of line (`🤖 AI review · <model> (Anthropic)`, with the model id as the API names it), written by the workflow. Release notes are built by a script from the merged titles, so they carry no line.

## Code of Conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
