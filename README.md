# DiluxOne/.github

The organisation's shared engineering setup. Every DiluxOne repository calls
the workflows here instead of carrying its own, and inherits the community
files (contributing guide, security policy, support, code of conduct, pull
request template, issue forms) unless it has its own. The rules for contributors are in
[CONTRIBUTING.md](CONTRIBUTING.md); this page is about the machinery.

## What happens on a pull request

0. **An accepted issue first.** Every pull request, a maintainer's too,
   closes an issue a maintainer accepted: the description says
   `Closes #12` (or the issue is linked under *Development*), and the issue
   is open, in the same repository and carries the `accepted` label, added
   by a person. A bot's label never counts, so no automation can accept an
   issue, and only people with triage access or more can label one. The
   issue's **Type** (GitHub's own field: the organisation's Feature, Bug,
   Task and Docs) must fit the pull request's: a `feat` (or any `!`) closes
   a Feature, a `fix` a Bug; the issue forms set it (bug → Bug, feature →
   Feature, docs → Docs, maintenance task → Task) and a maintainer corrects
   it when accepting. Priority and Projects are the maintainer's, set when
   accepting. So an accepted bug report cannot
   carry a feature in. Bots'
   own pull requests (Dependabot, releases) are exempt. This is where a
   feature that is already planned, or that belongs to a paid add-on, is
   stopped: before anyone writes it, by not accepting its issue. The gate
   is a deterministic step of the conventions check
   ([`scripts/issue-gate.sh`](scripts/issue-gate.sh), the policy's
   `issue-gate`, read from the base branch), so it runs on forks too, with
   a read-only token. Accepting the issue later does not re-run the check:
   edit the description, or re-run the job.
1. **Checks.** The conventions (branch name, title, every commit, the
   description's required sections, no "Generated with" footer, relative doc
   links, a `docs` title that changes only documentation, and at most
   `max-changed-lines-untrusted` (600) lines from an author who is not
   trusted, `composer.lock`, `package-lock.json` and translation files aside) and the fast gates of the repository's kind of project, among them
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

Most of it is the organisation's already: a new repository gets the pull request pipeline, the rulesets, the issue forms and the community files without a file of its own (docs/plans/org-first.md). What it adds:

1. **Workflows.** From [`workflow-templates/`](workflow-templates/) (also under *Actions → New workflow*): `issues.yml` (the issue triage and reproduction; fill in `support-url`) and `pull-request-comments.yml` (replies to `@dilux-bot`), which GitHub cannot require from the organisation; and, for a WordPress plugin, `plugin-checks-wp.yml` (fill in `slug` and `version-constant`) and `release-wp.yml`. No `pull-request.yml`: the organisation's ruleset requires [`org-pull-request.yml`](.github/workflows/org-pull-request.yml) on every repository.
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
   retired-names: 'old name|OLD_PREFIX_'   # names that must not come back (the docs check)
   paid-roadmap:            # a free plugin whose paid add-on plans in private: the triage reads it, never quotes it
     repository: DiluxOne/my-plugin-pro-wordpress
     path: docs/roadmap.md
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
3. **Labels, settings and shared files.** `python3 scripts/sync-repos.py all --repo <name>` from a checkout of this repository: the labels, the merge and security settings, `.github/CODEOWNERS` and the opening block of `AGENTS.md` (a pull request with its issue). The `main` and tag rulesets are the organisation's; a plugin that publishes adds its environment `wordpress-org` (deployment policy: tag `*.*.*` plus `main`, required reviewers, the SVN credentials and the release App's key as environment secrets) and installs the `dilux-release` App.

   Then the readme: the newest entry under `== Changelog ==` is headed
   `= X.Y.Z =` (or `= Unreleased =`) and its first line is `Unreleased.`
   while the version is not ready. Every pull request that changes what a
   user sees adds its bullet under that line; the pull request that removes
   the line is the release decision, sets the three version markers to the
   version being released (`scripts/release-markers.sh prepare`), and the
   next push to `main` waits for the environment's reviewers. Between
   releases the markers say the last version released.

## What every repository shares, and how it stays in step

The organisation holds what GitHub lets it hold: the issue Types (Feature, Bug, Task, Docs) and fields (Priority), the Projects, the rulesets, the secrets and Apps, and the community files of this repository (issue forms, pull request template, `CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`, code of conduct), which GitHub uses for every repository that has none of its own. What it does not hold lives here and [`scripts/sync-repos.py`](scripts/sync-repos.py) brings it to every repository:

- [`labels.yml`](labels.yml): every label the workflows and people use (`accepted` among them).
- [`repos.yml`](repos.yml): the merge and security settings, and the files GitHub reads only from the repository (`.github/CODEOWNERS`).
- [`agents-block.md`](agents-block.md): the opening of every `AGENTS.md`, the organisation's rules for any agent, between `dx:org` markers.

```bash
python3 scripts/sync-repos.py all --dry-run          # what would change, everywhere
python3 scripts/sync-repos.py labels                  # labels, through the API
python3 scripts/sync-repos.py settings --repo NAME    # one repository's settings
python3 scripts/sync-repos.py files                   # CODEOWNERS and the AGENTS.md block, as a pull request per repository
```

Labels and settings change through the API. Files never go straight to `main`: for each repository that differs, the script opens an issue (Type Task) and a pull request that closes it, and the maintainer accepts the issue and merges. A maintainer runs it, signed in to `gh` as an owner of the organisation.

## Migrating a repository from `v4` to `v5`

`v5` moves the pull request pipeline to the organisation and reads an issue's native Type.

1. Open the issue for it (the maintenance-task form) and have it accepted; set the native Type of every open issue a pull request closes (a `type:*` label no longer counts).
2. Delete `.github/workflows/pull-request-edited.yml`, and `pull-request.yml` unless it has jobs of its own: for a plugin, keep only `checks`, `tests` and `weekly-failure` (the `plugin-checks-wp.yml` template). Move `retired-names` from the callers to `.github/review-policy.yml`.
3. Delete what the organisation provides: the issue forms, the pull request template, `SECURITY.md`, `CONTRIBUTING.md` unless it has something of its own. Keep `.github/CODEOWNERS`, `dependabot.yml` and the review policy.
4. Point the remaining `uses:` and `central-ref:` at `@v5`.
5. Run `scripts/sync-repos.py all --repo <name>`; once the organisation's rulesets are active, delete the repository's own.

## Migrating a repository from `v3` to `v4`

`v4` brings the accepted-issue gate: from the moment a repository points at
`v4`, every pull request that is not a bot's must close an accepted issue.

1. Create the `accepted` label (`scripts/sync-repos.py labels` does), and
   give each of a repository's own issue forms a `type:` key with its issue
   Type (Bug, Feature, Docs, Task), as the organisation's forms do.
2. Grant `issues: read` to the `conventions` job in `pull-request.yml` (or
   `pull-request-wp.yml`) and `pull-request-edited.yml`; without it the
   workflow fails to start.
3. Point every `uses:` and `central-ref:` at `@v4` (the release workflow at
   its commit).
4. Before the first pull request on `v4`, open its issue and accept it. A
   pull request already open needs one too: write `Closes #<number>` in its
   description.
5. Reproductions change trigger: the triage's `bug:unconfirmed` no longer
   starts one; someone with write access adds `repro:run` (created on the
   first report; create it by hand to use it before) or `repro:again`.

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

## Migrating a repository from `v2` to `v3`

`v3` brings the kinds and their packs. A repository moves when it is ready; `v2` stays where it is for the ones that are not.

1. Declare the kind in `.github/review-policy.yml`: `kind: wordpress-plugin`.
2. Add `.github/review-suppressions.yml` (`review-rules.php --suggest-suppressions` writes the list; every reason is written by a person) and fix what the rules find.
3. Point every `uses:` at `@v3` (the release workflow at its commit), and set the new tests inputs if the repository has more than one suite.
4. Once green, require `checks / Review rules (<kind>)` and the per-target `tests / …` checks in the `main` ruleset.

### What `v3` changes for a plugin

Each of these is red until the plugin complies:

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
the code to `.github/review-policy.yml` in a pull request of its own first.
That pull request is red on the same strict check, for the same reason, so
an administrator merges it past the required check, deliberately; the pull
request that needed the code then passes.

## Reusable workflows

Call them pinned to `@v5`; a breaking change ships as the next major (`v6`), and the previous one stays where it is. A stack suffix
(`-wp`) appears only when the steps are specific to that stack. A workflow
with a `central-ref` input reads the scripts, profiles and policy at that
ref (default `v5`), not at the ref of its `uses:` line: a caller that pins
`uses:` to a version passes the same version as `central-ref`.

| Workflow | Does | Inputs |
| --- | --- | --- |
| [`org-pull-request.yml`](.github/workflows/org-pull-request.yml) | Not reusable: the pull request pipeline of every repository but this one, required by the organisation's `main` ruleset. Calls `conventions.yml`, `claude-review.yml` and `auto-merge.yml` at `@v5` with today's job names, on every pull request event, `edited` included. | none; the repository's `.github/review-policy.yml` |
| [`conventions.yml`](.github/workflows/conventions.yml) | Branch, title, commits, description sections, no "Generated with" footer, a `docs` title that changes only docs, the size limit for authors who are not trusted (all in `scripts/conventions.sh`), the accepted issue the pull request closes (`scripts/issue-gate.sh`), relative doc links, retired names. Callers grant `issues: read`. Reads the labels and the review App's last record live, so a re-run sees today's `type:*` label. | `retired-names`, `required-sections`, `max-header`, `central-ref`, `review-bot` |
| [`claude-review.yml`](.github/workflows/claude-review.yml) | The review described above. `profile` (default `general`) names a kind or a pack's alias (`plugin-wp`); with `general`, the kind the repository's policy declares adds its profile. Outputs `risk`, `complexity`, `floor`, `trusted`, `blocking`. | `profile`, `central-ref`, `max-auto-reviews` |
| [`review-reply.yml`](.github/workflows/review-reply.yml) | Answers `@dilux-bot` mentions from members and collaborators, with the high-risk reviewer, on the same profiles as the review. | `profile`, `central-ref` |
| [`auto-merge.yml`](.github/workflows/auto-merge.yml) | Turns GitHub's auto-merge on or off from the review's outputs and commits the description verbatim. `pull-request-edited.yml` runs it on `edited` too. | the five review outputs |
| [`scripts/conventions.sh`](scripts/conventions.sh) | Not a workflow: the conventions a pull request is held to (branch, title, every commit header, no session trailer, description sections, no "Generated with" footer, a `docs` title that changes only docs, the size limit). `conventions.yml` runs it on a pull request, `local-review.sh` before one; `--test` for its own tests. | env: `BRANCH`, `TITLE`, `BODY`, `BASE`, `HEAD_REF`, `COMMENTS_FILE`, `REVIEW_BOT`, `MAX_HEADER`, `SECTIONS`, `LABELS`, `AUTHOR_TYPE`, `MAX_LINES` |
| [`scripts/issue-gate.sh`](scripts/issue-gate.sh) | Not a workflow: the accepted-issue gate. Asks GitHub which issues the pull request closes and passes when one is open, in the same repository and carries the policy's label, added last by a person. `--test` for its own tests. | env: `REQUIRED`, `LABEL`, `AUTHOR_TYPE`, `GITHUB_REPOSITORY`, `PR`, `GH_TOKEN` |
| [`scripts/dx.sh`](scripts/dx.sh) | Not a workflow: the flow of [`docs/agents.md`](docs/agents.md), one command per step, from a clone or a fork: `dx issue`, `dx start <n>` (checks the issue is accepted, makes the branch and the description), `dx check` (the local review), `dx pr`. `--test` for its own tests. | `issue`, `start`, `check`, `pr` |
| [`scripts/sync-repos.py`](scripts/sync-repos.py) | Not a workflow: brings `labels.yml`, `repos.yml` and `agents-block.md` to every repository (labels and settings through the API, files as a pull request per repository). `--test` for its own tests. | `labels`, `settings`, `files`, `all`; `--repo`, `--dry-run` |
| [`scripts/triage-brief.sh`](scripts/triage-brief.sh) | Not a workflow: the issue triage's public brief (the issue, the open issues, the roadmap, README and readme.txt, the versions, where questions go), never the paid roadmap. Both triage jobs build their brief with it. `--test` for its own tests. | env: `NUMBER`, `TITLE`, `BODY`, `AUTHOR`, `ROADMAP`, `SUPPORT_URL`, `DEV_TAG`, `GH_TOKEN`; `<out-file>` |
| [`scripts/triage-act.sh`](scripts/triage-act.sh) | Not a workflow: what the triage does with a verdict: its labels, the reply with the AI line and a record, the lock of a security report. `--test` for its own tests, with a stand-in for gh. | env: `VERDICT`, `REPLY`, `SUMMARY`, `NUMBER`, `MAINTAINER`, `MODEL`, `COST`, `GH_TOKEN` |
| [`scripts/triage-reply.sh`](scripts/triage-reply.sh) | Not a workflow: the triage's fixed replies when it read a paid add-on's private roadmap (a paid, planned, new or by-design request), in English, Spanish or Portuguese, and the plain fallback when the reply written without the roadmap fails. `--test` for its own tests. | `<category> <language>` |
| [`scripts/review-brief.sh`](scripts/review-brief.sh) | Not a workflow: the review brief, the one file the Claude review reads (profiles, `AGENTS.md`, `docs/architecture.md`, policy floor, description, diff). `claude-review.yml` and `local-review.sh` build it with the same script; `--test` for its own tests. | env: see the script's header |
| [`scripts/local-review.sh`](scripts/local-review.sh) | Not a workflow: the pull request's checks before it exists, on a contributor's machine: conventions, policy floor, brief, and the review through the local Claude Code CLI; the findings go to `.git/dx-review/findings.md` and the next run is incremental. See CONTRIBUTING.md, "Review before the pull request"; `--test` for its own tests (never runs the review). | `--base`, `--title`, `--body-file`, `--profile`, `--no-claude`, `--full`, `--model` |
| [`scripts/release-ready.sh`](scripts/release-ready.sh) | Not a workflow: whether a readme's newest changelog entry is ready (exit 0) or held by a first line `Unreleased.` (exit 1); `--test` for its own tests. The release job's hold. | the readme |
| [`scripts/release-markers.sh`](scripts/release-markers.sh) | Not a workflow: `check` holds the three version markers to a real version (the last one released, or the next one in the pull request that releases it and on `main` after it merged; the checks' readme job and the release job run it); `prepare` turns a tree into its release pull request (removes the `Unreleased.` line, stamps the markers); `--test` for its own tests. | `check <dir> <main-file> <constant> <last> <next> <pending>`, `prepare <dir> <version> <main-file> [<constant>]` |
| [`scripts/review-rules.php`](scripts/review-rules.php) | Not a workflow: the review rules engine. Runs a kind's `kinds/<kind>/rules.yml` (what that kind's reviewers sent back, as data) with generic rule types (comment, call argument, hook callback, forbidden call, forbidden config, suppression allow-list) and language adapters (PHP, on its tokenizer); code rules read the shipped tree, config rules the repository. An error fails, a warning annotates. The checks' `Review rules (<kind>)` job runs it; `--suggest-suppressions` prints the entries `.github/review-suppressions.yml` is missing; `--test` runs its own tests and every rule's fixtures. See [`kinds/README.md`](kinds/README.md). | `--kind`, `--rules`, `--repo`, `--tree`, `--format`, `--only`, `--suggest-suppressions`, `--test` |
| [`scripts/kind.sh`](scripts/kind.sh) | Not a workflow: the kind a check runs for and its settings (the pack's, plus the repository's `kind-settings`), through `policy.py`'s `POLICY_MODE=kind`. On a pull request (any event but `push`, `schedule` and `workflow_dispatch`) the policy is the base branch's, so a change cannot exempt itself; on those three it is the checked commit's own, already merged. `--test` for its own tests. | env: `KIND_DEFAULT`, `DEFAULT_POLICY`, `EVENT` |
| [`scripts/test-targets.py`](scripts/test-targets.py) | Not a workflow: turns `plugin-tests-wp.yml`'s inputs into one job per integration target and E2E suite, each with a stable check name, and refuses an input that is not one; `--test` for its own tests. | env: the workflow's inputs |
| [`scripts/stamp-version.sh`](scripts/stamp-version.sh) | Not a workflow: stamps a plugin tree with a version (the `Version:` header, the constant, `Stable tag:`, a `= Unreleased =` heading; with a build, a `Build:` header line) and fails when a marker did not take it. The release and the development build stamp with it; `--test` for its own tests. | `<dir> <version> <main-file> [<constant>] [<build>]` |
| [`scripts/next-version.py`](scripts/next-version.py) | Not a workflow: the next version of a repository from the `type:*` labels of the pull requests merged since the last `X.Y.Z` tag (a `version:major|minor|patch` label a person sets wins): breaking → major, feat → minor, fix or perf → patch, anything else nothing to release. Also the development version, `<next>-dev.<N>`, N the commits since the tag. `--json` for machines, `--test` for its own tests. | `--repo`, `--base`, `--tag-prefix` |
| [`plugin-checks-wp.yml`](.github/workflows/plugin-checks-wp.yml) | The fast gates of the `wordpress-plugin` kind: syntax and unit tests on every PHP from the minimum to the latest, PHPCS, PHPStan, Psalm taint, i18n, Plugin Check on the shipped tree (strict: a warning fails; categories and ignored codes from the pack, plus the repository's `kind-settings`), `Review rules (wordpress-plugin)` (the kind's `rules.yml`, `scripts/review-rules.php`), readme and versions (the markers against what was released: `scripts/release-markers.sh`). Opt-in: `translations-complete: true` adds `Translations complete (languages/*.po)` (every shipped `.po` parses, has nothing fuzzy and, merged with the strings of today's code, misses none); `codeql-languages: javascript-typescript` adds `CodeQL` (security-extended queries; a result fails the check; nothing is uploaded to code scanning, which would need `security-events: write` from every caller). Needs the composer scripts `test:unit`, `lint`, `stan`, `psalm:taint`, a `.distignore` and a `readme.txt`. | `slug`, `main-file`, `version-constant`, `php-versions`, `kind`, `translations-complete`, `codeql-languages`, `central-ref` |
| [`plugin-tests-wp.yml`](.github/workflows/plugin-tests-wp.yml) | Slow suites on wp-env, one job and one check per target. Integration: `integration-targets: '["single","network"]'` runs PHPUnit on a single site (`Integration (single site)`) and on the tests site turned into a network (`Integration (network)`); left out, the old single job `Integration tests (wp-env)`, on the network unless `multisite: false`. E2E: `e2e-suites` is a JSON list of `{name, site, run, results?, timeout?}`, each its own job `E2E (<name>)`: `site` `single` is the development site with the plugin activated, `network` the tests site turned into a subdirectory network (WordPress's rewrite rules, the plugin network-activated); `run` is the repository's command (`npx playwright test -c playwright.network.config.ts`, an npm script); `results` the folder kept when it fails. Left out, the old single job `E2E (Playwright)`, `npx playwright test` on the development site. A suite turned off, or a pull request without code, keeps its jobs, green, with nothing run (a job skipped before its matrix expands would report a name no ruleset can require). Needs `.wp-env.json`, `phpunit-integration.xml` and Playwright configs. | `integration`, `multisite`, `integration-targets`, `e2e`, `e2e-suites`, `central-ref` |
| [`weekly-failure.yml`](.github/workflows/weekly-failure.yml) | When the scheduled full run fails: opens one `ci:weekly` issue with the run, or adds the run to the one already open. | none |
| [`issue-triage.yml`](.github/workflows/issue-triage.yml) | When an issue opens: classifies it with the roadmap and the docs (bug to reproduce, needs info, by design, pro feature, planned, enhancement, question, duplicate, security), applies the label and posts one reply; never closes, never accepts. With `paid-roadmap:` in the repository's policy it also reads the paid add-on's private roadmap, with a token for that repository alone; that run only classifies (labels and numbers), and a second job, on a fresh runner where the roadmap never was, replies: fixed text for a paid, planned, new or by-design request (`scripts/triage-reply.sh`), a reply written from the public brief alone otherwise. At most `max-per-day` (20) issues get an AI triage in 24 hours, counted with GitHub's issue search (every issue, a bot's too); past that, or when the count fails, `needs-triage`. A report with steps made on an older version (an older release, or a development build older than the current pre-release) is still a bug to reproduce: the reproduction runs on the current code and says whether it is still there, instead of asking the reporter to update; the reply names the current version. On a schedule, closes `needs-info` issues nobody answered. Light model. | every repository (`dev-tag`) |
| [`issue-repro.yml`](.github/workflows/issue-repro.yml) | When a person who can write to the repository labels an issue `repro:run` (or `repro:again`; a bot's label, the triage's `bug:unconfirmed` included, starts nothing): Claude writes one unit test that fails if the bug exists (no shell), a second job with no secrets and a read-only token runs it inside a container with no network, no environment and the checkout read-only, a third with the bot token pushes the file the first job produced (hash-checked) and reports. Fails: `bug:confirmed` plus a draft PR with the test. Passes: `could-not-reproduce` and a question to the reporter; when the report named an older version, the reply says the current code (the development build, linked) may already have the fix and asks to try it. Both verdicts say what they ran on. At most 5 a day. | repositories with unit tests (`dev-tag`) |
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

Every place the bot's token is minted asks only for what that job does: the review, the replies and the triage get `contents: read` while the model runs; `contents: write` is minted only by the merge, the reproduction push, the weekly learnings, and the step that resolves review threads after the model has finished (resolving a thread is a write on the repository), which nothing that read the pull request's text ever holds. Tags are not creatable by `dilux-bot` at all: the ruleset an adopting repository sets at step 3 allows `X.Y.Z` tag creation to administrators and the release App only, and this repository's `v*` tags (the moving `v5`, the frozen `v4`, `v3`, `v2` and `v1`) can be created, moved or deleted only by administrators (ruleset `moving tags`: creation, update, deletion). The wordpress.org credentials live in the repository environment `wordpress-org`, whose deployment policy admits only `X.Y.Z` tags and `main`, so no pull request or branch job can read them; the check `svn-auth-check.yml` runs inside that environment.

Everything here is high risk: a human merges every change. After merging, move
`v5` (or cut `v6` for a breaking change: `scripts/next-version.py --tag-prefix v`
says which) and tag the exact version. Moving `v5` also ships the review
profiles, the packs, the default policy and the organisation's required
workflow, which every repository on `v5` reads from that tag. A run that
already exists keeps the workflow it was created with: re-running a failed
job after `v5` moved re-runs the old workflow. Reopen the pull request, or
push to it, for a run on the new one. `v4`, `v3`, `v2` and `v1` stay where
they are.
