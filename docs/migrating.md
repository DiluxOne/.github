# Migrating between versions

What a repository changes to move from one major of the shared workflows to the next, newest first.

## Migrating a repository from `v4` to `v5`

`v5` moves the pull request pipeline to the organisation and reads an issue's native Type.

1. Open the issue for it (the maintenance-task form) and have it accepted; set the native Type of every open issue a pull request closes (a `type:*` label no longer counts).
2. Delete `.github/workflows/pull-request-edited.yml`, and `pull-request.yml` unless it has jobs of its own: for a plugin, keep only `checks`, `tests` and `weekly-failure` (the `plugin-checks-wp.yml` template). Move `retired-names` from the callers to `.github/review-policy.yml`.
3. Delete what the organisation provides: the issue forms, the pull request template, `SECURITY.md`, `CONTRIBUTING.md` unless it has something of its own. Keep `.github/CODEOWNERS`, `dependabot.yml` and the review policy.
4. Point the remaining `uses:` and `central-ref:` at `@v5`.
5. Before opening that pull request, the repository joins the organisation's rulesets (a maintainer, from this repository's session), or its own ruleset would require checks the pull request deletes. After the merge, run `scripts/sync-repos.py all --repo <name>` and replace the repository's own rulesets with one named **own checks** that only requires its own jobs' checks (`checks / …`, `tests / …`, a plugin's real-storage suites), by their exact names: the organisation's ruleset requires its pipeline, not a plugin's tests. A repository with no checks of its own keeps no ruleset.

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
