# Plan: configure the organisation once

Every DiluxOne repository carries, today, its own copy of the same setup: the `main` and tag rulesets, the callers of the pull request pipeline, issue forms, the contributing and security guides, labels and merge settings. A change to any of them means touching every repository, and they drift. GitHub Team lets most of it live at the organisation. This plan says what moves there, what stays in each repository, and in which order. Agreed with the maintainer on 8 October 2026 (issue #28).

The rule: **what is the same for every repository is configured once, at the organisation or in this repository; a repository keeps only what is its own.**

## What lives at the organisation

| What | Where | How it reaches every repository |
| --- | --- | --- |
| Issue **Type**: Feature, Bug, Task, Docs | Organisation settings, issue types | Native; the issue forms set it, the accepted-issue gate reads it |
| Issue fields: **Priority** | Organisation settings, issue fields | Native; the maintainer sets it when accepting |
| **Projects**, one per product (the free plugin and its Pro add-on together) | Organisation Projects | Built-in workflows: an issue labelled `accepted` is added with Status *Accepted*; closed or merged moves it to *Done* |
| Protection of `main` and of release tags | **Organisation rulesets**, all repositories | One ruleset for `main` (pull request only, squash, linear history, conversations resolved, required checks) and two for `X.Y.Z` tags (created only by administrators and the release App; never moved or deleted) |
| The pull request pipeline: conventions, the accepted-issue gate, the Claude review, the auto-merge decision | A **required workflow** in this repository, demanded by the organisation's `main` ruleset | Runs on every pull request of every repository with no file in it. Its jobs keep today's names (`conventions / …`, `review / Claude review`), so the required checks do not change. As today, the conventions and the gate run on a fork's pull request with a read-only token and no secret, and the review, which needs secrets, skips forks |
| Issue forms, pull request template, `CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`, code of conduct | This repository's community files | GitHub's defaults for every repository that has none of its own |
| Labels (`accepted`, the triage's, the review's) | `labels.yml` here | `scripts/sync-repos.py`, run by the maintainer, creates or updates them everywhere |
| Merge and security settings (squash only, auto-merge, delete branch, squash title and body from the pull request, Dependabot alerts, secret scanning where the plan has it) | `repos.yml` here | The same script |
| Secrets and the bots (`dilux-bot`, `dilux-release`) | Organisation secrets and Apps | Already there |

## What stays in each repository

Only what is its own:

- `AGENTS.md`, `CLAUDE.md`, `README.md`, `docs/` (the roadmap and the plans).
- `.github/review-policy.yml`: its kind of project, its high-risk paths, and `paid-roadmap:` for a free plugin with a Pro add-on.
- The callers GitHub cannot require from the organisation, because required workflows run only on pull requests: the issue triage and reproduction (`issues.yml`) and the replies to `@dilux-bot` (`pull-request-comments.yml`). Two small files, from `workflow-templates/`.
- The checks of its kind that need its own values (a WordPress plugin's slug for Plugin Check, its test suites, its release): the `-wp` callers. Whether these can become required workflows reading the slug from the policy is step 6.
- `.github/dependabot.yml` and `.github/CODEOWNERS`, which GitHub reads only from the repository (the sync script can write the same `CODEOWNERS` everywhere).
- A `CONTRIBUTING.md` of its own only when it has something the organisation's cannot say (Offload's real-storage suites), and then it links to the organisation's for the rest.

Everything else a repository has today and the organisation now provides is deleted from it: its rulesets, `pull-request.yml` and `pull-request-edited.yml` where the required workflow replaces them, its issue forms and its copies of the community files.

## The accepted issue

The gate stays on the label: `accepted`, added by a person, is the only thing that lets a pull request through, because it lives on the issue, the repository's own token reads it, and its history says who added it. The Project shows it: an issue labelled `accepted` lands on its product's board as *Accepted* on its own. The issue's native **Type** must fit the pull request's: a `feat` or `!` closes a Feature, a `fix` a Bug, and any other type (docs, refactor, test, ci, build, chore, perf, style, revert) closes any accepted issue, a Task or a Docs one among them. The `type:*` labels stay on pull requests only, where the review sets them from the diff.

## Repositories

Every repository of the organisation follows this, products and tools alike, `diluxone-wp-test` included. `ards-web`, a client's site, is not a DiluxOne product: it moves to the maintainer's personal account (its deployment uses repository secrets, which move with it). Mail is already there.

| Product | Repositories | Project |
| --- | --- | --- |
| Offload | `diluxone-offload-wordpress` | Offload |
| Users+ | `diluxone-users-wordpress`, `diluxone-users-pro-wordpress` | Users+ |
| Multisite User Sync | `diluxone-multisite-user-sync-wordpress` | Multisite User Sync |
| Comments | `diluxone-comments-wordpress`, `diluxone-comments-pro-wordpress` | Comments |
| Help | `diluxone-help-wordpress` | Help |
| Support | `diluxone-support-wordpress` | Support |
| Commerce | `diluxone-commerce-wordpress` | Commerce |
| Slider | `diluxone-slider-wordpress` (not on GitHub yet) | Slider |
| The organisation's tooling | `.github`, `diluxone-wp-test` | Platform |

## Easy for every agent, ours and a contributor's

Most work here is done by AI agents: the maintainer's, and the ones an outside contributor points at a fork. The flow has to be something an agent can follow from a clone, with no knowledge of this conversation:

- **One flow, written once.** `docs/agents.md` in this repository says it step by step, with the exact commands: find or open the issue (with the form that sets its Type), wait for `accepted`, branch, work, check locally, open the pull request with `Closes #<n>`. The organisation's `CONTRIBUTING.md` says the same for people and tells them to point their agent at `AGENTS.md`.
- **The same opening in every `AGENTS.md`.** Each repository's `AGENTS.md` starts with a short block, the same everywhere and kept in step by the sync script between `<!-- dx:org -->` markers: what the organisation's rules are, that nothing starts without an accepted issue, and where the flow is. Below it, only what is the repository's own.
- **A small command for each step**, `scripts/dx.sh` in this repository, which any clone or fork can run (from a checkout of this repository beside it, or fetched at a pinned version):
  - `dx issue`: opens an issue with the right form and Type, from flags or by asking.
  - `dx start <n>`: checks that the issue is accepted and its Type, and creates the branch (`<type>/<n>-<slug>`).
  - `dx check`: the conventions, the gate as CI will see it, and the local review.
  - `dx pr`: opens the pull request with the template filled and `Closes #<n>`.
  
  It works the same on a fork: the issue is read from the upstream repository.
- **Errors that say what to do.** Every check that fails names the step of the flow that was skipped and the command that fixes it.

## Order

Each step is one pull request here (with its accepted issue) or one change of settings, and the next starts when the maintainer says so.

1. **This plan**, merged.
2. **v5 of the shared workflows.**
   - The accepted-issue gate reads the native issue Type.
   - The organisation's issue forms set it.
   - A new `org-pull-request.yml`, the pipeline as one workflow a ruleset can require: it reads each repository's policy and kind from the repository itself.
   - `labels.yml`, `repos.yml` and `scripts/sync-repos.py` (labels, settings, `CODEOWNERS` and the `AGENTS.md` opening block).
   - `docs/agents.md` and `scripts/dx.sh`, the agent's flow and its commands.
   - The README's adoption section rewritten for the organisation.

   Breaking: v4's `type:*` labels on issues no longer count.
3. **Organisation rulesets in evaluate mode**, next to the repositories' own, until a week of pull requests shows they decide the same. Then active, and each repository's own rulesets deleted.
4. **The required workflow**: the `main` ruleset requires `org-pull-request.yml`; each repository's `pull-request.yml` and `pull-request-edited.yml` are deleted, in the same pull request that adopts v5 there.
5. **Projects**, one per product, with Status (Inbox, Accepted, In progress, In review, Done) and the organisation's Priority, and their built-in workflows. The maintainer's `gh` needs the `project` scope (`gh auth refresh -s project`).
6. **The kind's checks as required workflows**, if a WordPress plugin's values can come from its policy; otherwise they stay as callers.
7. **Each repository**, in its own session, with the instructions below.
8. **`ards-web`** transferred to the maintainer's account.

## Instructions for each repository's agent

When the maintainer asks a repository to adopt this:

1. Open the issue for it (the maintenance-task form, Type Task) and wait until the maintainer accepts it.
2. On a branch:
   - Delete what the organisation now provides: `.github/ISSUE_TEMPLATE/`, `.github/pull_request_template.md`, `SECURITY.md`, `CONTRIBUTING.md` (unless it has something of its own: then keep only that, linking to the organisation's), `pull-request.yml` and `pull-request-edited.yml`. Keep `CODEOWNERS`.
   - Keep `issues.yml`, `pull-request-comments.yml`, the `-wp` callers, `dependabot.yml` and `review-policy.yml`, on `@v5`.
3. Update `AGENTS.md`:
   - "Start from an issue": the native Type must fit the pull request.
   - Commit headers of 72 characters or fewer.
   - The free or paid decision lives in the Pro add-on's roadmap; a free plugin with a Pro add-on names it with `paid-roadmap:`.
4. Pull requests already open close an accepted issue too (`Closes #<n>`).
5. A repository still on v2 moves through v3 first ("Migrating from v2 to v3" in the README).

The maintainer runs `scripts/sync-repos.py` for the labels and settings, which it changes through the API, and deletes the repository's own rulesets once the organisation's are active. What the script writes into files (`CODEOWNERS`, the opening block of `AGENTS.md`) never goes straight to `main`: it opens one pull request per repository, closing an issue it opens there for the maintainer to accept, like any other change.
