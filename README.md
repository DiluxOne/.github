# DiluxOne/.github

The organisation's shared engineering setup. Every DiluxOne repository calls
the workflows here instead of carrying its own, and inherits the community
files (contributing guide, security policy, support, code of conduct, pull
request template, issue forms) unless it has its own. The rules for contributors are in
[CONTRIBUTING.md](CONTRIBUTING.md); this page is about the machinery.

## What happens on a pull request

1. **Checks.** The conventions (branch name, title, every commit, the
   description's required sections, no "Generated with" footer, relative doc
   links) and the stack's fast gates. Deterministic, no AI.
2. **Review.** [`scripts/policy.py`](scripts/policy.py) sets the lowest risk
   the change can have from its paths alone
   ([`policy/review-policy.default.yml`](policy/review-policy.default.yml) plus
   the repository's `.github/review-policy.yml`). Then Claude reviews it with
   the [review profiles](review-profiles/) and the repository's `AGENTS.md`
   and `docs/architecture.md`: inline comments for blockers and majors (each a
   thread to resolve), `risk:*` and `complexity:*` labels, one summary comment
   with what the run cost, red when blocking. It can raise the risk, never
   lower it. It reads the whole change once and only what you pushed since
   its last look after that, spends nothing when the same commit is re-run,
   uses the model and effort the policy names for that floor (read from the
   base branch, so a change cannot pick its own reviewer), skips the
   repository's code rules for text-only changes, and after `max-auto-reviews`
   (5) keeps the last verdict until the `review:full` label asks for more.
   Drafts and forks are not reviewed.
3. **Merge.** A human, with [`scripts/squash-merge.sh`](scripts/squash-merge.sh)
   `<owner/repo> <number>` (description verbatim, co-authors kept), or
   GitHub's auto-merge when the floor is low, the verdict is low risk and low
   complexity, nothing blocks, the author is trusted and the policy says
   `auto-merge: true`.

Mention `@dilux-bot` in a review thread or in the conversation and Claude
answers there; it resolves its own thread when the point is settled.

## Adopt it in a new repository

1. **Workflows.** Copy the callers from [`workflow-templates/`](workflow-templates/)
   (they also appear under *Actions → New workflow* in every repository of the
   organisation): `pull-request.yml` or `pull-request-wp.yml`,
   `pull-request-comments.yml`, `issues.yml` and, for a plugin,
   `release-wp.yml`. Fill in `slug`, `version-constant`, `retired-names` and
   `support-url`.
2. **Policy and rules.** Add `.github/review-policy.yml`. Every review
   setting lives in this file and in the organisation's
   [`policy/review-policy.default.yml`](policy/review-policy.default.yml),
   nowhere else: the paths that are always high risk, the ones that are safe,
   who is trusted, which model and effort each risk level gets, the budget
   per run, and whether qualifying pull requests merge on their own. The
   lists add to the defaults; the rest replaces them key by key (except
   `auto-merge`, which a repository can only turn off), so write only what
   differs:

   ```yaml
   high-risk:
     - "src/billing/**"
   low-risk-eligible:
     - "examples/**"
   code:
     - "bin/**"
   review:
     medium: { model: claude-sonnet-5, effort: medium }
   budget-usd: 2
   auto-merge: true
   ```

   `code` and `plugin-check` decide what runs: a pull request that changes
   no file matching `code` skips the slow suites (integration, end-to-end,
   and a repository's own real-storage workflow if it gates on the same
   answer), and skips Plugin Check unless a `plugin-check` file such as
   `readme.txt` or a hidden file changed. The fast checks and the review always run; a push
   to `main` always runs everything. The defaults cover a WordPress plugin;
   a repository only adds what is peculiar to it.

   Then an `AGENTS.md` with the rules the review must hold the code to, and
   a `docs/roadmap.md` that says what is free, what is paid, what is planned,
   what will not be done and the known limitations: the issue triage answers
   from it.
3. **Settings.** Squash only, auto-merge allowed, delete the branch on merge,
   squash title from the PR title and body from the PR body. A ruleset on
   `main`: changes only through a pull request, linear history, conversations
   resolved, required checks green and up to date, named
   `conventions / Conventions (branch, title, commits)`,
   `conventions / Docs (links and names)`, `review / Claude review` and, for a
   plugin, every `checks / …` and `tests / …` job. A ruleset on tags: `X.Y.Z`
   and `vX.Y.Z` can be neither deleted nor moved. Dependabot alerts and
   updates, private vulnerability reporting. The `dilux-bot` App must be
   installed on the repository. The labels are created by the review itself.

## Reusable workflows

Call them pinned to `@v1`; a breaking change ships as `v2`. A stack suffix
(`-wp`) appears only when the steps are specific to that stack.

| Workflow | Does | Inputs |
| --- | --- | --- |
| [`conventions.yml`](.github/workflows/conventions.yml) | Branch, title, commits, description sections, no "Generated with" footer, relative doc links, retired names. | `retired-names`, `required-sections`, `max-header` |
| [`claude-review.yml`](.github/workflows/claude-review.yml) | The review described above. Outputs `risk`, `complexity`, `floor`, `trusted`, `blocking`. | `profile`, `central-ref`, `max-auto-reviews` |
| [`review-reply.yml`](.github/workflows/review-reply.yml) | Answers `@dilux-bot` mentions from members and collaborators, with the strong model. | `profile`, `central-ref` |
| [`auto-merge.yml`](.github/workflows/auto-merge.yml) | Turns GitHub's auto-merge on or off from the review's outputs and commits the description verbatim. The caller runs it on `edited` too. | the five review outputs |
| [`plugin-checks-wp.yml`](.github/workflows/plugin-checks-wp.yml) | Fast gates for a WordPress plugin: syntax and unit tests on every PHP from the minimum to the latest, PHPCS, PHPStan, Psalm taint, i18n, Plugin Check on the shipped tree, readme and versions. Needs the composer scripts `test:unit`, `lint`, `stan`, `psalm:taint`, a `.distignore` and a `readme.txt`. | `slug`, `main-file`, `version-constant`, `php-versions` |
| [`plugin-tests-wp.yml`](.github/workflows/plugin-tests-wp.yml) | Slow suites on wp-env: PHPUnit integration (multisite) and Playwright E2E. Needs `.wp-env.json`, `phpunit-integration.xml` and a Playwright config that writes to `build/e2e-results`. | `integration`, `multisite`, `e2e` |
| [`issue-triage.yml`](.github/workflows/issue-triage.yml) | When an issue opens: classifies it with the roadmap and the docs (bug to reproduce, needs info, by design, pro feature, enhancement, question, duplicate, security), applies the label and posts one reply; never closes. On a schedule, closes `needs-info` issues nobody answered. Light model. | every repository |
| [`issue-repro.yml`](.github/workflows/issue-repro.yml) | When an issue gets `bug:unconfirmed` (or `repro:again`): Claude writes one unit test that fails if the bug exists (no shell), a second job with no secrets and a read-only token runs it, a third with the bot token pushes the file the first job produced (hash-checked) and reports. Fails: `bug:confirmed` plus a draft PR with the test. Passes: `could-not-reproduce` and a question to the reporter. At most 5 a day. | repositories with unit tests |
| [`plugin-release-wp.yml`](.github/workflows/plugin-release-wp.yml) | On a tag `X.Y.Z`: validates the version markers, deploys to wordpress.org SVN, creates the GitHub release with the changelog and what was merged since the previous release, grouped by type. `dry-run` rehearses everything but the SVN commit. | `slug`, `main-file`, `version-constant`, `dry-run` |

Only here: [`review-learnings.yml`](.github/workflows/review-learnings.yml)
(every Monday: finds with one search the pull requests the bot reviewed
anywhere in the organisation, proposes new profile rules from the last 7 days
of lessons and, per repository, changes to its policy or `AGENTS.md` from 90
days of evidence; a path needs `min-evidence` (5) clean merges to be proposed
as safe; every proposal is a pull request a human merges, with what changes,
why, and what starts happening if approved) and
[`svn-auth-check.yml`](.github/workflows/svn-auth-check.yml) (by hand, proves
the wordpress.org credentials without committing). This repository's own
callers are [`pull-request.yml`](.github/workflows/pull-request.yml) and
[`pull-request-comments.yml`](.github/workflows/pull-request-comments.yml).

## Organisation secrets and variables

| Kind | Name | Notes |
| --- | --- | --- |
| Secret | `ANTHROPIC_API_KEY` | Review, replies and learnings. Also a Dependabot secret, so Dependabot's pull requests are reviewed. |
| Secret | `DILUX_BOT_PRIVATE_KEY` | The `dilux-bot` GitHub App's key. Also a Dependabot secret. |
| Secret | `SVN_USERNAME`, `SVN_PASSWORD` | wordpress.org SVN. |
| Variable | `DILUX_BOT_CLIENT_ID` | The App's client ID. |

Models, effort, budget and auto-merge are not variables: they live in the
policy files (see "Adopt it"). To stop everything at once, set
`auto-merge: false` in the default policy, or disable the *Pull request*
workflow of a repository from its Actions tab.

## Changing this repository

Everything here is high risk: a human merges every change. After merging, move
`v1` (or cut `v2` for a breaking change) and tag the exact version. Moving `v1`
also ships the review profiles and the default policy, which every repository
reads from that tag. A run that already exists keeps the workflow it was
created with: re-running a failed job after `v1` moved re-runs the old
workflow. Reopen the pull request, or push to it, for a run on the new one.
