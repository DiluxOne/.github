# Release automation: the type of a change, the next version, the tag

Status: proposal, 2026-09-26, reviewed for security, cost and against the tools the market uses. Decision of the maintainer: the release is approved as a **deployment** (the job on `main` builds, waits for approval in the `wordpress-org` environment, then tags and publishes), not as a release pull request; sections C and E are being rewritten to that; the security fixes the review asked for ship first (DiluxOne/.github#3). Not implemented yet.

## Goals, in the maintainer's words

1. The type of every change (feature, fix, docs, breaking) is decided by the AI from the diff, not by whoever typed the title, and is visible as a label.
2. Whether a change calls for a new version, and which number, is decided by the same rules automatically; the maintainer approves the release (for now); later, the approval can be automatic per repository and per kind of bump.
3. Development builds carry the version that is coming (`X.Y.Z-dev.N`), computed, never typed and never asked for.
4. Every real change runs the full pipeline once. Cutting a release runs nothing twice. Reviews stay cheap.
5. Nobody, and no workflow, can publish a version that did not go through the full pipeline.

## What the market does

- **release-please** (Google): on every push to `main`, parses Conventional Commits since the last release, opens or updates one "Release PR" that bumps the version files and the changelog; merging that PR creates the tag and the GitHub release. The human gate is the merge. Version comes from commit types only.
- **semantic-release**: same analysis, no PR: it tags and publishes on every push to `main`. No human gate.
- **conventional-changelog / commitlint**: the format rule and the changelog generator behind both.

This design is release-please with two changes: the type comes from the AI's reading of the diff (labels), not from the human's commit message; and the release PR is recognised by the pipeline so it does not re-run the slow suites.

## A. The type of a change

- The review (`claude-review.yml`) already reads the whole diff. It returns one more field in its record: `type`, one of `breaking`, `feat`, `fix`, `perf`, `refactor`, `docs`, `test`, `ci`, `build`, `chore`.
- The bot sets the label `type:<type>` on the pull request and, when the title's prefix disagrees, retitles the pull request to match (the bot has `pull-requests: write`). The conventions check keeps validating the format; the type itself is now the review's.
- A human can override: setting a different `type:*` label by hand wins over the bot (the bot only replaces a `type:*` label it set itself, read from the label's timeline actor). A `version:major` / `version:minor` / `version:patch` label on any pull request forces that bump for the release that includes it.
- The labels are created in every repository by the central (`scripts/labels.sh`, run at adoption and idempotent).

## B. The next version, and the dev version

- `scripts/next-version.py` (central) is deterministic: from the labels of the pull requests merged into `main` since the last tag, `breaking` → major, `feat` → minor, `fix`/`perf` → patch, everything else → nothing to release; a `version:*` label overrides. It prints the pending bump, the next version and the list of pull requests per type. The AI does not pick the number; it picks the type. The number is auditable from the labels.
- **Dev builds.** Nothing about the version is stored on `main` beyond the marker the release doc already prescribes (`X.Y.Z-dev` in the plugin header, set by the bump-back PR after a release). Every build that is not a release (`make dist`, `make deploy-test`, the CI artifact) stamps `Version: <next>-dev.<N>` where `<next>` comes from `next-version.py` and `N` is the number of commits since the last tag, and writes the short commit into the plugin's Status › System screen. The maintainer who installs a build sees `2.1.0-dev.14` and knows a minor release is pending and which build it is. When the release ships, `2.1.0-dev.14 < 2.1.0` for PHP, so the site updates normally.
- Because the number is derived, there is no chicken and egg: the dev version and the release version come from the same labels, and an override label changes both.

## C. The release pull request

- `release-proposal.yml` (central, reusable) runs on every push to `main` of each repository. It runs `next-version.py`; if nothing is pending it exits. Otherwise it opens or updates **one** pull request from the branch `release/X.Y.Z`, authored by the bot, that changes only the files the repository's policy lists under `release-files:` (Offload: `diluxone-offload.php` and `readme.txt`; a generic repository: `CHANGELOG.md` and its version file). Claude (Sonnet, `low`) writes the changelog entry and a one-paragraph justification that names the pull requests per type and checks the roadmap for a version the maintainer already announced; if the computed bump disagrees with the roadmap, it says so in the pull request instead of choosing.
- The repository's policy decides what happens next, per kind of bump:

  ```yaml
  release:
    patch: propose   # propose | auto | off
    minor: propose
    major: propose
  ```

  `propose` opens the pull request and waits for a human merge; `auto` merges it as soon as its checks pass (the same auto-merge job, gated on this policy, never on the review's risk rating); `off` never opens one. The organisation default is `propose` everywhere; a repository can only move to `auto` for `patch` unless the organisation policy allows more.
- A comment `@dilux-bot version: 3.0.0` on the release pull request re-labels the relevant pull request with `version:major` and re-runs the proposal.

## D. What runs on the release pull request

- The `What changed` job (already in `plugin-tests-wp.yml` and `plugin-checks-wp.yml`) answers `code=false` when the pull request's author is the bot **and** every changed file matches the repository's `release-files:` list. The rule is a list in the policy, so the central knows nothing about WordPress. Integration, end-to-end and the real-storage suites are skipped; the fast checks, the strict version alignment (all three markers equal) and Plugin Check run.
- The review of a bot release pull request is Sonnet at `low` effort, or skipped when the repository's policy says `review-release: false` (default: run; the review reads only two files).
- The full pipeline ran on `main` when the last real change merged (push-to-main runs everything). The release pull request adds no code, so nothing needs to run again. The version alignment check is the one thing that must run, and does.

## E. The tag and the publication

- On push to `main`, the central checks whether the pushed commit is the squash merge of a pull request from a `release/*` branch authored by the bot (GitHub's commit → associated pull requests API). If it is, it creates the tag `X.Y.Z` on that commit with the App's token. The existing release workflow (`plugin-release-wp.yml`) fires on the tag as today: strict validation of the markers against the tag, build from the tagged commit, deploy, GitHub release with notes grouped by `type:*` label.
- Rulesets: creating tags matching `X.Y.Z` is allowed to administrators and to a dedicated release App (`dilux-release`, `contents: write` and nothing else, its key an environment secret) only, never to `dilux-bot`; moving or deleting them to nobody; `main` takes no pushes from anyone; pull requests must be up to date with `main` before merging; every check is required.
- The release workflow refuses a tag whose commit is not the merge of a bot `release/*` pull request, and a tag whose version does not equal the pull request's branch. So the only path to a published version is: real change → full pipeline on its pull request → merge → full pipeline on `main` → bot release pull request → human (or policy) merge → tag by the App → publish. No step can be skipped by a person, a label or a comment.

## F. Costs

- Type classification: no extra call; it is a field of the review that already runs.
- Release proposal: one Sonnet call per push to `main` with something pending (cents), and none when nothing is pending or the open release pull request is already current.
- Release pull request checks: seconds (fast gates + version alignment + Plugin Check, about two minutes).
- Tag and publication: unchanged.
- Reviews in general: unchanged in mechanism (model by risk, incremental after the first); a cap of three automatic reviews per pull request, after which the `review:full` label re-arms it.

## G. What changes where

| where | change |
|---|---|
| `claude-review.yml`, review profiles | `type` in the record; label and retitle |
| `conventions.yml` | unchanged (format still enforced); the labels script |
| `scripts/next-version.py`, `scripts/labels.sh` | new |
| `release-proposal.yml` | new reusable workflow; caller in each repository's `main` push workflow |
| `plugin-tests-wp.yml`, `plugin-checks-wp.yml`, `scripts/changes.sh` | the release-files rule |
| `plugin-release-wp.yml` | provenance check of the tag; notes grouped by label |
| `policy/review-policy.default.yml` | `release:`, `release-files:`, `review-release:` |
| README, workflow templates | adoption steps; the tag ruleset |
| Offload | `release-files:` in its policy; the dev stamp in `make dist` / `deploy-test`; Status › System shows the build; `docs/release.md` rewritten |

## Open questions for the reviewers

1. Security: is there any path by which a version reaches wordpress.org without the full pipeline having run on exactly that tree? Labels, comments, a fork, a human with admin rights, a stale open release pull request.
2. Cost: does anything still run twice for one change? Is the release pull request really cheap, given it changes a `.php` file?
3. Market: what do release-please and semantic-release do that this design lacks, and what do they warn against (monorepos, pre-releases, the bump-back commit, squash merges and commit parsing)?
4. The dev version: does deriving it from labels instead of storing it break anything (readme check, WordPress' update logic, `version_compare`, a site with a stamped build when the real release has a different number than the one stamped)?
