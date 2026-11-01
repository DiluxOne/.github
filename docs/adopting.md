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
how to add a rule and how to add a kind; the kinds today are
[`wordpress-plugin`](../kinds/wordpress-plugin/) and
[`ai-agent-plugin`](../kinds/ai-agent-plugin/), a plugin for coding agents
(#552).

## Another organisation

An organisation other than DiluxOne does not adopt repository by repository first: it installs the engine's configuration in its own `.github` with `scripts/install.py`, which also prints the link to create its own App with the permissions the engine needs, and the secret and variables that follow ([installing](installing.md)). Then each of its repositories joins as below.

## Adopt it in a new repository

In DiluxOne it starts from an issue (#562): the daily drift check opens "Adopt <repository>" here for every repository of the organisation `repos.yml` does not list, with the entry detection proposes (its kind) as a YAML block (a maintainer opens one by hand with the body `python3 scripts/detect.py adopt-body NAME` prints, title `Adopt NAME`, label `lane:adopt`). Correct the block in the issue if it is wrong (its Project as `project: <n>`, its `design-system`, its callers' values), then add `accepted`: that is the only step. [`org-adopt.yml`](../.github/workflows/org-adopt.yml) opens the pull request that adds that entry to `repos.yml`, the `adopt` lane merges it by policy when it is that entry alone, and then `python3 scripts/sync-repos.py adopt --repo NAME` runs: labels, settings, the organisation's code security configuration, the custom property `dx-adopted` the organisation's rulesets cover, the shared files, the callers (written with the values `repos.yml` gives, never a placeholder), `make pre-pr`, the Dependabot file (their pull requests the org-sync lane's, which merge on their own), the own checks, the merge queue (only once every check its rules require runs on `merge_group`) and its Project. The steps below are what that does, and what is left to a repository's own work.

Most of it is the organisation's already: a new repository gets the pull request pipeline, the rulesets, the issue forms and the community files without a file of its own (docs/plans/org-first.md). What it adds:

1. **Workflows.** From [`workflow-templates/`](../workflow-templates/) (also under *Actions → New workflow*): `issues.yml` (the issue triage and reproduction; fill in `support-url`) and `pull-request-comments.yml` (replies to `@dilux-bot`), which GitHub cannot require from the organisation; for a WordPress plugin, `plugin-checks-wp.yml` (fill in `slug` and `version-constant`; an add-on whose base plugin is not on wordpress.org passes `requires-plugins-from` and the `DILUX_BOT_PRIVATE_KEY` secret to both of its calls, so Plugin Check and the wp-env suites run with the base mounted beside it) and `release-wp.yml`; for a plugin for coding agents, `plugin-checks-ai.yml` (its own suites stay its own workflows, on `merge_group` too). Once the repository is in `repos.yml` with its kind, `python3 scripts/sync-repos.py callers --repo <name>` writes the ones it lacks, whole, as a pull request (#552), each input to fill in with its entry's `callers` value, else `repos.yml` `callers: defaults` (#562): nothing is left to fill in by hand. No `pull-request.yml`: the organisation's ruleset requires [`org-pull-request.yml`](../.github/workflows/org-pull-request.yml) on every repository. Change only what a template says to fill in, and add inputs and jobs of your own beside its jobs: the daily drift check compares every caller with its template, job by job, and `sync-repos.py callers` brings one back in step (see below).
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

   **How its bugs are reproduced** (#377): a bug is fixed only once a
   failing test proves it, so every repository declares a way to write that
   test (`repro.ways`, the keys of
   [`scripts/repro-ways.py`](../scripts/repro-ways.py)). Its kind's pack may
   give it one (a WordPress plugin gets PHPUnit and Playwright); otherwise
   it goes in its `.github/review-policy.yml` `repro:`, or in `repos.yml`
   `repro:` under its name. The installer proposes one from its stack
   ([`policy/repro-stacks.yml`](../policy/repro-stacks.yml): PHPUnit,
   pytest, `dotnet test`, Go, Vitest, Jest, each writing a JUnit report),
   and the daily drift check lists every repository that declares none.
   Until it does, its bugs stay unconfirmed and the autopilot does not start
   on one: the issue says which way to declare.

   **Its one check before a pull request** (#479): a `pre-pr` target in its
   Makefile, whatever its stack, that runs every check its pull request and
   its merge queue run, one after the other, stopping at the first failure,
   and starts and stops what it needs (a plugin's wp-env sites) instead of
   relying on anything started before it. What it must cover is its kind's
   pack (`kinds/<kind>/pack.yml` `pre-pr`); a repository of no kind lists
   what its own covers in its `.github/review-policy.yml` (`pre-pr:`, one
   item per line). `dx check` and the autopilot run it before a pull
   request, [`scripts/pre-pr.py`](../scripts/pre-pr.py) says whether it is
   there, and the daily drift check lists a repository without one (unless
   its `repos.yml` entry's `pre-pr` says it has none by design).
3. **What it is, then labels, settings and shared files.** First add it to `repos.yml` `repos:`, one entry with everything said of it (#562): its kinds, the paths each covers and their roles, its `project`, `design-system`, `repro`, `merge-queue`, `pre-pr`, `dependabot` and `callers` (`scripts/repos-config.py check` holds it; the daily drift check reports a repository missing there); the kind is read from there only. Then `python3 scripts/sync-repos.py all --repo <name>` from a checkout of this repository: the labels, the merge and security settings (Dependabot's security updates among them), `.github/CODEOWNERS`, and the opening block of `AGENTS.md` (a pull request with its issue); then `python3 scripts/sync-repos.py dependabot --repo <name>` for `.github/dependabot.yml` (a pull request of its own). `all` also turns its merge queue on where GitHub gives one (org.yml `merge-queue`, #451): a public repository, once every check its rules require comes from a workflow that runs on `merge_group` (#562; the drift check names a check and its workflow that do not; a required check no run of its five most recent pull requests produces keeps a new queue off but leaves an existing one as it is, since it could not tell). `python3 scripts/sync-repos.py adopt --repo <name>` does all of it at once. The `main` and tag rulesets are the organisation's; a plugin that publishes adds its environment `wordpress-org` (deployment policy: tag `*.*.*` plus `main` and the branches `security/*`, where dilux-bot alone pushes a security patch, #247; the SVN credentials and the release App's key as environment secrets; no required reviewer is needed, since a person accepting the release issue is the approval) and installs the `dilux-release` App.

   The organisation's side: the three organisation rulesets (`org: main`, `org: release tag creation`, `org: release tags`) cover the repositories whose custom property `dx-adopted` is `true`, which `sync-repos.py rulesets` (and `adopt`) writes from `repos.yml` (#562); it moves a ruleset from its list of names to the property only when every repository that list covers today (`~ALL` and patterns included, archived ones not) is listed in `repos.yml` and not excluded, and otherwise names those and changes nothing, and secret scanning and push protection come from the code security configuration `repos.yml` `security: configuration` names for the repository's visibility (one name for every repository, or `public:` and `private:`, the latter covering internal ones, #603), which `sync-repos.py security` attaches and keeps the default for new repositories of that visibility; a private repository with no `private:` entry gets none, and one already attached stays until a maintainer detaches it in the organisation's settings; what GitHub holds only at the enterprise level the maintainer changes once there. Done by an administrator of the organisation (a maintainer, or the session working in this repository): for a private repository, also to the organisation variable `DX_RUNNER_HEAVY` and to the runner group `private-repos-vm`, so its jobs run on the organisation's VM and spend no minutes; and give it a Project in its `repos.yml` entry (`project:`; `sync-repos.py project` links it, and the drift check says when it has none) and, when it has screens, its design system (`design-system:`, [`design-systems/`](../design-systems/)). A repository that versions third-party code with Markdown of its own (a site's `wp-content/plugins/` and `themes/`) lists those paths in a `.lycheeignore` at its root, lychee's own file, so the docs check does not follow their links.

   Then the readme: the newest entry under `== Changelog ==` is headed
   `= X.Y.Z =` (or `= Unreleased =`) and its first line is `Unreleased.`
   while the version is not ready. Every pull request that changes what a
   user sees adds its line in a file of its own, `changelog.d/<issue>.md`
   (one bullet each, [`scripts/changelog-fragments.sh`](../scripts/changelog-fragments.sh),
   #452), never in `readme.txt`, so two pull requests never edit the same
   lines; while a fragment waits the version is held too. Its translations
   merge the same way: `languages/*.pot` and `*.po` carry no source
   references and are sorted by message, and no `.mo` is committed (it is
   built when the plugin is packaged and before its suites start,
   [`scripts/plugin-i18n.sh`](../scripts/plugin-i18n.sh)); `sync-repos.py
   i18n --repo <name>` moves a plugin there in one pull request. The release decision is an
   issue: "Release X.Y.Z", opened with the Release form (label
   `lane:release`, which `sync-repos.py labels` creates) and accepted by a
   person. Accepting it opens the release pull request, which removes the
   line, writes the fragments into the version's entry and removes them,
   and sets the three version markers to that version
   (`scripts/release-markers.sh prepare`); when it merges, the release
   workflow checks the acceptance (`scripts/release-issue.py verify`, with
   the `issues: read` the template grants) and publishes. Between releases
   the markers say the last version released. The environment needs no
   required reviewer, which a private repository below GitHub Enterprise
   cannot have; one that has them is asked there too. Without an accepted
   release issue, only the environment's reviewers can approve
   (`scripts/release-gate.py`, which reads the environment with the
   `actions: read` the template grants), and without them nothing deploys.

## What every repository shares, and how it stays in step

The organisation holds what GitHub lets it hold: the issue Types (Feature, Bug, Task, Docs) and fields (Priority), the Projects, the rulesets, the secrets and Apps, and the community files of this repository (issue forms, pull request template, `CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`, code of conduct), which GitHub uses for every repository that has none of its own. What it does not hold lives here and [`scripts/sync-repos.py`](../scripts/sync-repos.py) brings it to every repository:

- [`labels.yml`](../labels.yml): every label the workflows and people use (`accepted` among them).
- [`repos.yml`](../repos.yml): the merge and security settings, the files GitHub reads only from the repository (`.github/CODEOWNERS`), which public Project of the organisation each repository's accepted issues land on, and which design system its screens follow ([`design-systems/`](../design-systems/)).
- [`agents-block.md`](../agents-block.md): the opening of every `AGENTS.md`, the organisation's rules for any agent, between `dx:org` markers.
- The Dependabot templates: [`kinds/wordpress-plugin/dependabot.yml`](../kinds/wordpress-plugin/dependabot.yml) for a WordPress plugin, [`kinds/ai-agent-plugin/dependabot.yml`](../kinds/ai-agent-plugin/dependabot.yml) for a plugin for coding agents (its actions only), [`policy/dependabot.default.yml`](../policy/dependabot.default.yml) for a repository without a kind (or of a kind without one). Every dependency stays on its latest version: each ecosystem is checked daily, with no cooldown, majors included, and its updates come grouped in one pull request (`ci(deps)` for the actions, `build(deps)` or `build(deps-dev)` for the packages and images). A repository's `.github/dependabot.yml` is its kind's template with only the ecosystems it has: github-actions always, npm with a `package.json` at its root, composer with a `composer.json`, docker with a `Dockerfile`. What it adds (other directories, an `ignore`) goes in its `repos.yml` entry (`dependabot`), never in its own file: the drift check reports any difference, and `dependabot` brings it back.

```bash
python3 scripts/sync-repos.py all --dry-run          # what would change, everywhere
python3 scripts/sync-repos.py labels                  # labels, through the API
python3 scripts/sync-repos.py settings --repo NAME    # one repository's settings
python3 scripts/sync-repos.py files                   # CODEOWNERS and the AGENTS.md block, as a pull request per repository
python3 scripts/sync-repos.py dependabot              # dependabot.yml from the kind's template, as a pull request per repository
python3 scripts/sync-repos.py callers --repo NAME     # the workflow callers, as the templates have them, as a pull request
python3 scripts/sync-repos.py adopt --repo NAME       # everything a repository repos.yml lists needs, at once (#562)
python3 scripts/sync-repos.py rulesets                # the dx-adopted property the organisation's rulesets cover
```

Labels and settings change through the API. Files never go straight to `main`: for each repository that differs, the script opens an issue (Type Task, whose body is a PRD that passes G1, so the maintainer can accept it as written, #432) and a pull request that closes it. Run from a checkout that is `main` as it is now, with nothing it reads changed locally, a `files` run's issue carries the run's marker and `lane:org-sync`, and the autonomy policy accepts it ([`policy/autonomy.yml`](../policy/autonomy.yml), #155) and merges its pull request when every file is what that commit holds (and still what `main` holds) and no job's permissions or secrets change, a new job in an existing caller included; otherwise the maintainer accepts the issue and merges. The lane has four runs, each its own issue and pull request (#187, #562): `files` (CODEOWNERS, the AGENTS.md block), `callers`, `pre-pr` (`dx.mk`, its kind's `pre-pr-make`, and `include dx.mk` in the Makefile) and `dependabot` (`.github/dependabot.yml`, its kind's template for the ecosystems the repository has, with what its entry adds); the policy accepts the issues of each and merges their pull requests on the same conditions, so `sync-repos.py adopt` needs no person for them. A new caller merges by policy too, when it is its template whole with the repository's default branch and the values `repos.yml` gives (its grants are the template's, which a person merged here); a release caller is written with `dry-run: true`, the template's, so nothing merged by policy makes a repository publish: its entry sets `callers: {dry-run: false}` when a person decides it goes live. A maintainer runs it, signed in to `gh` as an owner of the organisation; `labels` and `files` also run every day on their own, as dilux-bot, from [`org-drift.yml`](../.github/workflows/org-drift.yml). The callers below go the same way.

The workflow callers are kept in step the same way. A repository that calls the shared workflows has a caller of every template in `every-repository` ([`repos.yml`](../repos.yml), `callers`: `issues.yml` and `pull-request-comments.yml`) and of any other template whose shared workflows it calls (`plugin-checks-wp.yml` for one that calls `plugin-checks-wp.yml`). The drift check holds each of them to its template: every job of the template, with the same `uses:` at the same major, the same `needs` (a job of its own may join them), `if`, `permissions`, `secrets` handling and inputs, and the template's triggers (its `$default-branch` the repository's default branch; a file that is the caller of two templates is not held to either's triggers, #324). It never compares the inputs the template says to fill in (`repository-owned` in `repos.yml`: `support-url`, `slug`, `version-constant`, `profile`, the release's `dry-run`), the inputs a repository adds that its template does not set (`main-file`, `requires-plugins-from`), or its own jobs. `sync-repos.py callers --repo NAME` (`--dry-run` shows the diff) opens an issue (Type Task, a PRD that passes G1, #432) and a pull request (run by a person, its commits are git commits signed with that person's key and pushed, as the organisation requires signed commits; dilux-bot's runs write through the API, #327) that rewrites only the jobs that differ, keeping those values, the caller's header and its own jobs, and adds the top-level permissions the template grants and the caller lacks (never removing its own, #329), and writes the template's triggers where the caller lacks one (a caller with triggers of its own the template lacks, or a schedule of its own while another trigger is missing, is left to a person; a schedule of its own alone is the repository's and never drift, #324). A repository at an older major migrates first ([`migrating.md`](migrating.md)), unless `repos.yml` names that major in `callers: migrates-from`: then the same pull request moves every call to the current major, the repository's own jobs too, and the lane merges a job whose only change is that (#320).
