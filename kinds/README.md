# Kinds of project

The organisation's workflows and scripts know nothing about WordPress, or
about any other stack. What is specific to a kind of project lives in a
**pack**, a directory here, as data: its review profile, its rules, its
settings, the list of workflows that make up its battery. A repository says
which kind it is, once, in its `.github/review-policy.yml`:

```yaml
kind: wordpress-plugin
```

| Kind | Pack | For |
| --- | --- | --- |
| `wordpress-plugin` | [`wordpress-plugin/`](wordpress-plugin/) | a plugin published on wordpress.org |

## What a pack holds

```
kinds/<kind>/
  pack.yml            the manifest: name, aliases, workflows, adapters, settings
  rules.yml           what this kind's reviewers send back, as rules the engine checks
  review-profile.md   what the Claude review reads for this kind, on top of review-profiles/general.md
  surface.yml         its public surface, and its documentation paths (optional; "Public surface" below)
  dependabot.yml      the .github/dependabot.yml of its repositories (optional; "Dependabot" below)
  *.md                anything a repository of this kind needs to know (wordpress-plugin/suppressions.md)
```

`pack.yml`:

| Key | What |
| --- | --- |
| `name` | The kind's name for people. |
| `aliases` | Other names a caller's `profile:` may use for this kind (one line, `[a, b]`). `plugin-wp` is the wordpress-plugin kind's: the name of its profile before packs existed, still accepted. |
| `workflows` | The reusable workflows in `.github/workflows/` that make up the battery. |
| `own-checks` | What a repository of this kind requires of its own jobs in its **own checks** ruleset: `callers-of` (it needs one when it calls one of these workflows), `jobs` (the caller's job names whose checks are required), `skip` (check names left out). `scripts/sync-repos.py own-checks` creates it. |
| `detect` | How detection recognises a repository of this kind (#191, `scripts/detect.py`): `files` that must be at its root, a `header` (a root file matching `glob` whose first lines match `pattern`), and the `roles` a proposal gives its paths. Detection only proposes: the daily run opens an issue and a pull request adding a new repository to `repos.yml`, and a person merges it. |
| `adapters` | The engines the kind's checks run and the language adapter each reads with. |
| `settings` | What the workflows read from the pack, free-form per kind (for wordpress-plugin, `php`: `tools`, the PHP every tool runs on, `minimum`, the oldest every plugin supports, and `analysis-only`, the dev packages the unit tests leave out, read by [`scripts/php-versions.py`](../scripts/php-versions.py); `plugin-check`: `strict`, `categories`, `include-experimental`, `ignore-codes`). |
| `autopilot` | What the autopilot adds to every change of this kind beside what the Spec names (#341), one instruction per line, read into its work prompt by [`scripts/autopilot.py`](../scripts/autopilot.py) for the kind the repository's `.github/review-policy.yml` declares. For wordpress-plugin, the change's line in `readme.txt`'s changelog, under the held (`Unreleased.`) entry. |
| `repro` | How a bug is reproduced, by the layer the triage says it shows in (#352), read by [`scripts/repro-ways.py`](../scripts/repro-ways.py), whose header says what each key means. `ways`: one per way, each for a `layer` (`logic`, `browser`, `cli` or `api`), with the `test` file the agent writes (`{n}` the issue's number) and the `needs` it must find; `sandbox: php-unit` runs it in [`scripts/repro-sandbox.sh`](../scripts/repro-sandbox.sh), and any other is a command way: `setup` (with the network, before the test is in the tree), `theme` (installs a theme a report names), `run` and the `junit` report it writes, run by [`scripts/repro-run.sh`](../scripts/repro-run.sh) with no environment and no network but the machine's; `minutes`, and `context`, `list`, `example` and `guide` for the writer's brief. `affected`: paths mapped to the tests a pull request that touches them runs instead of the whole suite. A repository changes a way, adds one or switches one off (`false`) in its `.github/review-policy.yml`, and adds its own `affected`. A layer with no way gets `could-not-reproduce` and the reason; a repository with no ways at all keeps the PHP unit test. For wordpress-plugin, `unit` (PHPUnit under `tests/Unit/Repro/`) and `browser` (Playwright on wp-env under `tests/e2e/repro/`, through [`playwright.dx-repro.config.ts`](wordpress-plugin/playwright.dx-repro.config.ts)). |
| `release` | How a version of this kind is released (#82), read by [`scripts/release-issue.py`](../scripts/release-issue.py): `publishes-to` (where it goes, for people), `workflow` (the reusable workflow that releases it, ending at the GitHub release with its build, #287; the repository's caller of it holds the inputs), `publish` (the reusable workflow that, on that release's publishing, sends its build where the kind publishes; for wordpress-plugin, `plugin-publish-wp.yml` to wordpress.org), `prepare` (the command that turns the default branch into the release pull request, one argument per item: `{version}`, `{central}` for the checkout of this repository, any other `{name}` the caller's input) `defaults` (an input the caller leaves out) and `stable` (where the version in production is published, `url` with `{slug}` and the JSON `field`, which [`scripts/production-version.py`](../scripts/production-version.py) checks the last GitHub release against before a security patch, #247). A kind without it publishes nothing, and its release issue says so. |

A repository can add to a list in `settings` from its own policy, never
replace a value: it adds an exception, it does not turn a gate off (nor
choose its own PHP: `php.tools` and `php.minimum` are the pack's alone). The
checks read that policy from the base branch, so a pull request cannot
exempt itself; its additions apply once it has merged.

```yaml
# .github/review-policy.yml
kind: wordpress-plugin
kind-settings:
  plugin-check:
    ignore-codes: [some_code_this_plugin_cannot_avoid]   # added to the pack's list
```

## How the pieces find the pack

- [`scripts/policy.py`](../scripts/policy.py) reads `kind:` and fails on a
  kind that has no pack. Every mode writes `kind`; `POLICY_MODE=kind` writes
  the kind, the paths of its rules and profile, and its settings merged with
  the repository's `kind-settings` (as JSON, which a workflow reads with
  `fromJSON`). `policy.py --profile <name>` resolves a `profile:` (general, a
  kind, an alias).
- [`scripts/kind.sh`](../scripts/kind.sh) is that call from a workflow: the
  policy from the base branch, the workflow's own kind as the default.
- The Claude review ([`claude-review.yml`](../.github/workflows/claude-review.yml),
  [`review-reply.yml`](../.github/workflows/review-reply.yml),
  [`scripts/review-brief.sh`](../scripts/review-brief.sh),
  [`scripts/local-review.sh`](../scripts/local-review.sh)) adds the kind's
  `review-profile.md` to `general.md`: the one the caller's `profile:` names,
  or, when it names only `general` (the default now), the one of the kind the
  repository declares.
- The engine, [`scripts/review-rules.php`](../scripts/review-rules.php), runs
  `kinds/<kind>/rules.yml` (`--kind <kind>`).
- [`scripts/php-versions.py`](../scripts/php-versions.py) turns the pack's
  `php` and the plugin's own `Requires PHP` into the PHP the checks run on:
  the tools' PHP, the minimum they analyse for, and every release between
  the two for the syntax and unit-test jobs. A plugin that still declares a
  higher `Requires PHP` than the pack's minimum is checked from its own,
  with a warning, until it lowers it; a pull request that raises it above
  both the base's and the minimum fails.
- What a screen looks like is not the kind's: it is the design system's
  ([`design-systems/`](../design-systems/)), which a repository names in
  `repos.yml` whatever its kind. Its pattern rules for CSS run in the
  kind's checks all the same (`plugin-checks-wp.yml`,
  `Design system (stylelint)`, [`scripts/design-lint.py`](../scripts/design-lint.py)):
  a rule about how a screen looks goes into the system's `rules.yml`, not
  into a pack's.

**What a pack cannot do: choose the workflows.** GitHub resolves a
`uses: owner/repo/.github/workflows/file.yml@ref` line before anything runs,
so a reusable workflow cannot be picked from data. The workflows of a kind
stay files in `.github/workflows/`, with the kind's suffix
(`plugin-checks-wp.yml`), and a repository's caller names them (the
templates in [`workflow-templates/`](../workflow-templates/) do). What those
files hold is the generic part: they take the kind as an input, read its
rules and settings from the pack, and run the generic engine. `pack.yml`
lists them so a person (and `policy.py --test`) can see the battery in one
place. A repository that declares another kind than the workflow it calls
fails the checks with that message.

## Adding a rule after a rejection

Every rejection becomes one entry in the kind's `rules.yml`, never a new
script or workflow. In the same pull request:

1. **Write the entry** (fields below): an `id` in kebab-case, the `type`
   that reads the shape, a `severity`, the `message` a contributor sees (what
   the reviewer objects to and what to do instead), and the `source`: which
   review and when, e.g. `wordpress.org plugin review, DiluxOne Users+ round 1
   (T10), 2026-10-01`.
2. **Write its fixtures**: under `fixtures.fail`, the shortest code that must
   trip it (the line the reviewer quoted, trimmed); under `fixtures.pass`, the
   closest code that must not (the fix, and the look-alikes that are fine). A
   rule without both does not load.
3. **Run** `php scripts/review-rules.php --test` (every fixture of every pack)
   and the rule on the repositories of that kind
   (`php scripts/review-rules.php --kind <kind> --repo <checkout> --tree <shipped tree>`):
   a finding there is either real (fix it, or list the exception) or the
   rule is too wide (narrow it, and add the case as a `pass` fixture).
4. **Teach the reviewer** too, when reading is needed beyond what the rule
   sees: a bullet in the kind's `review-profile.md`.

A shape no rule type can read is the one case for touching the engine: a
new rule type (or a new option of one) in `scripts/review-rules.php`, with
its own tests in `--test`, and the rule as data on top of it.

### Rule fields

Every rule: `id`, `type`, `severity` (`error` fails the check, `warning` and
`notice` annotate), `message` (with the `{placeholders}` of its type),
`source`, `fixtures` (`fail` and `pass` lists; an item is the code of one
file, or a map of path to content for several), and optionally `scope`
(`tree`, the code that ships, the default; or `repo`, the repository root),
`language` (the adapter; the file's `language:` by default) and `flags`
(regular-expression flags, e.g. `i`, `s`).

Regular expressions are PCRE, written as the body only (no delimiters);
single-quoted YAML keeps backslashes as they are (`'\$_GET'`).

| Type | Reads | Fields | Placeholders |
| --- | --- | --- | --- |
| `comment` | every comment | `pattern`; `unless` (a comment that also matches it is fine) | `{match}` |
| `call-arg` | an argument of a function call, written as `fn()`, `\fn()` or `Ns\fn()` | `functions` (a list, or a map of function to argument position; `"*"` is every call, methods included), `argument` (1-based position, or `any`), `argument-name` (the named-argument form), `except-functions`, `superglobals`, `when`: `present`, `below: N` (a value that is not a number literal counts as below), `contains-superglobal`, `is-superglobal`, `matches` | `{function}`, `{value}` |
| `forbidden-call` | a function call | `functions` | `{function}` |
| `hook-callback` | the function a hook is registered with (`'fn'`, `'Class::m'`, `array( $this, 'm' )`, `[ __CLASS__, 'm' ]`, `[ self::class, 'm' ]`, a closure, an arrow function, `$this->m( ... )`), resolved anywhere in the tree | `hooks` (globs over the hook's name; a part built at runtime reads as `*`), `registrars` (default `add_action`, `add_filter`), `public-hooks` (a callback also registered on one of these is skipped), `top-level-only` (a registration inside a function body is conditional, and skipped), `superglobals`, `ignore-keys` (a superglobal read whose literal key matches is not a read), `require`: a list of `calls: [...]` with `before-first: superglobal-read` and `when-no-read: pass`, or `contains: regex` with a `label`; either with `unless-calls: [...]` | `{hook}`, `{callback}`, `{missing}` |
| `forbidden-config` | configuration files in the repository (scope `repo`) | `files` (globs), `pattern` | `{match}` |
| `suppression-allowlist` | every `phpcs:ignore` / `phpcs:disable` | `sniffs` (the checks whose suppression must be listed), `never` (checks that can never be listed), `file` (the list, default `.github/review-suppressions.yml`), `reason-pattern` with `reason-severity` and `reason-message` (a reason in the list that matches is reported), `stale-message` | `{sniff}`, `{fingerprint}`, `{entry}`, `{list}` |

A callback the tree does not define (a function of another plugin, a method
two classes share) is not read: the rule says nothing rather than guess.

### The suppressions file

A `suppression-allowlist` rule holds every suppression of the checks it
names to an entry in the repository's `.github/review-suppressions.yml`:

```yaml
suppressions:
  - file: includes/admin.php          # from the repository's root
    sniff: WordPress.Security.NonceVerification.Recommended   # as the comment names it
    fingerprint: c55a8742d2b6         # the code the comment covers
    reason: Which tab to draw; nothing is saved and nothing is printed from it.
```

The fingerprint is the first 12 hex digits of the SHA-1 of the code the
comment covers: the line it ends (a trailing `// phpcs:ignore`), or else the
next line with code, and the two lines with code after it, comments left out
and whitespace collapsed. Moving the block keeps it, changing that code does
not. Entries are matched one to one: two identical blocks in one file share a
fingerprint and need an entry each. An entry that matches nothing any more
(the code changed or went away) fails as stale, so the list never says more
than the code does. A `reason` that points somewhere else ("the caller
verifies it", "checked below") is a warning, as it is in the comment.
A bare `phpcs:ignore` (no check named) and the checks under `never` cannot be
listed at all. The file lives under `.github/`, so a pull request that adds
an entry is high risk and a person reads the reason.

To start one, or to see what is missing:

```bash
php scripts/review-rules.php --kind wordpress-plugin --repo . --tree build/<slug> --suggest-suppressions
```

It prints the missing entries with `reason: "TODO: …"`; each reason is
written by a person, for the reviewer who will read it.

## Public surface

An accepted Bug or Docs issue lets a `fix` or `docs` pull request through the
accepted-issue gate; it must not carry functionality nobody accepted in with
it (#144). The conventions check fails a pull request whose type is not
`feat` (and has no `!`), from an author who is not trusted (the policy's
`trusted-authors`, read from the base branch; bots are never checked), when
its diff adds what the kind's `surface.yml` lists. The message is neutral:
new functionality needs a Feature issue a maintainer accepted, with a link to
CONTRIBUTING.md. [`scripts/surface.py`](../scripts/surface.py) reads only git
objects (the diff, and the files at the merge base and at the head), so it
runs on a fork's pull request too, with no secret and nothing of the pull
request executed. A kind without `surface.yml` has no surface check.

`surface.yml`:

| Key | What |
| --- | --- |
| `docs-paths` | Shell `case` globs (`*` crosses directories) a `docs` pull request may change, added to the organisation's `docs-paths` in [`policy/review-policy.default.yml`](../policy/review-policy.default.yml) (all a repository without a kind gets). wordpress-plugin adds `readme.txt`. |
| `files`, `exclude` | Globs (`**` crosses directories, `*` does not) of the files the surface is read in, and of those never read (wordpress-plugin: dependencies at any depth; tests and hidden folders at the root only, so the same names deeper in cannot hide surface). |
| `surface` | The entries: `id`, `what` (how the message names it), `pattern` (a Python regular expression over a whole file, so a call may span lines), optionally `files` of its own, and `fixtures`. |
| `sensitive` | Security-sensitive code (#287): entries (`id`, `what`, `pattern` over one line, `when`: `changed`, the default, for a line added or removed, or `removed`, for what only weakens when it goes, such as an escape, counted per call so one moved to another line is not taken out; and `fixtures`). An autopilot's change that adds or removes a line one matches is merged by a person, whatever its issue's Type and the review's risk (`surface.py --sensitive`, read by the auto-merge decision; not knowing counts as touching, except for a kind with no list, which has nothing sensitive). wordpress-plugin lists permissions and capabilities, nonces, `$wpdb`, authentication, code that runs commands or writes files, and an escape or a sanitiser taken out. |

An entry whose `pattern` has a `name` group is new when that name (a quoted
literal compared without its quotes, or the expression as written,
whitespace aside) appears nowhere in the base's files of the entry: a hook
moved, or fired a second time, is not new. One without is new when the
changed files hold more matches at the head than at the base: a call changed
in place, or moved to another file, is not new (nor, by the same count, one
added where another is removed: the human merge reads that). The check is
required in every repository of the kind, so an entry stays conservative: a
pattern that is unsure says nothing, and the human merge still reads the
change.

Fixtures: `fail` (must be found) and `pass` (must not), each the head of one
new file (a string), `{base, head, path}` for one file, or `{files: {path:
{base, head}}}` for several (no `base`, the file is new; no `head`, deleted).
`python3 scripts/surface.py --test` runs every pack's.

## Dependabot

Every repository's `.github/dependabot.yml` comes from the organisation
(#178): `scripts/sync-repos.py dependabot` writes the kind's
`dependabot.yml` there, as a pull request with its issue, and the daily drift check
(`sync-repos.py check`) reports a repository whose file differs. A kind
without one, and a repository without a kind, get
[`policy/dependabot.default.yml`](../policy/dependabot.default.yml).

A template is a whole Dependabot configuration with one entry under
`updates` for every ecosystem the organisation's repositories use
(github-actions, npm, composer, docker), each with the comments right above
it and one `directories: ["/"]` line. A repository gets only the entries of
the ecosystems it has: github-actions always, npm with a `package.json` at
its root, composer with a `composer.json`, docker with a `Dockerfile`. What
a repository adds lives in [`repos.yml`](../repos.yml) (`dependabot`), per
ecosystem, and nothing else is kept: `directories` (beside its root's; they
turn the ecosystem on) and `ignore` (Dependabot's own entries, written under
the entry). The rule a template keeps, and `sync-repos.py --test` holds it
to: every dependency on its latest version, so each ecosystem is checked
daily, with no cooldown and no `ignore`, its groups take every dependency
and every kind of update (majors included), one for the version updates and
one for the security updates, with the labels of
[`labels.yml`](../labels.yml) and a `ci` or `build` prefix with its scope
(`ci(deps): …`, `build(deps-dev): …`).

## The engine

[`scripts/review-rules.php`](../scripts/review-rules.php) is generic: rule
types and language adapters, no rule of its own. It reads the rules files
with a YAML subset parser of its own (no extension or library on a runner or
a laptop): block maps and lists, flow lists of scalars, quoted and plain
scalars, `|` and `>` blocks, comments. Anchors, tags, flow maps and multiple
documents are refused with their line, never guessed at; `--test` reads every
pack's files through it and through a real YAML library (yq or PyYAML, when
installed) and fails if the two differ.

A language adapter turns files into what the rule types ask for: comments,
calls and their arguments, function bodies, hook registrations,
suppressions. PHP's is `RR_Php_Adapter`, on PHP's own tokenizer, so a string
or a comment is never read as code. Another language is a class with the
same methods, registered in `rr_adapter()`; a rule names it with `language:`.

## Adding a kind

A future `node-app`, say:

1. `kinds/node-app/pack.yml` (name, workflows, adapters, settings),
   `review-profile.md`, and `rules.yml` (it may start with no rules of
   substance, but every rule carries fixtures).
2. Its battery as reusable workflows with the kind's suffix
   (`app-checks-node.yml`, …): generic steps that take `kind` as an input,
   call `scripts/kind.sh` for the settings and `scripts/review-rules.php
   --kind node-app` for the rules. The checks of the wordpress-plugin kind
   are the model.
3. If its rules read another language, an adapter in the engine (see
   above), with tests.
4. Its caller templates in `workflow-templates/`, its row in the table at
   the top of this page, and its name where
   [`docs/adopting.md`](../docs/adopting.md) lists the kinds.

`python3 scripts/policy.py --test` checks every pack: its workflows exist,
it names its adapters, it has rules and a review profile.
