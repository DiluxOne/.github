# Adopting the setup

How a repository joins: its kind of project, what it adds of its own, and what the organisation keeps in step for it.

## Kinds of project

Nothing here is hard-wired to one stack. What is specific to a kind of
project (its review profile, the rules its reviewers taught us, the settings
of its gates, the workflows of its battery) lives in a pack under
[`kinds/`](../kinds/), as data, and a repository declares its kind with
`kind:` in its `.github/review-policy.yml`. Every rejection a review sends
back becomes one entry in the kind's `rules.yml`, with fixtures, never a new
script or workflow. [`kinds/README.md`](../kinds/README.md) explains the model,
how to add a rule and how to add a kind; the one kind today is
[`wordpress-plugin`](../kinds/wordpress-plugin/).

## Adopt it in a new repository

Most of it is the organisation's already: a new repository gets the pull request pipeline, the rulesets, the issue forms and the community files without a file of its own (docs/plans/org-first.md). What it adds:

1. **Workflows.** From [`workflow-templates/`](../workflow-templates/) (also under *Actions → New workflow*): `issues.yml` (the issue triage and reproduction; fill in `support-url`) and `pull-request-comments.yml` (replies to `@dilux-bot`), which GitHub cannot require from the organisation; and, for a WordPress plugin, `plugin-checks-wp.yml` (fill in `slug` and `version-constant`) and `release-wp.yml`. No `pull-request.yml`: the organisation's ruleset requires [`org-pull-request.yml`](../.github/workflows/org-pull-request.yml) on every repository.
2. **Policy and rules.** Add `.github/review-policy.yml`. Every review
   setting lives in this file and in the organisation's
   [`policy/review-policy.default.yml`](../policy/review-policy.default.yml),
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
   branch ([`kinds/README.md`](../kinds/README.md)). A plugin that suppresses a
   nonce, sanitising, SQL or filesystem check lists each suppression, with
   its reason, in `.github/review-suppressions.yml`
   ([`kinds/wordpress-plugin/suppressions.md`](../kinds/wordpress-plugin/suppressions.md)).

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

The organisation holds what GitHub lets it hold: the issue Types (Feature, Bug, Task, Docs) and fields (Priority), the Projects, the rulesets, the secrets and Apps, and the community files of this repository (issue forms, pull request template, `CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`, code of conduct), which GitHub uses for every repository that has none of its own. What it does not hold lives here and [`scripts/sync-repos.py`](../scripts/sync-repos.py) brings it to every repository:

- [`labels.yml`](../labels.yml): every label the workflows and people use (`accepted` among them).
- [`repos.yml`](../repos.yml): the merge and security settings, the files GitHub reads only from the repository (`.github/CODEOWNERS`), and which public Project of the organisation each repository's accepted issues land on.
- [`agents-block.md`](../agents-block.md): the opening of every `AGENTS.md`, the organisation's rules for any agent, between `dx:org` markers.

```bash
python3 scripts/sync-repos.py all --dry-run          # what would change, everywhere
python3 scripts/sync-repos.py labels                  # labels, through the API
python3 scripts/sync-repos.py settings --repo NAME    # one repository's settings
python3 scripts/sync-repos.py files                   # CODEOWNERS and the AGENTS.md block, as a pull request per repository
```

Labels and settings change through the API. Files never go straight to `main`: for each repository that differs, the script opens an issue (Type Task) and a pull request that closes it, and the maintainer accepts the issue and merges. A maintainer runs it, signed in to `gh` as an owner of the organisation.
