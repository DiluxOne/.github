# Contributing to DiluxOne projects

Thanks for helping. This is the default guide for every DiluxOne repository; a repository with its own `CONTRIBUTING.md` adds project-specific rules (setup, tests, release) on top of this.

## Before you start

- **Questions about using a plugin** go to its wordpress.org support forum, not to issues.
- **Security problems** go through private vulnerability reporting, never a public issue. See [SECURITY.md](SECURITY.md).
- **Bugs and ideas** go to the repository's issues, using its templates.

## Working with an AI agent

Most work here is done with AI agents. Point yours at the repository's `AGENTS.md`: it opens with the organisation's rules, and the step-by-step flow, with a command for each step (`dx issue`, `dx start`, `dx check`, `dx pr`), is in [DiluxOne/.github, `docs/agents.md`](https://github.com/DiluxOne/.github/blob/main/docs/agents.md). It works the same from a fork.

## Start from an issue

Every change starts as an issue: features, fixes and docs alike, maintainers included. Open one with the repository's template (or find the one that already describes it) and wait until a maintainer accepts it, which they do by adding the `accepted` label. The template sets the issue's **Type** (Bug, Feature, Docs or Task), and the pull request's type must fit it: a `feat` closes a Feature, a `fix` a Bug. A maintainer sets the Priority and the Project when accepting; the issue is assigned to whoever accepted it, and moves to the member of the organisation who opens the pull request that closes it (an outside contributor's pull request leaves it with the maintainer who accepted it). Then write the code, and say `Closes #<number>` in the pull request's description. CI fails a pull request that closes no accepted issue; bots' own pull requests (Dependabot, releases) are exempt.

**Working it yourself: claim it.** The code of an accepted issue is written by the autopilot, unless a person claims it first: comment `/claim` on the issue, or tick "I want to work on this myself" in its form (#488). dilux-bot labels it `claimed`, names you and says the dates, and the autopilot does not start on it. A claim made before acceptance is recorded, and its clock starts when the issue is accepted (for a bug, when it is reproduced: you get the failing test's branch, and your pull request must carry that test unchanged and make it pass). With no pull request and no push to a linked branch you are reminded at 7 days and the claim is released at 10; one comment saying "still on it" extends it once, never past 30 days; a maintainer exempts a long task by commenting `/claim long`. Your pull request stops the clock while it waits on a maintainer's review; with changes requested or failing checks and no push from you, it is reminded at 7 days and closed, with thanks, at 14 (reopen it when you come back). `/unclaim` releases it at once, and every release starts the autopilot, so no accepted issue waits on nobody. A person with no merged pull request in the organisation holds one claim at a time, three with one; a person without write access keeps at most 2 pull requests open across the organisation. The first one wins: once the autopilot has started, `/claim` is refused with why, and a maintainer can hand it over with `/yield @you`; a pull request opened without a claim while the autopilot works stays open beside the autopilot's, and the maintainer picks at review. A maintainer who wants to keep a stalled pull request reads it and comments `/adopt` (or `/adopt <sha>`): the autopilot continues from the commit they read, with its author as co-author.

Why: it is the cheapest moment to agree on what to build. A feature that is already planned, that belongs to a paid add-on, or that the project will not do is answered on the issue, before anyone spends time on code. An issue that is not accepted is not a "no" to the person, only to the change as proposed; the reply says why when it can.

**One decision for several repositories** is one issue a maintainer accepts. Each repository's part is a sub-issue of it (GitHub's sub-issues), opened by a member of the organisation or by dilux-bot: it needs no `accepted` of its own, because the `delegated` lane of the autonomy policy accepts it while its parent stays open and accepted, and as long as its text is not edited after it was linked. Its pull request goes through every check like any other. For a decision in DiluxOne/.github, its `Repositories` section says which repositories (`all`, `kind:`, `visibility:`, `has:`, `name:`), and accepting it opens their sub-issues on its own.

If the issue is accepted after the pull request was opened, the failed check runs again on its own when the maintainer accepts it, in a repository whose `issues.yml` has the `accepted` job; otherwise push a commit, or ask a maintainer to re-run it, and it passes.

## Pull requests

1. Create a branch from `main`: in your fork if you are an outside contributor, in the repository itself if you are a maintainer.
2. Make the change, with tests, and update any doc that describes what you changed. Sign every commit (GPG, SSH or S/MIME, [as GitHub explains](https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits)): GitHub shows it as "Verified". The bots' commits go through GitHub's API, which signs them.
3. Review it locally before you push (see "Review before the pull request" below): every review on GitHub costs money and a round of waiting, so the pull request should arrive clean.
4. Open a pull request against `main` and fill in the template (see "Writing the pull request" below).
5. Wait for CI. Pull requests are squash-merged: the PR title becomes the commit title on `main` and the PR description becomes its body.

Nothing reaches `main` without a green pull request, maintainers included.

## Branch names

`<type>/<short-kebab-description>`, for example `fix/sync-retry-count` or `docs/install-guide`. Dependabot's own `dependabot/…` branches are the only exception.

## Commit messages and PR titles

We follow [Conventional Commits](https://www.conventionalcommits.org/). The first line (and the PR title) is `<type>(<optional-scope>): <subject>`, with type one of `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`. Keep it short: aim for 72 characters, CI rejects anything over 100, and do not end it with a period. Dependabot's long grouped titles are the exception: the review shortens them, and their commits are not measured, since the squash keeps only the title.

The body explains **why**: the problem, the context, the alternatives you considered. Write it in plain paragraphs, **one line per paragraph, without hard-wrapping**: GitHub, where these messages are read, wraps them for you, and hard-wrapped lines show up broken there. The commit on `main` takes its body from the pull request description, so the commits on your branch can be short.

```
fix(sync): retry a failed file once before reporting it

A single network blip marked files as failed even when the next attempt would succeed, and the user had to retry the whole batch by hand.

Retrying once inside the same batch fixes the common case without hiding a real outage: a second failure is still reported.
```

Credit people with trailers, never a tool (see "Who signs what" below). Session links (`Claude-Session:`) are rejected by CI.

Titles stay plain Conventional Commits, without emoji: tools read the type, and Dependabot writes them too. Emoji belong in the description's section headings and in the release notes, which group changes by type on their own (✨ features, 🐛 fixes, 📝 docs…).

## Writing the pull request

The description becomes the commit body on `main`, so it is part of the project's history. Write it for the person who reads it in a year:

- **📝 What changes:** one or two sentences, in plain words. Required.
- **💡 Why:** the problem it solves, and the accepted issue it closes (`Closes #123`). Required; CI fails a pull request that closes no accepted issue.
- **🙌 Credits:** who proposed what the change uses, one `- @login: co-author|suggested|reported (<link>)` per line (see "Who signs what").
- **🧪 How I tested it:** what you ran and what you checked.
- **📸 Screenshots:** before and after, for anything visible.
- Short paragraphs, no walls of text, no copy of the diff. Friendly and direct.

CI fails a pull request whose "What changes" or "Why" is empty (bots' are exempt).

## Review before the pull request

[`scripts/local-review.sh`](scripts/local-review.sh) runs, on your machine, what the pull request will be checked on: the conventions ([`scripts/conventions.sh`](scripts/conventions.sh), the same script CI runs), the risk floor ([`scripts/policy.py`](scripts/policy.py)), and the Claude review on the same brief ([`scripts/review-brief.sh`](scripts/review-brief.sh): the review profiles, the repository's `AGENTS.md` and `docs/architecture.md`, the description and the diff), through the Claude Code CLI on your own account. It needs git, bash (the 3.2 of macOS will do), jq, python3 with yq or PyYAML (`brew install jq yq` on macOS) and, for the review itself, the Claude Code CLI. From the repository, with a checkout of this one:

```bash
bash ../.github/scripts/local-review.sh --body-file pr.md   # the description you will paste
```

The docs check CI also runs (relative links resolve, no retired product name) is not part of it. It reviews the branch against `origin/main`; the title is the branch's only commit, or `--title`. It ends with "Ready for a pull request" or "Not ready" for what would stop the pull request on GitHub: a broken convention, a blocker or a major the branch introduced (a pre-existing one, in code it did not touch, is listed but never stops it), a description the review says does not match the code, a title of another type than the change (on GitHub the review would retitle it). The findings go to `.git/dx-review/findings.md` (never committed), a list to fix; commit the fixes and run it again: like the review on a pull request, the next run reads only what changed since, sees the earlier findings and says which are fixed (`--full` reviews everything again; a run with nothing new since (same commit, title, description, model, profile and base) answers from the file without spending a review; `--model <id>` asks another model than the policy's). `--no-claude` stops at the brief, for another reviewer or agent to read. Every repository has a `make pre-pr` (#479, `scripts/pre-pr.py`): every check its pull request and its merge queue run, the test suites included, whatever its stack; `dx check` runs it before this review. CI still reviews the pull request: a branch that came out clean here should pass there in one round.

## What CI checks

Every pull request runs the conventions check (branch name, PR title, every commit, the description and the accepted issue it closes) and the project's quality gates. A pull request titled `docs` may change only documentation (Markdown, images under `docs/`, a plugin's `readme.txt`, licence files, the issue templates). One from someone outside the maintainers that is not a `feat` may not add new functionality (for a WordPress plugin: a setting or option, a REST route or AJAX endpoint, an admin page, a post type or taxonomy, a hook, a shortcode, a block): that needs its own Feature issue, accepted by a maintainer. One from someone outside the maintainers may change at most 600 lines, not counting `composer.lock`, `package-lock.json` and the translation files (`.po`, `.pot`, `.mo`) under `languages/`: split a bigger change into smaller pull requests, each with its accepted issue. An autopilot pull request a maintainer took over (`needs-human` added, `autopilot` removed, then a commit of the maintainer's own pushed from a clone) counts as the maintainer's: no cap. Nor has a pull request the organisation's own bot opens from a branch of the same repository (never from a fork).

Pull requests from branches of the repository (not drafts, not forks) are reviewed by Claude, which comments inline on blockers and majors, lists minor findings in its summary and labels the risk and complexity. A second agent, which did not write them, confirms each new blocker and major against the code before it is posted; one it rejects stays in the summary as a minor marked not confirmed. Its comment opens with the count of what is left to fix, or says nothing needs fixing; a finding about code the pull request did not introduce is marked pre-existing, never inline and never blocking.

- To dismiss a blocker or major instead of fixing it, reply on its thread starting with `wrong:`, `intentional:` or `does not matter:` and why, then resolve it. The weekly digest counts what became of every finding, and that word is how a dismissed one counts for what it was (`scripts/review-outcomes.py`).

- The first review reads the whole change; later ones read only what you pushed since, so keep pushes meaningful. Editing the title or description does not trigger a new review; an edited description counts as unchecked (no auto-merge) until the next push or a maintainer's `/review full`.
- The review decides the type of the change from the diff and sets it as a `type:*` label; it corrects the title's type to match (the version number is computed from these labels). If it is wrong, set a different `type:*` label yourself: the bot keeps a label a person set.
- Every change is reviewed by the same model; the risk decides the effort: low for docs, tests and lockfiles, medium for ordinary code, high for high-risk changes.
- After 5 automatic reviews the next push keeps the last verdict and a human merges: comment `/review full`, then push or re-run the review, to ask for another full pass.
- It merges on its own only when the change touches only low-risk paths, the review rated it low risk and low complexity without blocking, the description matches the code (nothing claimed the diff does not do, no behaviour change left unsaid), the author is a trusted maintainer (or Dependabot), every required check is green and the policy has auto-merge on. Anything else, a maintainer merges.

A maintainer merging by hand runs `scripts/squash-merge.sh <owner/repo> <number>` from a checkout of [DiluxOne/.github](https://github.com/DiluxOne/.github): it commits the description as written plus the credits' trailers (the Credits block's people and the branch's human `Co-authored-by`, never a model, a bot or a maintainer who accepted or merges; [`scripts/credits.py`](scripts/credits.py)), because GitHub's own squash message hard-wraps at 72 columns. Auto-merge does the same, for the merge queue too.

Every conversation must be resolved before a pull request merges, the review's included. Fix the code and push: the next review resolves its own threads that the push fixed. Or answer in the thread mentioning `@dilux-bot`: Claude replies there and resolves its thread when you show it is not a problem. A maintainer can also resolve a thread by hand, with a reply that says why.

Pull requests from **forks** are not reviewed automatically: the review runs with the organisation's keys, and no code from outside the repository runs with them. A maintainer reviews and merges them.

## How a change becomes a version

Every DiluxOne repository numbers its versions `X.Y.Z`, always three numbers, no suffix, by what a change means to the people who use it:

| Part | When | Who decides |
| --- | --- | --- |
| **Major** `X.0.0` | A big new capability (a new provider, a new flow the product did not have), **or** any change that breaks something that worked | The maintainer, with the `version:major` label on the pull request. A breaking change (`type:breaking`, `!` in the title) forces it on its own |
| **Minor** `x.Y.0` | Additions and improvements to what already exists, compatible with it | Automatic: `type:feat` |
| **Patch** `x.y.Z` | Bug fixes, security fixes and performance, with no new behaviour | Automatic: `type:fix`, `type:perf` |

Two rules come with it:

- **A breaking change ships only in a major**, and a minor before it announces it ("this is going away in the next major"). Breaking means a user, a site or a caller has to change something to keep working: a new minimum requirement, a removed option, a setting that changes meaning, a renamed hook, data that cannot go back to the previous version.
- **Every major says in its changelog** `Breaking changes: none`, or lists them with what to do.

"Big" is a person's call: the review suggests `version:major` when a pull request looks like a new capability, and never sets it. A big `feat` is still a `feat`, not a breaking change.

Nobody types a version number. The `type:*` label the review sets on each merged pull request decides the next one (`type:breaking` → major, `type:feat` → minor, `type:fix` or `type:perf` → patch; a maintainer's `version:major|minor|patch` label wins). `main` names a real version in its files: the last one released, or, from the moment the pull request that releases the next one merges, that next one; the checks hold every pull request to it. In a repository that publishes (a WordPress plugin):

- **Every push to `main` publishes a development build**, the shipped tree stamped `<next>-dev.<N>`, as the one *Development build* pre-release in the repository's Releases, replaced each time (no history: the commit in its notes rebuilds any of them). Anyone can download it and try what is coming; it is not a release, and "Latest" stays the last published version.
- **The changelog is written as the changes merge.** A pull request that changes what a user sees adds its bullet to the newest entry of `readme.txt` (`= X.Y.Z =`, first line `Unreleased.`), in the same pull request.
- **A release is an issue, and a person accepting it is the decision to publish.** The maintainer opens "Release X.Y.Z" with the Release form (title exactly `Release X.Y.Z`, the version the labels give; label `lane:release`) and accepts it. Accepting it opens the release pull request on its own: the `Unreleased.` line removed and the version markers set to that version (`scripts/release-markers.sh prepare`, the command the repository's kind names), closing the issue. It goes through the checks and the review like any other. When it merges, the release workflow checks that a person (never a bot) with the admin or maintain role on the repository accepted that issue (triage or write is not enough to publish) and that its title still names the version it computed, then publishes; a title changed after the acceptance needs a new one. The bot opens one only when a person closes the version's milestone `X.Y.Z` (the next daily run, `scripts/milestones.py`), and no policy accepts one. A repository whose environment still has required reviewers is also asked there; without an accepted release issue, those reviewers are the only other approval, and without either nothing is published (a repository's policy can set a kind of bump to `auto`, published without waiting, or `off`, never published; the organisation default is to wait). Until then, however many pull requests merge, nothing waits for anyone and nothing is published.
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
- Several models: `🤖 AI-generated · Claude Opus 5.5, Claude Sonnet 5.5 (Anthropic)`.
- The same line closes any issue or pull request comment an agent writes for someone.
- No product advertising: CI rejects a description that says "Generated with Claude Code" or similar.

### Who signs what

A model is never a co-author: the field is moving away from it (the Linux kernel and LLVM ask for `Assisted-by:` and never let a tool sign), and a model cannot be an author. People are, and the credit in the history is what brings contributors back. The rule is the same in every repository (the organisation's block of each `AGENTS.md`):

- A commit written with a model's help ends with `Assisted-by: <model> (<maker>)`, e.g. `Assisted-by: Claude Opus 5.5 (Anthropic)`. A `Co-authored-by` that names a model (`Co-Authored-By: Claude <noreply@anthropic.com>`, Copilot, Gemini, ChatGPT, Codex…) is refused by the conventions check, which names the `Assisted-by:` line to use (a warning while org.yml `attribution` is `warn`, a failure once it is `required`). Claude Code adds its own trailer unless its settings say `"includeCoAuthoredBy": false`.
- A person is a co-author, `Co-authored-by: Name <id+login@users.noreply.github.com>`, when they wrote commits of the pull request, opened the issue whose "Proposed solution" it uses, proposed in a comment on the issue what it uses, or claimed the issue and wrote code for it. `Suggested-by:` credits an idea used in part, `Reported-by:` a report without a proposal that was used. The address is always GitHub's noreply form, built from the account's id, never a private e-mail.
- Never a co-author: the maintainer who accepts or merges, dilux-bot, Dependabot, any bot, a model.

The pull request lists the people in its description's Credits block, which the autopilot fills in and anyone else writes by hand; a maintainer corrects it with `/coauthor @login` and `/uncoauthor @login` on the pull request, and the bot says what changed. The merge writes the trailers at the end of the commit on `main`:

```text
## 🙌 Credits

<!-- dx-credits -->
- @ana: co-author (https://github.com/DiluxOne/example/issues/12)
- @bob: suggested (https://github.com/DiluxOne/example/issues/12#issuecomment-345)
<!-- /dx-credits -->
```

becomes, under the description:

```text
---------

Co-authored-by: Ana Pérez <1234+ana@users.noreply.github.com>
Suggested-by: bob <5678+bob@users.noreply.github.com>
```

Every issue form has an optional "Proposed solution": fill it in, and if the change uses it, you are credited as its co-author.

The Claude review's comments carry the same kind of line (`🤖 AI review · <model> (Anthropic)`, with the model id as the API names it), written by the workflow. Release notes are built by a script from the merged titles, so they carry no line.

## Code of Conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
