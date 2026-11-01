# Migrating between versions

What a repository changes to move from one major of the shared workflows to the next, newest first.

A major whose migration is nothing but the callers is named in `repos.yml` (`callers: migrates-from`): `python3 scripts/sync-repos.py callers` then moves each repository on its own, in one issue and pull request of the org-sync lane, every call of the shared workflows at the new major (its own jobs' too) and its callers in step with the templates (#320). Any other major is migrated by hand, as below.

## Within `v7`: `pull-requests: read` for the autopilot (#537)

The autopilot's `work` job runs `make pre-pr`, whose `next-version.py` lists the repository's closed pull requests with the job's own token, so it reads pull requests now. A called workflow gets no more than its caller grants, and GitHub refuses a call that grants less, so a repository that copied `workflow-templates/issues.yml` adds `pull-requests: read` to its `triage` and `claim` jobs before it moves to the release that carries this (`permissions: { contents: read, issues: write, pull-requests: read }` and `{ contents: read, pull-requests: read }`); until then its issue workflow fails to start.

## Migrating a repository from `v6` to `v7`

`v7` keeps two pull requests of a WordPress plugin from conflicting on its changelog and its translations (#452). A change's changelog lines are a file of its own, `changelog.d/<issue>.md`, which the release writes into `readme.txt` (`scripts/changelog-fragments.sh`); on a pull request, `readme.txt`'s changelog no longer changes by hand. With `translations-complete`, `languages/*.pot` and `*.po` are held to the form that merges (no source references, sorted, the header's dates fixed) and no `.mo` is committed: the checks, the suites and the release compile them (`scripts/plugin-i18n.sh`). A repository that is not a WordPress plugin changes nothing but its callers.

1. A plugin with catalogues first takes `python3 scripts/sync-repos.py i18n --repo NAME`: one issue and pull request that write them in that form, remove any committed `.mo` and list `languages/*.mo` in `.gitignore`. It merges at `v6`, which does not check the form.
2. Then `python3 scripts/sync-repos.py callers` moves each repository on its own (`repos.yml`, `callers: migrates-from`): every call at `@v7`, its own jobs' too.
3. A pull request still open that edits `readme.txt`'s changelog moves its lines to `changelog.d/<issue>.md` once its repository is at `v7`.

## Migrating a repository from `v5` to `v6`

`v6` ends a plugin's release at its GitHub release (the tag, the notes and the zip), and sends that release to wordpress.org in a job of its own, `publish` (`plugin-publish-wp.yml`), which runs when the release is published and only for one `dilux-release` made (#287). It asks a repository for nothing but its callers, so `python3 scripts/sync-repos.py callers` moves each one on its own (`repos.yml`, `callers: migrates-from`, #320): every call of the shared workflows at the current major (a repository still at `v5` goes straight to `@v7`), its own jobs' too, and `release.yml` with the `publish` job of `workflow-templates/release-wp.yml`. The private security repository's callers (`nightly-review.yml`, `security-fix.yml`, `security-patch.yml`) pass `DILUX_SECURITY_PRIVATE_KEY`, and `security-fix.yml` also runs on a maintainer's comment (#313).

## Migrating a repository from `v4` to `v5`

`v5` moves the pull request pipeline to the organisation and reads an issue's native Type.

Within `v5`, from the version that brings the autonomy policy (#79): `conventions.yml` asks for `actions: read`, to read the run that opened a lane's issue. The organisation's pipeline (`org-pull-request.yml`) already grants it, so no repository changes anything; one that called `conventions.yml` from a workflow of its own would add `actions: read` to that job.

Within `v5`, from the version that makes a release an issue (#82): a plugin's `release.yml` grants `issues: read` (the `release-wp.yml` template does), so the release workflow can read the issue "Release X.Y.Z" a person accepted. Without it the issue is not read and only the environment's required reviewers can approve, as before; the summary says so. Run `python3 scripts/sync-repos.py labels` so the `lane:release` label the Release form sets exists, and, once the repository releases through its issue, remove the environment's required reviewers (they would be asked too).

Within `v5`, from the version that brings the PHP floor (#85), the plugin checks run every tool on the latest PHP and hold the code to the oldest every plugin supports, PHP 7.4, both from the pack (`kinds/wordpress-plugin/pack.yml`, `settings.php`). Nothing turns red on the day it ships: a plugin whose `Requires PHP` is higher is checked from its own, with a warning (a pull request that raises it above both the base's and 7.4 fails), and the two tools below warn instead of failing. Each plugin then moves in a pull request of its own:

- Remove `php-versions` from the caller (it is ignored, with a warning).
- Lower `Requires PHP` to 7.4 in the main file and `readme.txt`, `require.php` in `composer.json` to `>=7.4`, and `phpVersion` (PHPStan) and `testVersion` (PHPCS) in its own configs, for a person running them locally; the checks pass the pack's minimum over both.
- Let Composer resolve the tools for the PHP they run on: no `config.platform.php`. The unit-test jobs take the pack's `php.analysis-only` packages (Psalm and its WordPress plugin, PHPStan and its extensions) out of `require-dev` and resolve the rest for their own PHP, so those can be the newest: `vimeo/psalm: ^6.14.2` (the first Psalm that runs on PHP 8.5; 5 stops at 8.3), `humanmade/psalm-plugin-wordpress: ^3.1.2`. Everything else in `require-dev` has to install on 7.4 as well as on the latest: PHPUnit `^9.6` (the last that runs on 7.4), and any other package the unit tests do not need goes in the repository's own `kind-settings: php: analysis-only:` list.
- Require `phpcompatibility/phpcompatibility-wp: ^3.0@alpha`, with `phpcompatibility/php-compatibility: ^10.0@alpha` and `phpcompatibility/phpcompatibility-paragonie: ^2.0@alpha` beside it (a pre-release is installed only when the root asks for it). Version 2 brings PHPCompatibility 9, from 2019, which knows no syntax newer than PHP 7.4: it lets union types, `match`, `?->`, named arguments, promoted constructor properties, `readonly` and enums through.
- Fix what PHPCompatibility, PHPStan and the PHP 7.4 syntax and unit-test jobs then find. The pull request is green when the `PHP versions` job and the PHPCS and Psalm jobs warn about nothing.

1. Open the issue for it (the maintenance-task form) and have it accepted; set the native Type of every open issue a pull request closes (a `type:*` label no longer counts).
2. Delete `.github/workflows/pull-request-edited.yml`, and `pull-request.yml` unless it has jobs of its own: for a plugin, keep only `checks`, `tests` and `weekly-failure` (the `plugin-checks-wp.yml` template). Move `retired-names` from the callers to `.github/review-policy.yml`.
3. Delete what the organisation provides: the issue forms, the pull request template, `SECURITY.md`, `CONTRIBUTING.md` unless it has something of its own. Keep `.github/CODEOWNERS` and the review policy; `.github/dependabot.yml` comes from the organisation (`scripts/sync-repos.py dependabot` writes it from the kind's template, docs/adopting.md).
4. Point the remaining `uses:` and `central-ref:` at `@v5`, the release workflow too: nothing is pinned to a commit in any repository (#136).
5. Before opening that pull request, the repository joins the organisation's rulesets (a maintainer, from this repository's session), or its own ruleset would require checks the pull request deletes. After the merge, run `scripts/sync-repos.py all --repo <name>`: besides the labels and settings, it creates a ruleset named **own checks** that only requires the repository's own jobs' checks (`checks / …`, `tests / …`, from its last merged pull requests, which jobs the kind's pack says, plus every check its old rulesets required outside the organisation's pipeline) and deletes the repository's rulesets the organisation's and **own checks** cover; a ruleset with a rule or a check nothing else carries stays, for a person to decide. The organisation's ruleset requires its pipeline, not a plugin's tests. Add any other suite of its own (a plugin's real-storage ones) to **own checks** by hand; the script never rewrites one that exists. The daily drift check reports a repository that needs **own checks** and has none. A repository with no checks of its own keeps no ruleset.

## Migrating a repository from `v3` to `v4`

`v4` brings the accepted-issue gate: from the moment a repository points at
`v4`, every pull request that is not a bot's must close an accepted issue.

1. Create the `accepted` label (`scripts/sync-repos.py labels` does), and
   give each of a repository's own issue forms a `type:` key with its issue
   Type (Bug, Feature, Docs, Task), as the organisation's forms do.
2. Grant `issues: read` to the `conventions` job in `pull-request.yml` (or
   `pull-request-wp.yml`) and `pull-request-edited.yml`; without it the
   workflow fails to start.
3. Point every `uses:` and `central-ref:` at `@v4`.
4. Before the first pull request on `v4`, open its issue and accept it. A
   pull request already open needs one too: write `Closes #<number>` in its
   description.
5. Reproductions start on their own: add the `repro-triaged` job from
   `workflow-templates/issues.yml`, which runs the reproduction when the
   triage classifies a report as a bug. Someone with write access can still
   comment `/repro` on the issue to start one, or to try again.

## Migrating a repository from `v2` to `v3`

`v3` brings the kinds and their packs. A repository moves when it is ready; `v2` stays where it is for the ones that are not.

1. Declare the kind in `.github/review-policy.yml`: `kind: wordpress-plugin`.
2. Add `.github/review-suppressions.yml` (`review-rules.php --suggest-suppressions` writes the list; every reason is written by a person) and fix what the rules find.
3. Point every `uses:` at `@v3`, and set the new tests inputs if the repository has more than one suite.
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
4. Point every `uses:` at `@v2`.
