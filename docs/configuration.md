# Configuration

Every setting the engine applies (#568): its default, who may change it and how far. Written by `python3 scripts/settings.py docs` from [`policy/settings-schema.yml`](../policy/settings-schema.yml), which CI holds to the engine's files and to the scripts that read them (`settings.py check`): edit the schema, never this page. Which level a value in force comes from: `settings.py explain FILE KEY`.

The levels, named the same everywhere:

- **engine**: the engine's defaults, the files of DiluxOne/.github.
- **org**: the organisation's configuration, its own `.github` repository, laid over the engine's by `scripts/config-overlay.sh`. A file it has overrides only the keys it sets: a mapping key by key, a value or a list replaced, an `add-only` list added to (the engine's entries are kept), `labels.yml` merged by name. `repos.yml` and any file that is not YAML replace the engine's whole. The merged autonomy policy must pass `autonomy.py check`, or the run stops.
- **repo**: a repository's own file (`.github/autonomy.yml`, `.github/review-policy.yml`, its entry in `repos.yml`), read by the script that applies the setting, within what its organisation lets it and never past the engine's safeguards: autonomy cannot widen itself.

What a level may do: `any` value; `lower-only`; `stricter` (switch off, narrow, ask a person); `up-to-ceiling` (raise it up to the setting's ceiling; past it, held there with a warning); `add-only` (add entries, never remove one); `never`.

## `org.yml`

| Setting | Default | org | repo | Limit | Read by | Issue |
|---|---|---|---|---|---|---|
| `org`: The organisation's login on GitHub. | the organisation's own, never the engine's | `any` | `never` | the login of the organisation whose `.github` it is; the overlay stops a run whose org.yml names another | [`org.py`](../scripts/org.py), [`config-overlay.sh`](../scripts/config-overlay.sh) | #191 |
| `central`: The repository that holds the organisation's configuration. | the organisation's own, never the engine's | `any` | `never` | the organisation's `.github` repository | [`org.py`](../scripts/org.py) | #191 |
| `bot`: The organisation's App: `app` its slug, `id` its user id. | the organisation's own, never the engine's | `any` | `never` | the organisation variables DX_BOT_APP, DX_BOT_LOGIN and DX_BOT_ID win over it, and every workflow needs them | [`org.py`](../scripts/org.py) | #191, #197, #568 |
| `security`: The private repository where security work happens. | the organisation's own, never the engine's | `any` | `never` | a private repository of the organisation; none, no security work | [`org.py`](../scripts/org.py) | #194, #287 |
| `maintainers`: The organisation's maintainers, trusted authors of every repository and who may run scripts/sync-repos.py for the org-sync lane. | the organisation's own, never the engine's | `any` | `never` | people with the admin or maintain role | [`org.py`](../scripts/org.py), [`autonomy.py`](../scripts/autonomy.py), [`policy.py`](../scripts/policy.py) | #568 |
| `catalogs`: The catalog each kind publishes to (`{catalog}` in its pack's `release.publishes-to`); a kind without one publishes nowhere. | the organisation's own, never the engine's | `any` | `never` | a repository of the organisation, per kind that publishes to a catalog | [`org.py`](../scripts/org.py) | #552, #568 |
| `merge-queue`: Whether the merge queue is on where GitHub gives one. | `"auto"` | `any` | `any` | `auto`, `on` or `off`; a repository's exception is repos.yml `merge-queue` | [`sync-repos.py`](../scripts/sync-repos.py), [`repos_conf.py`](../scripts/repos_conf.py) | #451 |
| `pre-pr`: Whether a repository without `make pre-pr` fails its pull requests. | `"optional"` | `any` | `stricter` | `optional` or `required`; a repository without one by design is repos.yml `pre-pr: false` | [`pre-pr.py`](../scripts/pre-pr.py), [`sync-repos.py`](../scripts/sync-repos.py) | #479 |
| `who-decides`: Whose answers the autopilot takes, and who may add `accepted`, `autopilot:continue`, `/coauthor` and `/uncoauthor`. | `"codeowners"` | `any` | `any` | `codeowners` (the owners of the files the autopilot's open pull request that closes the issue touches (never a person's), else of the Spec's `Spec: files` while its seal still matches, else of the catch-all rule), `acceptor` or `writers`, each within its action's floor (write; maintain for the credits); a repository's exception is repos.yml `who-decides` | [`org.py`](../scripts/org.py), [`deciders.py`](../scripts/deciders.py) | #588 |
| `attribution`: What the conventions check does with a model named as a co-author. | `"warn"` | `any` | `never` | `warn` or `required` | [`org.py`](../scripts/org.py) | #491 |
| `adopted-property`: The custom property that says a repository is adopted, which the organisation's rulesets cover. | `"dx-adopted"` | `any` | `never` | a custom property of the organisation | [`sync-repos.py`](../scripts/sync-repos.py) | #562 |
| `conventions-contradictions`: A repository's own commit rules that contradict the organisation's, which the daily drift check lists. | the patterns in org.yml | `any` | `never` | each pattern with the lines it must find and must not | [`sync-repos.py`](../scripts/sync-repos.py) | #562 |

## `repos.yml`

| Setting | Default | org | repo | Limit | Read by | Issue |
|---|---|---|---|---|---|---|
| `repos.*.merge-queue`: A repository's exception to org.yml `merge-queue`. | org.yml `merge-queue` | `any` | `any` | `auto`, `on` or `off` | [`repos_conf.py`](../scripts/repos_conf.py), [`sync-repos.py`](../scripts/sync-repos.py) | #451 |
| `repos.*.who-decides`: A repository's exception to org.yml `who-decides`. | org.yml `who-decides` | `any` | `any` | `codeowners`, `acceptor` or `writers` | [`repos_conf.py`](../scripts/repos_conf.py), [`deciders.py`](../scripts/deciders.py) | #588 |
| `repos.*.pre-pr`: Whether a repository has `make pre-pr`. | `true` | `any` | `stricter` | `false` only for a repository with no `make pre-pr` by design | [`repos_conf.py`](../scripts/repos_conf.py), [`sync-repos.py`](../scripts/sync-repos.py) | #479 |

## `policy/autonomy.yml`

| Setting | Default | org | repo | Limit | Read by | Issue |
|---|---|---|---|---|---|---|
| `autopilot`: Whether anything proceeds without a person deciding. | `true` | `any` | `stricter` | the organisation variable DX_AUTOPILOT=off stops it everywhere | [`autonomy.py`](../scripts/autonomy.py) | #78 |
| `autopilot-rounds`: Review rounds the autopilot may spend on a blocked pull request. | `5` | `any` | `never` | a whole number above 0 | [`autopilot.py`](../scripts/autopilot.py) | #83 |
| `autopilot-runs`: Runs the autopilot may spend on one issue's draft pull request. | `5` | `any` | `never` | a whole number above 0 | [`autopilot.py`](../scripts/autopilot.py) | #83 |
| `autopilot-mode`: How the autopilot settles a choice the Spec leaves open. | `{"default": "guided", "ceiling": "full"}` | `any` | `up-to-ceiling` | `guided` or `full`, a repository up to `ceiling` | [`autonomy.py`](../scripts/autonomy.py), [`autopilot.py`](../scripts/autopilot.py) | #247 |
| `budgets-usd.*`: The most one agent's run may cost. | each one's own, in `policy/autonomy.yml` | `any` | `lower-only` | above 0 and at most 200 dollars | [`autonomy.py`](../scripts/autonomy.py), [`autopilot.py`](../scripts/autopilot.py) | #287 |
| `claims.*`: A person's claim on an issue, its days and its limits. | each one's own, in `policy/autonomy.yml` | `any` | `lower-only` | a whole number from 1 to 365 | [`autonomy.py`](../scripts/autonomy.py), [`claim.py`](../scripts/claim.py) | #488 |
| `constitution`: The protected paths, always accepted and merged by a person. Added to, never replaced. | `["policy/**", ".github/**", "scripts/**", "kinds/**", "review-profile…` | `add-only` | `add-only` | `policy/**` and `rules/**` are always protected | [`autonomy.py`](../scripts/autonomy.py), [`no-widening.py`](../scripts/no-widening.py) | #78, #187 |
| `person-merges`: The labels whose issue a person always merges. Added to, never replaced. | `["security"]` | `add-only` | `add-only` | `security` is always there | [`autonomy.py`](../scripts/autonomy.py) | #194 |
| `planned-release`: Whether a planned version's release issue is accepted by policy when its milestone closes. | `"auto"` | `any` | `never` | `auto` or `confirm`; DX_AUTOPILOT=off is always `confirm` | [`milestones.py`](../scripts/milestones.py) | #247 |
| `security-patch.*`: The limits a security patch must stay within before it is announced. | each one's own, in `policy/autonomy.yml` | `any` | `never` | max-files 1 to 100, max-lines 1 to 5000, forbidden globs, a Claude reviewer-model | [`security-patch.py`](../scripts/security-patch.py) | #247, #287 |
| `lanes.*.description`: What the lane covers. | each one's own, in `policy/autonomy.yml` | `any` | `never` | says what the lane covers | [`autonomy.py`](../scripts/autonomy.py) | #78 |
| `lanes.*.enabled`: Whether the lane is on. | `true` | `any` | `stricter` | a lane switched off accepts nothing | [`autonomy.py`](../scripts/autonomy.py) | #78 |
| `lanes.*.accept`: Whether the lane's issue is accepted by policy, or waits for a person's `accepted` (a reproduced bug fixed on its own, or waiting). | each one's own, in `policy/autonomy.yml` | `any` | `stricter` | `human` or `policy`; the release lane is always `human` | [`autonomy.py`](../scripts/autonomy.py) | #78, #397 |
| `lanes.*.type`: The Type of the lane's issue. | each one's own, in `policy/autonomy.yml` | `any` | `never` | the issue's Type the lane takes | [`autonomy.py`](../scripts/autonomy.py) | #155 |
| `lanes.*.origin`: Who opens the lane's issues, and how it is recognised. | each one's own, in `policy/autonomy.yml` | `any` | `never` | `app` is org.yml's App when it is not set, `people` org.yml `maintainers` | [`autonomy.py`](../scripts/autonomy.py) | #78, #568 |
| `lanes.*.repositories`: The repositories the lane covers. | each one's own, in `policy/autonomy.yml` | `any` | `stricter` | a repository only narrows it | [`autonomy.py`](../scripts/autonomy.py) | #78 |
| `lanes.*.evidence`: What the lane's acceptance rests on, in words. | each one's own, in `policy/autonomy.yml` | `any` | `never` | what the lane's acceptance rests on | [`autonomy.py`](../scripts/autonomy.py) | #78 |
| `lanes.*.merge`: The most a pull request closing the lane's issue may be, as the review rates it, and still merge on its own. | each one's own, in `policy/autonomy.yml` | `any` | `up-to-ceiling` | up to the lane's `ceiling`; the release lane never merges on its own; an issue marked Critical never does | [`autonomy.py`](../scripts/autonomy.py) | #83, #188 |
| `lanes.*.ceiling`: The most a repository's own file may raise the lane's `merge` to. | the lane's `merge` | `any` | `never` | never below the lane's `merge`; the release lane has none | [`autonomy.py`](../scripts/autonomy.py) | #188 |
| `lanes.*.constitution-merge`: The caps within which a reproduced bug's fix in a protected path merges on its own. | each one's own, in `policy/autonomy.yml` | `any` | `never` | only the bugfix-reproduced lane, and only a fix that widens nothing (scripts/no-widening.py) | [`autonomy.py`](../scripts/autonomy.py) | #397 |

## `policy/review-policy.default.yml`

| Setting | Default | org | repo | Limit | Read by | Issue |
|---|---|---|---|---|---|---|
| `trusted-authors`: Who may have a pull request merged without a person. | `["dependabot[bot]"]` | `any` | `any` | org.yml `maintainers` are always added | [`policy.py`](../scripts/policy.py) | #78, #568 |
| `issue-gate.required`: Every pull request closes an accepted issue. | `true` | `any` | `stricter` | a repository turns it off only when `optional` is true | [`policy.py`](../scripts/policy.py) | #78 |
| `issue-gate.label`: The label that accepts an issue. | `"accepted"` | `any` | `never` | the label a person adds | [`policy.py`](../scripts/policy.py) | #78 |
| `issue-gate.optional`: Whether a repository may turn the issue gate off. | `false` | `any` | `never` | true lets a repository turn the gate off | [`policy.py`](../scripts/policy.py) | #78 |
| `max-changed-lines-untrusted`: The most lines a pull request from an author who is not trusted may change. | `600` | `any` | `lower-only` | 0 is no limit, and only the organisation can say it | [`policy.py`](../scripts/policy.py) | #130, #361 |
| `docs-paths`: What a pull request titled docs may change. | `["*.md", "docs/*.png", "docs/*.jpg", "docs/*.jpeg", "docs/*.gif", "do…` | `any` | `never` | a kind adds its own (kinds/<kind>/surface.yml) | [`surface.py`](../scripts/surface.py) | #353 |
| `high-risk`: The paths that make a pull request high risk. | `[".github/**", "AGENTS.md", "CLAUDE.md", ".claude/**", "Makefile", ".…` | `any` | `add-only` | a repository only adds paths | [`policy.py`](../scripts/policy.py) | #78 |
| `review`: Which reviewer each risk level gets. | `{"low": {"model": "claude-sonnet-5-5", "effort": "low"}, "medium": {"…` | `any` | `any` | a model id and an effort of low, medium, high, xhigh or max | [`policy.py`](../scripts/policy.py) | #78 |
| `budget-usd`: The most one review run may spend. | `3` | `any` | `any` | dollars per review run | [`policy.py`](../scripts/policy.py) | #78 |
| `auto-merge`: Whether a pull request that meets every condition merges on its own. | `true` | `any` | `stricter` | false here stops it everywhere | [`policy.py`](../scripts/policy.py) | #78 |
| `release`: Whether a release waits for a person, per kind of bump. | `{"patch": "approve", "minor": "approve", "major": "approve"}` | `any` | `stricter` | `auto` only where `auto-allowed` is true | [`plugin-release-wp.yml`](../.github/workflows/plugin-release-wp.yml) | #82 |
| `auto-allowed`: Whether a repository may release a bump without a person. | `false` | `any` | `never` | true lets a repository set a bump to `auto` | [`plugin-release-wp.yml`](../.github/workflows/plugin-release-wp.yml) | #82 |
| `low-risk-eligible`: The paths a pull request may change and still be rated low risk. | `["**/*.md", "docs/**", "tests/**", "package-lock.json", "composer.loc…` | `any` | `add-only` | a repository only adds paths | [`policy.py`](../scripts/policy.py) | #78 |
| `code`: What counts as code, for the slow suites. | `["**/*.php", "**/*.js", "**/*.mjs", "**/*.jsx", "**/*.ts", "**/*.tsx"…` | `any` | `add-only` | a repository only adds paths | [`policy.py`](../scripts/policy.py) | #78 |
| `plugin-check`: The files that are not code but that Plugin Check reads. | `["readme.txt", "**/.*"]` | `any` | `add-only` | a repository only adds paths | [`policy.py`](../scripts/policy.py) | #78 |
| `kind-settings`: A repository's exceptions to its kind's `settings`. | `{}` | `never` | `add-only` | a list is appended to the pack's, a map merged; a single value of the pack is never replaced | [`policy.py`](../scripts/policy.py) | #191 |

## `kinds/*/pack.yml`

| Setting | Default | org | repo | Limit | Read by | Issue |
|---|---|---|---|---|---|---|
| `name`: The kind's name. | each one's own, in `kinds/*/pack.yml` | `any` | `never` | the kind's name for people | [`detect.py`](../scripts/detect.py) | #191 |
| `aliases`: Other names of the kind. | each one's own, in `kinds/*/pack.yml` | `any` | `never` | names a profile may still use | [`policy.py`](../scripts/policy.py) | #191 |
| `workflows`: The workflows that make up the kind's battery. | each one's own, in `kinds/*/pack.yml` | `any` | `never` | reusable workflows of the engine | [`sync-repos.py`](../scripts/sync-repos.py) | #191 |
| `own-checks`: What a repository of the kind requires of its own jobs. | each one's own, in `kinds/*/pack.yml` | `any` | `never` | a ruleset that exists is never rewritten | [`sync-repos.py`](../scripts/sync-repos.py) | #552 |
| `pre-pr`: What a repository of the kind's `make pre-pr` runs, in words. | each one's own, in `kinds/*/pack.yml` | `any` | `never` | every check the pull request and the merge queue run | [`pre-pr.py`](../scripts/pre-pr.py) | #479 |
| `pre-pr-make`: How `make pre-pr` runs them (dx.mk). | each one's own, in `kinds/*/pack.yml` | `any` | `never` | bash, one command a line | [`pre-pr.py`](../scripts/pre-pr.py), [`sync-repos.py`](../scripts/sync-repos.py) | #479 |
| `detect`: How detection recognises a repository of the kind. | each one's own, in `kinds/*/pack.yml` | `any` | `never` | detection only proposes; repos.yml says what a repository is | [`detect.py`](../scripts/detect.py) | #191 |
| `adapters`: The engines the kind's checks run, and the language of each. | each one's own, in `kinds/*/pack.yml` | `any` | `never` | engines of the engine | [`policy.py`](../scripts/policy.py) | #191 |
| `settings`: The kind's settings for its checks. | each one's own, in `kinds/*/pack.yml` | `any` | `add-only` | a repository adds exceptions with `kind-settings`, never turns a gate off | [`policy.py`](../scripts/policy.py) | #191 |
| `autopilot`: What the autopilot adds to every change of the kind. | each one's own, in `kinds/*/pack.yml` | `any` | `never` | instructions added to the autopilot's work prompt | [`autopilot.py`](../scripts/autopilot.py) | #341 |
| `repro`: How a bug of the kind is reproduced. | each one's own, in `kinds/*/pack.yml` | `any` | `any` | a repository's own `repro:` wins (scripts/repro-ways.py) | [`repro-ways.py`](../scripts/repro-ways.py) | #377 |
| `release.publishes-to`: Where a release of the kind is published. | each one's own, in `kinds/*/pack.yml` | `any` | `never` | `{catalog}` is org.yml `catalogs` for the kind | [`release-issue.py`](../scripts/release-issue.py) | #82, #552, #568 |
| `release.workflow`: The workflow that makes the GitHub release. | each one's own, in `kinds/*/pack.yml` | `any` | `never` | a reusable workflow of the engine | [`release-issue.py`](../scripts/release-issue.py) | #82 |
| `release.publish`: The workflow that publishes the release. | each one's own, in `kinds/*/pack.yml` | `any` | `never` | a reusable workflow of the engine | [`install.py`](../scripts/install.py) | #82 |
| `release.prepare`: The command that prepares the release pull request. | each one's own, in `kinds/*/pack.yml` | `any` | `never` | a command of the engine's scripts | [`release-issue.py`](../scripts/release-issue.py) | #82 |
| `release.defaults`: The defaults of the release's inputs. | each one's own, in `kinds/*/pack.yml` | `any` | `any` | a repository's caller inputs win | [`release-issue.py`](../scripts/release-issue.py) | #82 |
| `release.stable`: Where the version in production is read, when it is not the last GitHub release. | each one's own, in `kinds/*/pack.yml` | `any` | `never` | where the version in production is read | [`production-version.py`](../scripts/production-version.py) | #287 |

## `labels.yml`

| Setting | Default | org | repo | Limit | Read by | Issue |
|---|---|---|---|---|---|---|
| (the whole list): Every label the organisation's workflows and people use, with its colour and description. Merged by `name`. | each one's own, in `labels.yml` | `any` | `never` | a label the engine's workflows use keeps its name | [`sync-repos.py`](../scripts/sync-repos.py) | #78, #564 |
