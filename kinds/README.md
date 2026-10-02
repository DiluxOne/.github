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
  *.md                anything a repository of this kind needs to know (wordpress-plugin/suppressions.md)
```

`pack.yml`:

| Key | What |
| --- | --- |
| `name` | The kind's name for people. |
| `aliases` | Other names a caller's `profile:` may use for this kind (one line, `[a, b]`). `plugin-wp` is the wordpress-plugin kind's: the name of its profile before packs existed, still accepted. |
| `workflows` | The reusable workflows in `.github/workflows/` that make up the battery. |
| `adapters` | The engines the kind's checks run and the language adapter each reads with. |
| `settings` | What the workflows read from the pack, free-form per kind (for wordpress-plugin, `plugin-check`: `strict`, `categories`, `include-experimental`, `ignore-codes`). |

A repository can add to a list in `settings` from its own policy, never
replace a value: it adds an exception, it does not turn a gate off. The
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
   the top of this page and in the README.

`python3 scripts/policy.py --test` checks every pack: its workflows exist,
it names its adapters, it has rules and a review profile.
