# Release automation: the type of a change, the next version, the tag

Status: decided 2026-09-26, reviewed for security, cost and against the tools the market uses. The release is approved as a **deployment** (the job on `main` builds, waits for approval in the `wordpress-org` environment, then tags and publishes), not as a release pull request. Shipped so far: the security fixes (DiluxOne/.github#3), the type of a change by the review (#4), nothing runs twice, `next-version.py`. Pending: the stamped development builds and the release job itself.

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

This design is release-please with two changes: the type comes from the AI's reading of the diff (labels), not from the human's commit message; and there is no release pull request at all: the release is a deployment approved in a GitHub environment, so nothing is committed to `main` for a release and nothing runs twice.

## A. The type of a change

- The review (`claude-review.yml`) already reads the whole diff. It returns one more field in its record: `type`, one of `breaking`, `feat`, `fix`, `perf`, `refactor`, `docs`, `test`, `ci`, `build`, `chore`.
- The bot sets the label `type:<type>` on the pull request and, when the title's prefix disagrees, retitles the pull request to match (the bot has `pull-requests: write`). The conventions check keeps validating the format; the type itself is now the review's.
- A human can override: setting a different `type:*` label by hand wins over the bot (the bot only replaces a `type:*` label it set itself, read from the label's timeline actor). A `version:major` / `version:minor` / `version:patch` label on any pull request forces that bump for the release that includes it.
- The labels are created in every repository by the central (`scripts/labels.sh`, run at adoption and idempotent).

## B. The next version, and the dev version

- `scripts/next-version.py` (central) is deterministic: from the labels of the pull requests merged into `main` since the last tag, `breaking` → major, `feat` → minor, `fix`/`perf` → patch, everything else → nothing to release; a `version:*` label overrides. It prints the pending bump, the next version and the pull requests grouped by the bump each asks for. The AI does not pick the number; it picks the type. The number is auditable from the labels.
- **Dev builds.** Nothing about the version is stored on `main`: the three markers stay at the last released version, and the release job stamps them in the build it publishes, so there is no bump-back commit after a release. Every build that is not a release (`make dist`, `make deploy-test`, the CI artifact) stamps `Version: <next>-dev.<N>` where `<next>` comes from `next-version.py` and `N` is the number of commits since the last tag, and writes the short commit into the plugin's Status › System screen. The maintainer who installs a build sees `2.1.0-dev.14` and knows a minor release is pending and which build it is. When the release ships, `2.1.0-dev.14 < 2.1.0` for PHP, so the site updates normally.
- Because the number is derived, there is no chicken and egg: the dev version and the release version come from the same labels, and an override label changes both.

## C. The release is a deployment

- `plugin-release-wp.yml` gains a second entry: besides a tag `X.Y.Z`, the caller runs it on every push to `main` (the same workflow that runs the suites, so nothing runs twice). A `release` job runs `next-version.py`: nothing pending, it ends there. Something pending, it builds the tree from that commit with the three version markers stamped to `X.Y.Z`, validates them, and reaches the step that needs the `wordpress-org` environment. The environment has a required reviewer, so the run waits there, visible in the Actions tab and in the run's summary (the version, the bump and the pull requests per type that justify it). Approve, and the job tags the commit `X.Y.Z` with the release App's token, commits to SVN and creates the GitHub release; reject, and nothing happens. Merges keep landing meanwhile: a later push starts a new run that supersedes the waiting one (`concurrency`, cancel in progress), computed from all of `main` again.
- The repository's policy decides, per kind of bump, whether a human must approve:

  ```yaml
  release:
    patch: approve   # approve | auto | off
    minor: approve
    major: approve
  ```

  `approve` waits in the environment; `auto` runs in a second environment the caller names (`auto-environment`), with the same secrets and no reviewers, so that the key that creates the tag is then held by a job nobody approved: a repository turns `auto` on only for the bumps it is willing to publish unattended, and only when the organisation policy allows it; `off` never releases. The organisation default is `approve` everywhere.
- A comment `@dilux-bot version: 3.0.0` on a pull request re-labels it with `version:major` (or minor, or patch) and the next push to `main` computes from that. The roadmap check stays: the job reads `docs/roadmap.md`, and when the roadmap names a version for what is pending that the labels do not reach, the summary says so and a person decides with a label.

## D. What the release job does not do

- It never runs the suites: the commit it releases is the head of `main`, whose tree the pull request's checks ran on (section on `changes.sh` in the README). It runs the version alignment on the stamped tree, Plugin Check on the built tree, and the SVN commit. About two minutes before the approval, one after.
- It never writes to `main`: the version markers on `main` stay at the last released version (the stamp lives in the build, not in the repository), so there is no bump-back commit, no release branch and no release pull request to keep current.
- It never reads a description or a comment as an instruction: the version comes from labels, the labels from the review of the diff or from a person.

## E. The tag and the publication

- The tag `X.Y.Z` is created by the release job itself, on the commit it built, with the token of the dedicated release App (`dilux-release`, `contents: write` and nothing else, its private key a secret of the release environments, so only a job that passed the environment (its reviewers, or the policy's `auto` for that bump) ever holds it). `dilux-bot` cannot create tags. Administrators can, by hand, as today: the tag then runs the same workflow through the same environment, so the by-hand path is the same pipeline with the version typed instead of computed, and the strict marker validation refuses a tag that does not match what `next-version.py` says is pending.
- Rulesets, all in place: creating tags matching `X.Y.Z` is allowed to administrators and to the release App only; moving or deleting them to nobody; `main` takes no pushes from anyone; pull requests must be up to date with `main` before merging; every check is required.
- So the only path to a published version is: real change → full pipeline on its pull request → merge → push to `main` (suites skipped because the tree was tested, alignment and Plugin Check run) → version computed from labels → a person approves the deployment (or the policy does, per bump) → tag by the App → publish. No step can be skipped by a label, a comment, a fork or a description.

## F. Costs

- Type classification: no extra call; it is a field of the review that already runs.
- Release job: no model call at all; about two minutes of runner per push to `main` with something pending, none otherwise.
- Tag and publication: unchanged.
- Reviews in general: unchanged in mechanism (model by risk, incremental after the first); a cap of three automatic reviews per pull request, after which the `review:full` label re-arms it.

## G. What changes where

| where | change |
|---|---|
| `claude-review.yml`, review profiles | `type` in the record; label and retitle |
| `conventions.yml` | unchanged (format still enforced); the labels script |
| `scripts/next-version.py`, `scripts/labels.sh` | new |
| `plugin-release-wp.yml` | the `release` job on push to `main`: compute, build, stamp, wait for the environment, tag with the App, publish |
| `plugin-tests-wp.yml`, `plugin-checks-wp.yml`, `scripts/changes.sh` | a push to `main` skips the suites when the tree was tested (done) |
| `policy/review-policy.default.yml` | `release:` per bump |
| README, workflow templates | adoption steps; the tag ruleset |
| Offload | the dev stamp in `make dist` / `deploy-test`; Status › System shows the build; `release.yml` runs on push to `main` too; `docs/release.md` rewritten |

## Open questions for the reviewers

1. Security: is there any path by which a version reaches wordpress.org without the full pipeline having run on exactly that tree? Labels, comments, a fork, a human with admin rights, a stale open release pull request.
2. Cost: does anything still run twice for one change? Is the release job really cheap?
3. Market: what do release-please and semantic-release do that this design lacks, and what do they warn against (monorepos, pre-releases, the bump-back commit, squash merges and commit parsing)?
4. The dev version: does deriving it from labels instead of storing it break anything (readme check, WordPress' update logic, `version_compare`, a site with a stamped build when the real release has a different number than the one stamped)?
