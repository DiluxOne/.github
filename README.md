# DiluxOne/.github

The organisation's shared engineering setup. Every DiluxOne repository calls
the workflows here instead of carrying its own, and inherits the community
files (contributing guide, security policy, support, code of conduct, pull
request template, issue forms) unless it has its own. The rules for contributors are in
[CONTRIBUTING.md](CONTRIBUTING.md); this page is about the machinery.

## What happens on a pull request

1. **Checks.** The conventions (branch name, title, every commit, the
   description's required sections, no "Generated with" footer, relative doc
   links) and the fast gates of the repository's kind of project, among them
   its review rules: what that kind's reviewers sent back before, as data
   ([`kinds/`](kinds/)). Deterministic, no AI.
2. **Review.** [`scripts/policy.py`](scripts/policy.py) sets the lowest risk
   the change can have from its paths alone
   ([`policy/review-policy.default.yml`](policy/review-policy.default.yml) plus
   the repository's `.github/review-policy.yml`; `policy.py --test` checks
   its rules). Then Claude reviews it with
   the [review profiles](review-profiles/) (general, and the kind's
   `kinds/<kind>/review-profile.md`) and the repository's `AGENTS.md`
   and `docs/architecture.md`: inline comments for blockers and majors (each a
   thread to resolve), `risk:*`, `complexity:*` and `type:*` labels (the type of the change read from the diff, which also corrects the title's type token; a person's own `type:*` label wins), one summary comment
   with what the run cost, red when blocking. It can raise the risk, never
   lower it. It reads the whole change once and only what you pushed since
   its last look after that, spends nothing when the same commit is re-run,
   uses the model and effort the policy names for that floor (read from the
   base branch, so a change cannot pick its own reviewer), skips the
   repository's code rules for text-only changes, and after `max-auto-reviews`
   (5) keeps the last verdict until the `review:full` label asks for more.
   Drafts and forks are not reviewed; pull requests Dependabot or the
   organisation's App open are (`allowed_bots`).
3. **Merge.** A human, with [`scripts/squash-merge.sh`](scripts/squash-merge.sh)
   `<owner/repo> <number>` (description verbatim, co-authors kept), or
   GitHub's auto-merge when the floor is low, the verdict is low risk and low
   complexity, nothing blocks, the author is trusted and the policy says
   `auto-merge: true`.

Mention `@dilux-bot` in a review thread or in the conversation and Claude
answers there; it resolves its own thread when the point is settled.

Nothing runs twice for one change. An edit of the title or the description
re-runs only the conventions, the review (free on a commit it already
read) and the auto-merge decision, never the suites. A push to `main` runs
the slow suites only when it must: the job verifies that the commit is the
squash merge of a pull request of this repository, that its tree is the
one that pull request's checks ran on and that every check there passed;
any doubt runs everything. A pull request whose base branch changed after
its last push fails the conventions on every edit until a push runs the
suites against the new base. The conventions read the labels as they are
when they run, not as the event carried them, so a re-run sees the
`type:*` label the review set since; they compare the title's type with it
once the review has read the commit (the review App's last record names
it) or has reached its cap, so a push that changes the title waits for the
review's new reading instead of failing on the old label. An edit's review
runs in a concurrency group of its own: it cancels nothing and nothing
cancels it, since a cancelled run leaves a cancelled check that blocks the
merge. It spends nothing: on a commit the review read it reuses the
verdict, and on one its push's run is still reviewing it waits for that
verdict and reuses it, or fails when none comes. Once a week everything
runs against today's WordPress and tools, and a failure opens one
`ci:weekly` issue; *Run workflow* runs everything by hand, and its failure
is in the run alone.

## Kinds of project

Nothing here is hard-wired to one stack. What is specific to a kind of
project (its review profile, the rules its reviewers taught us, the settings
of its gates, the workflows of its battery) lives in a pack under
[`kinds/`](kinds/), as data, and a repository declares its kind with
`kind:` in its `.github/review-policy.yml`. Every rejection a review sends
back becomes one entry in the kind's `rules.yml`, with fixtures, never a new
script or workflow. [`kinds/README.md`](kinds/README.md) explains the model,
how to add a rule and how to add a kind; the one kind today is
[`wordpress-plugin`](kinds/wordpress-plugin/).

## Adopt it in a new repository

1. **Workflows.** Copy the callers from [`workflow-templates/`](workflow-templates/)
   (they also appear under *Actions → New workflow* in every repository of the
   organisation): `pull-request.yml` or `pull-request-wp.yml`,
   `pull-request-edited.yml`, `pull-request-comments.yml`, `issues.yml` and,
   for a plugin, `release-wp.yml`. Fill in `slug`, `version-constant`, `retired-names` and
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
   kind: wordpress-plugin   # kinds/<kind>/: adds its review profile, its rules and settings
   high-risk:
     - "src/billing/**"
   low-risk-eligible:
     - "examples/**"
   code:
     - "bin/**"
   review:
     high: { model: claude-sonnet-5-5, effort: xhigh }
   budget-usd: 2
   auto-merge: true
   ```

   `code` and `plugin-check` decide what runs: a pull request that changes
   no file matching `code` skips the slow suites (integration, end-to-end,
   and a repository's own real-storage workflow if it gates on the same
   answer), and skips Plugin Check unless a `plugin-check` file such as
   `readme.txt` or a hidden file changed. The fast checks and the review always run; a push
   to `main` runs the suites only when its tree was not tested already, and
   the weekly run always runs them. The defaults cover a WordPress plugin;
   a repository only adds what is peculiar to it. `kind-settings:` adds to
   the lists of its kind's settings (for a plugin, Plugin Check's
   `ignore-codes`), never replaces a value; the checks read it from the base
   branch ([`kinds/README.md`](kinds/README.md)). A plugin that suppresses a
   nonce, sanitising, SQL or filesystem check lists each suppression, with
   its reason, in `.github/review-suppressions.yml`
   ([`kinds/wordpress-plugin/suppressions.md`](kinds/wordpress-plugin/suppressions.md)).

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
   plugin, every `checks / …` and `tests / …` job: among them
   `checks / Review rules (wordpress-plugin)`, `checks / WordPress Plugin Check`,
   `checks / Translations complete (languages/*.po)` and `checks / CodeQL`
   (skipped, so passing, unless their input is on) and one `tests / …` per
   target and suite, named as the
   [`plugin-tests-wp.yml`](.github/workflows/plugin-tests-wp.yml) row below says. Two rulesets on tags
   `X.Y.Z`: one that lets only administrators create them (bypass actor:
   the Administrator role), so no token the workflows hold can publish; one
   under which nobody can delete or move them. For a plugin, an environment
   `wordpress-org` with a deployment policy of tag `*.*.*` plus branch
   `main`, **required reviewers** (the maintainers who may publish; without
   one the deployment does not wait for anyone), and, as environment secrets
   (never organisation secrets), `SVN_USERNAME`, `SVN_PASSWORD` and the
   release App's `DILUX_RELEASE_PRIVATE_KEY`, with `DILUX_RELEASE_CLIENT_ID`
   as an environment variable. The `dilux-release` App (one for the
   organisation, `contents: write` and nothing else) is installed on the
   repository and added to the bypass list of the tag-creation ruleset, as
   an Integration. Dependabot alerts and updates, private vulnerability
   reporting. The `dilux-bot` App must be installed on the repository. The
   labels are created by the review itself.

   The tag rulesets cover `X.Y.Z` only, so the moving tag `dev` of the
   development build stays free for the workflow's own token.

   Then the readme: the newest entry under `== Changelog ==` is headed
   `= X.Y.Z =` (or `= Unreleased =`) and its first line is `Unreleased.`
   while the version is not ready. Every pull request that changes what a
   user sees adds its bullet under that line; the pull request that removes
   the line is the release decision, sets the three version markers to the
   version being released (`scripts/release-markers.sh prepare`), and the
   next push to `main` waits for the environment's reviewers. Between
   releases the markers say the last version released.

## Migrating a repository from `v1` to `v2`

`v2` asks its callers for more than `v1` did, so a caller left on the old
templates fails to start once it points at `v2`:

1. Replace `pull-request.yml` / `pull-request-wp.yml` with the current
   templates: the `conventions` job grants `pull-requests: read`, the
   `checks` and `tests` jobs grant `pull-requests: read` and `checks: read`,
   `edited` is gone from the trigger, the WordPress one has the weekly
   `schedule`, `workflow_dispatch` and the `weekly-failure` job, and
   `auto-merge` receives `description-ok`.
2. Add `pull-request-edited.yml`.
3. For a plugin, replace `release-wp.yml`: it runs on `main` and `X.Y.Z` tags,
   grants `pull-requests: read`, passes `secrets: inherit` and starts as a
   rehearsal (`dry-run: true`). The environment needs the release App's key
   and client id besides the SVN credentials.
4. Point every `uses:` at `@v2` (the release workflow at its commit).

### What moving `v2` to the packs changes for a plugin

The callers' files stay as they are, but each plugin has to change before
it is green again: the checks get stricter the moment `v2` moves, and each
of these is red until the plugin complies:

- **Plugin Check is strict** (the pack's `strict: true`): a warning fails, as
  it does for the reviewer.
- **`checks / Review rules (wordpress-plugin)`** is a new check: an escaping
  suppression, a menu among WordPress's own, a handler that reads the
  request before its nonce or capability check, a nonce action built from
  input, a PHPCS config that teaches custom functions or silences a
  security check, a whole superglobal handed to a function, and every
  nonce, sanitising, SQL or filesystem suppression not listed with its
  reason in `.github/review-suppressions.yml` (`review-rules.php
  --suggest-suppressions` writes the list to fill in). Add it to the
  ruleset once it is green.
- `translations-complete` and `codeql-languages` are off unless the caller
  turns them on; their checks are skipped.

The repository's policy, `kind-settings:` included, is read from the base
branch on a pull request, so a pull request cannot exempt itself: one that
needs a new Plugin Check ignore code cannot turn its own check green. Add
the code to `.github/review-policy.yml` in a pull request of its own first,
merged by a person; the pull request that needed it then passes.

## Reusable workflows

Call them pinned to `@v2`; a breaking change ships as `v2`. A stack suffix
(`-wp`) appears only when the steps are specific to that stack. A workflow
with a `central-ref` input reads the scripts, profiles and policy at that
ref (default `v2`), not at the ref of its `uses:` line: a caller that pins
`uses:` to a version passes the same version as `central-ref`.

| Workflow | Does | Inputs |
| --- | --- | --- |
| [`conventions.yml`](.github/workflows/conventions.yml) | Branch, title, commits, description sections, no "Generated with" footer (all in `scripts/conventions.sh`), relative doc links, retired names. Reads the labels and the review App's last record live, so a re-run sees today's `type:*` label. | `retired-names`, `required-sections`, `max-header`, `central-ref`, `review-bot` |
| [`claude-review.yml`](.github/workflows/claude-review.yml) | The review described above. `profile` (default `general`) names a kind or a pack's alias (`plugin-wp`); with `general`, the kind the repository's policy declares adds its profile. Outputs `risk`, `complexity`, `floor`, `trusted`, `blocking`. | `profile`, `central-ref`, `max-auto-reviews` |
| [`review-reply.yml`](.github/workflows/review-reply.yml) | Answers `@dilux-bot` mentions from members and collaborators, with the high-risk reviewer, on the same profiles as the review. | `profile`, `central-ref` |
| [`auto-merge.yml`](.github/workflows/auto-merge.yml) | Turns GitHub's auto-merge on or off from the review's outputs and commits the description verbatim. `pull-request-edited.yml` runs it on `edited` too. | the five review outputs |
| [`scripts/conventions.sh`](scripts/conventions.sh) | Not a workflow: the conventions a pull request is held to (branch, title, every commit header, no session trailer, description sections, no "Generated with" footer). `conventions.yml` runs it on a pull request, `local-review.sh` before one; `--test` for its own tests. | env: `BRANCH`, `TITLE`, `BODY`, `BASE`, `HEAD_REF`, `COMMENTS_FILE`, `REVIEW_BOT`, `MAX_HEADER`, `SECTIONS`, `LABELS`, `AUTHOR_TYPE` |
| [`scripts/review-brief.sh`](scripts/review-brief.sh) | Not a workflow: the review brief, the one file the Claude review reads (profiles, `AGENTS.md`, `docs/architecture.md`, policy floor, description, diff). `claude-review.yml` and `local-review.sh` build it with the same script; `--test` for its own tests. | env: see the script's header |
| [`scripts/local-review.sh`](scripts/local-review.sh) | Not a workflow: the pull request's checks before it exists, on a contributor's machine: conventions, policy floor, brief, and the review through the local Claude Code CLI; the findings go to `.git/dx-review/findings.md` and the next run is incremental. See CONTRIBUTING.md, "Review before the pull request"; `--test` for its own tests (never runs the review). | `--base`, `--title`, `--body-file`, `--profile`, `--no-claude`, `--full`, `--model` |
| [`scripts/release-ready.sh`](scripts/release-ready.sh) | Not a workflow: whether a readme's newest changelog entry is ready (exit 0) or held by a first line `Unreleased.` (exit 1); `--test` for its own tests. The release job's hold. | the readme |
| [`scripts/release-markers.sh`](scripts/release-markers.sh) | Not a workflow: `check` holds the three version markers to a real version (the last one released, or the next one in the pull request that releases it and on `main` after it merged; the checks' readme job and the release job run it); `prepare` turns a tree into its release pull request (removes the `Unreleased.` line, stamps the markers); `--test` for its own tests. | `check <dir> <main-file> <constant> <last> <next> <pending>`, `prepare <dir> <version> <main-file> [<constant>]` |
| [`scripts/review-rules.php`](scripts/review-rules.php) | Not a workflow: the review rules engine. Runs a kind's `kinds/<kind>/rules.yml` (what that kind's reviewers sent back, as data) with generic rule types (comment, call argument, hook callback, forbidden call, forbidden config, suppression allow-list) and language adapters (PHP, on its tokenizer); code rules read the shipped tree, config rules the repository. An error fails, a warning annotates. The checks' `Review rules (<kind>)` job runs it; `--suggest-suppressions` prints the entries `.github/review-suppressions.yml` is missing; `--test` runs its own tests and every rule's fixtures. See [`kinds/README.md`](kinds/README.md). | `--kind`, `--rules`, `--repo`, `--tree`, `--format`, `--only`, `--suggest-suppressions`, `--test` |
| [`scripts/kind.sh`](scripts/kind.sh) | Not a workflow: the kind a check runs for and its settings (the pack's, plus the repository's `kind-settings`), from the policy on the base branch, through `policy.py`'s `POLICY_MODE=kind`; `--test` for its own tests. | env: `KIND_DEFAULT`, `DEFAULT_POLICY` |
| [`scripts/test-targets.py`](scripts/test-targets.py) | Not a workflow: turns `plugin-tests-wp.yml`'s inputs into one job per integration target and E2E suite, each with a stable check name, and refuses an input that is not one; `--test` for its own tests. | env: the workflow's inputs |
| [`scripts/stamp-version.sh`](scripts/stamp-version.sh) | Not a workflow: stamps a plugin tree with a version (the `Version:` header, the constant, `Stable tag:`, a `= Unreleased =` heading; with a build, a `Build:` header line) and fails when a marker did not take it. The release and the development build stamp with it; `--test` for its own tests. | `<dir> <version> <main-file> [<constant>] [<build>]` |
| [`scripts/next-version.py`](scripts/next-version.py) | Not a workflow: the next version of a repository from the `type:*` labels of the pull requests merged since the last `X.Y.Z` tag (a `version:major|minor|patch` label a person sets wins): breaking → major, feat → minor, fix or perf → patch, anything else nothing to release. Also the development version, `<next>-dev.<N>`, N the commits since the tag. `--json` for machines, `--test` for its own tests. | `--repo`, `--base`, `--tag-prefix` |
| [`plugin-checks-wp.yml`](.github/workflows/plugin-checks-wp.yml) | The fast gates of the `wordpress-plugin` kind: syntax and unit tests on every PHP from the minimum to the latest, PHPCS, PHPStan, Psalm taint, i18n, Plugin Check on the shipped tree (strict: a warning fails; categories and ignored codes from the pack, plus the repository's `kind-settings`), `Review rules (wordpress-plugin)` (the kind's `rules.yml`, `scripts/review-rules.php`), readme and versions (the markers against what was released: `scripts/release-markers.sh`). Opt-in: `translations-complete: true` adds `Translations complete (languages/*.po)` (every shipped `.po` parses, has nothing fuzzy and, merged with the strings of today's code, misses none); `codeql-languages: javascript-typescript` adds `CodeQL` (security-extended queries; a result fails the check; nothing is uploaded to code scanning, which would need `security-events: write` from every caller). Needs the composer scripts `test:unit`, `lint`, `stan`, `psalm:taint`, a `.distignore` and a `readme.txt`. | `slug`, `main-file`, `version-constant`, `php-versions`, `kind`, `translations-complete`, `codeql-languages`, `central-ref` |
| [`plugin-tests-wp.yml`](.github/workflows/plugin-tests-wp.yml) | Slow suites on wp-env, one job and one check per target. Integration: `integration-targets: '["single","network"]'` runs PHPUnit on a single site (`Integration (single site)`) and on the tests site turned into a network (`Integration (network)`); left out, the old single job `Integration tests (wp-env)`, on the network unless `multisite: false`. E2E: `e2e-suites` is a JSON list of `{name, site, run, results?, timeout?}`, each its own job `E2E (<name>)`: `site` `single` is the development site with the plugin activated, `network` the tests site turned into a subdirectory network (WordPress's rewrite rules, the plugin network-activated); `run` is the repository's command (`npx playwright test -c playwright.network.config.ts`, an npm script); `results` the folder kept when it fails. Left out, the old single job `E2E (Playwright)`, `npx playwright test` on the development site. A suite turned off, or a pull request without code, keeps its jobs, green, with nothing run (a job skipped before its matrix expands would report a name no ruleset can require). Needs `.wp-env.json`, `phpunit-integration.xml` and Playwright configs. | `integration`, `multisite`, `integration-targets`, `e2e`, `e2e-suites`, `central-ref` |
| [`weekly-failure.yml`](.github/workflows/weekly-failure.yml) | When the scheduled full run fails: opens one `ci:weekly` issue with the run, or adds the run to the one already open. | none |
| [`issue-triage.yml`](.github/workflows/issue-triage.yml) | When an issue opens: classifies it with the roadmap and the docs (bug to reproduce, needs info, by design, pro feature, enhancement, question, duplicate, security), applies the label and posts one reply; never closes. A report with steps made on an older version (an older release, or a development build older than the current pre-release) is still a bug to reproduce: the reproduction runs on the current code and says whether it is still there, instead of asking the reporter to update; the reply names the current version. On a schedule, closes `needs-info` issues nobody answered. Light model. | every repository (`dev-tag`) |
| [`issue-repro.yml`](.github/workflows/issue-repro.yml) | When an issue gets `bug:unconfirmed` (or `repro:again`): Claude writes one unit test that fails if the bug exists (no shell), a second job with no secrets and a read-only token runs it, a third with the bot token pushes the file the first job produced (hash-checked) and reports. Fails: `bug:confirmed` plus a draft PR with the test. Passes: `could-not-reproduce` and a question to the reporter; when the report named an older version, the reply says the current code (the development build, linked) may already have the fix and asks to try it. Both verdicts say what they ran on. At most 5 a day. | repositories with unit tests (`dev-tag`) |
| [`plugin-release-wp.yml`](.github/workflows/plugin-release-wp.yml) | The release as a deployment. On a push to `main`: computes the next version from the `type:*` labels of what merged (`scripts/next-version.py`); nothing pending, the policy's `release.<bump>: off`, or a readme whose newest changelog entry still starts with the line `Unreleased.` (the version is not ready), ends there, green, and the summary says why. Otherwise waits for the reviewers of the repository's environment (the summary shows the version, the bump and the pull requests), then checks that the three version markers already say the version (the release pull request set them) and validates the changelog (`= X.Y.Z =`), deploys to wordpress.org SVN, creates the tag with the release App's token and the GitHub release with the changelog and what was merged, grouped by type. On a tag `X.Y.Z` pushed by hand: the same, and the tag must be the version the labels say is next and the readme must be ready. Every push to `main` also publishes a development build, the shipped tree stamped `<next>-dev.<N>` with a `Build: <commit>` header, as the one **Development build** pre-release on the moving tag `dev-tag` (default `dev`), replaced each time: fixed asset URL `…/releases/download/dev/<slug>.zip`, no history (the commit rebuilds any build), "Latest" stays the last `X.Y.Z`. `dry-run` rehearses everything but the SVN commit, the tag and the release (the notes go to the summary). The caller passes `secrets: inherit` and runs only on `main` and `X.Y.Z` tags. Outputs `version` and `dev`. | `slug`, `main-file`, `version-constant`, `dry-run`, `environment`, `auto-environment`, `central-ref`, `dev-tag` |

Only here: [`review-learnings.yml`](.github/workflows/review-learnings.yml)
(every Monday: finds with one search the pull requests the bot reviewed
anywhere in the organisation, proposes new profile rules from the last 7 days
of lessons and, per repository, changes to its policy or `AGENTS.md` from 90
days of evidence; a path needs `min-evidence` (5) clean merges to be proposed
as safe; every proposal is a pull request a human merges, with what changes,
why, and what starts happening if approved) and
[`svn-auth-check.yml`](.github/workflows/svn-auth-check.yml) (reusable; a plugin
repository calls it by hand from the `svn-auth-check-wp.yml` template to prove the
SVN credentials of its `wordpress-org` environment without committing). This repository's own
callers are [`pull-request.yml`](.github/workflows/pull-request.yml) and
[`pull-request-comments.yml`](.github/workflows/pull-request-comments.yml).

## Organisation secrets and variables

| Kind | Name | Notes |
| --- | --- | --- |
| Secret | `ANTHROPIC_API_KEY` | Review, replies and learnings. Also a Dependabot secret, so Dependabot's pull requests are reviewed. |
| Secret | `DILUX_BOT_PRIVATE_KEY` | The `dilux-bot` GitHub App's key. Also a Dependabot secret. |
| Secret (environment, not organisation) | `SVN_USERNAME`, `SVN_PASSWORD` | wordpress.org SVN, in each plugin repository's `wordpress-org` environment. The release and the credentials check declare that environment on their job; their callers pass `secrets: inherit`, the one way an environment's secrets reach a called job (it hands over every secret, which is why those two workflows run only on `X.Y.Z` tags or by hand from `main`, and call a pinned commit). The environment's policy admits `X.Y.Z` tags and `main`: a pull request's job can never name it; a job running on `main` can only through a workflow that was merged into `main` by a reviewed pull request, which is the trust boundary of everything else here. |
| Variable | `DILUX_BOT_CLIENT_ID` | The App's client ID. |

Models, effort, budget and auto-merge are not variables: they live in the
policy files (see "Adopt it"). To stop everything at once, set
`auto-merge: false` in the default policy, or disable the *Pull request*
workflow of a repository from its Actions tab.

## Changing this repository

Every place the bot's token is minted asks only for what that job does: the review, the replies and the triage get `contents: read` while the model runs; `contents: write` is minted only by the merge, the reproduction push, the weekly learnings, and the step that resolves review threads after the model has finished (resolving a thread is a write on the repository), which nothing that read the pull request's text ever holds. Tags are not creatable by `dilux-bot` at all: the ruleset an adopting repository sets at step 3 allows `X.Y.Z` tag creation to administrators and the release App only, and this repository's `v*` tags (the moving `v2`, the frozen `v1`) can be created, moved or deleted only by administrators (ruleset `moving tags`: creation, update, deletion). The wordpress.org credentials live in the repository environment `wordpress-org`, whose deployment policy admits only `X.Y.Z` tags and `main`, so no pull request or branch job can read them; the check `svn-auth-check.yml` runs inside that environment.

Everything here is high risk: a human merges every change. After merging, move
`v2` (or cut `v3` for a breaking change: `scripts/next-version.py --tag-prefix v`
says which) and tag the exact version. Moving `v2` also ships the review
profiles and the default policy, which every repository reads from that tag.
A run that already exists keeps the workflow it was created with: re-running
a failed job after `v2` moved re-runs the old workflow. Reopen the pull
request, or push to it, for a run on the new one. `v1` stays where it is.
