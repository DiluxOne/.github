# Design systems

What a DiluxOne screen looks like, written once, here, instead of by hand in
each project. A design system is a directory with its tokens, its
components and the rules a review checks; a project says which one it uses.

| System | For | Projects |
| --- | --- | --- |
| [`wordpress-admin`](wordpress-admin/) | The admin screens of a WordPress plugin: WordPress's own pieces, its palette, its breakpoints, the person's colour scheme as the accent | Every plugin (`repos.yml`) |

## What a system holds

```
design-systems/<name>/
  README.md        what it is for, its principles, where its values came from
  tokens.json      the tokens, in the Design Tokens format ($value, $type)
  dist/tokens.css  the tokens as CSS custom properties, generated: never edited
  dist/stylelint.json  the pattern rules that read CSS, as stylelint's configuration, generated: never edited
  components.md    the components and patterns, each with its example
  rules.yml        what a review checks, as data, each pattern with its fixtures,
                   and its `screens`: the paths of the files that draw a screen
```

[`scripts/design-tokens.py`](../scripts/design-tokens.py) writes
`dist/tokens.css` from `tokens.json` and `dist/stylelint.json` from
`rules.yml` (`build`), and fails when they are out of step or a token, a
reference or a rule is wrong (`build --check`, run by this repository's pull
request pipeline with its `--test`). Every token is a property named
`--dx-<its path>`; a token that names another is `var()` of it, so a value
set at runtime (the accent, from the person's admin colour scheme) carries
everything built on it.

## What the checks hold a pull request to

`dist/stylelint.json` is not a second copy of the rules: it is `rules.yml`'s
pattern rules, the same expressions, for the stylelint rule
[`scripts/stylelint/design-system.mjs`](../scripts/stylelint/design-system.mjs),
and `scripts/design-lint.py --test` runs every CSS fixture of `rules.yml`
through it. A plugin's checks (`plugin-checks-wp.yml`, the
`Design system (stylelint)` job) run it on the CSS a pull request changes,
when the repository has a system in `repos.yml`:

- a rule of severity `error` (a raw colour, `!important`, a WordPress class
  restyled outside the plugin's wrapper) on a line the pull request adds or
  changes **fails** the check;
- a rule of severity `warning`, and anything on the lines it did not touch,
  is a **warning**: what a plugin already had is moved to the tokens in an
  issue of its own, not by whoever touches the file next;
- the message names the token that holds a raw value it found, from the
  rule's `tokens` (`#2271b1` is `var(--dx-color-accent)`);
- nothing of the repository's own stylelint setup counts: no
  `.stylelintrc`, no `.stylelintignore`, no `stylelint-disable` comment. An
  exception is a change to the rules, here, in a pull request a person
  merges. Minified files and what is under `vendor/` or `node_modules/` are
  not checked.

To run it on your machine, from a checkout of this repository beside the
plugin's:

```bash
npm ci --prefix ../.github/scripts/stylelint --ignore-scripts
node ../.github/scripts/stylelint/node_modules/stylelint/bin/stylelint.mjs \
  --config ../.github/design-systems/wordpress-admin/dist/stylelint.json \
  --config-basedir ../.github "assets/**/*.css"
```

A `local` system is read from the repository's `docs/design-system/` on the
base branch, so a pull request cannot loosen what checks it: its
`rules.yml`, added to the rules of the system its `README.md` extends, and
its `tokens.json`, added to that system's.

## A project and its system

A project says which system it uses in [`repos.yml`](../repos.yml):

```yaml
design-system:
  diluxone-offload-wordpress: wordpress-admin
  some-app: local
```

- **A system's name**: the project's screens follow that system. It carries a
  copy of the system's `dist/tokens.css`, taken from one of the
  organisation's tags (`v5`), and builds on the properties; the system's
  `rules.yml` is what its screens are held to.
- **`local`**: the project keeps its own, in `docs/design-system/` (a
  `README.md` at least, and the same files as a system here when it has
  tokens). It may extend a system of the organisation: its `README.md` says
  which (`Extends: wordpress-admin`), its tokens add to that system's and
  never redefine one, and its rules add to that system's.
- **Not listed**: no design system. A project with screens should name one.

When a pull request of a project changes a file that draws a screen (one of
the system's `screens`; a stylesheet when it lists none), the Claude review
reads the system's `README.md`, `components.md` and rules (the project's
`docs/design-system/` when it is `local`, with the system it extends), and a
finding that relies on them names the rule's id or the component
([`scripts/review-brief.sh`](../scripts/review-brief.sh), the kind's review
profile). What a system writes in those files is what every review of its
projects reads: keep them short.

`scripts/sync-repos.py --test` refuses a name that is neither a system here
nor `local`, and the daily drift check reports a `local` project with no
`docs/design-system/README.md`.

## Versions

A system changes like anything else here: an accepted issue, a pull request,
a person merges (this directory is high risk: every screen of every project
follows it). It is versioned with the organisation's tags, so a project
takes a new version of the tokens when it moves to a new major, or on
purpose in a pull request of its own. Renaming or removing a token is a
breaking change, as removing an input of a workflow is.

## Adding a system

1. `design-systems/<name>/` with the files above. Extract it from screens
   that exist rather than invent it, and say in its `README.md` where each
   value came from.
2. `python3 scripts/design-tokens.py build`, and commit `dist/tokens.css`.
3. Its row in the table at the top of this page, and the projects that use
   it in `repos.yml`.
