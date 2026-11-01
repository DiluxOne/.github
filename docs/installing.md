# Installing the engine in another organisation

The engine is DiluxOne's; the configuration is the organisation's ([phase 12](plans/autonomy.md#phase-12--setup-for-other-organisations), #197). Another organisation never copies the workflows, scripts or gates: its callers name them by tag (`uses: DiluxOne/.github/.github/workflows/<name>.yml@v7`), and every run lays the organisation's own `.github` repository over the engine's defaults ([`scripts/config-overlay.sh`](../scripts/config-overlay.sh)). An improvement to the engine reaches it when the major tag moves; a breaking one comes in a new major, with its migration notes ([versioning](versioning.md)).

## What the organisation needs first

- **Its own App**, made by an administrator of the organisation and installed on every repository. The installer prints GitHub's form to create it, filled in (`scripts/install.py`, `APP_PERMISSIONS`: actions, contents, issues, pull requests, organisation and repository projects write; checks, metadata and organisation administration read; private, no webhook): `https://github.com/organizations/<Org>/settings/apps/new?name=<Org>-bot&...`. Then its private key, its installation on all repositories, the secret `DILUX_BOT_PRIVATE_KEY` and the variables below. DiluxOne's App and its key never leave DiluxOne.
- **A token for Claude**: `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`) or `ANTHROPIC_API_KEY`.

## Install

From a checkout of this repository, as an administrator of the organisation:

```sh
python3 scripts/install.py apply --org <Org> --app <app-slug> --app-id <app-id>
```

It reads the organisation's repositories and what each one is (detection, each pack's `detect`), and opens **one pull request** in `<Org>/.github` (creating it, public, when it is missing) with:

| File | What |
| --- | --- |
| `org.yml` | The organisation and its App. |
| `repos.yml` | Every repository and its kinds, from detection: correct what it got wrong before merging. In `repro:`, for each repository that declares no way to reproduce a bug (neither its kind's pack nor its own `.github/review-policy.yml`), the way its stack proposes ([`policy/repro-stacks.yml`](../policy/repro-stacks.yml): PHPUnit, pytest, `dotnet test`, Go, Vitest or Jest, each writing the JUnit report the verdict reads, #377); one no stack is recognised in is named in the output, to declare by hand. |
| `.github/workflows/org-pull-request.yml` | The pull request pipeline every repository runs (conventions, review, auto-merge), calling the engine; each `secrets: inherit` written out as the secrets the called workflow asks for, since `inherit` does not cross organisations (one to a workflow that declares none stays: see the limits below). |
| `workflow-templates/` | The callers a repository adds from *Actions, New workflow*. |

What it leaves out keeps the engine's default: `policy/` (the review and autonomy policies), `labels.yml`, `kinds/`. A YAML file the organisation adds to its `.github` overrides only the keys it sets (#568): every other key stays the engine's, and so does every key a later release of the engine adds. A mapping merges key by key, a value or a list replaces the engine's, but an `add-only` list (`constitution`, `person-merges`) only adds to it, so no engine safeguard is dropped; `labels.yml` merges by label name; `repos.yml` and any file that is not YAML replace the engine's whole; a kind it adds joins the engine's. The merged autonomy policy must pass `autonomy.py check`, or every run stops. Every setting, its default, who may change it and how far, is in [the configuration reference](configuration.md); `scripts/settings.py explain FILE KEY --org FILE` says which level a value in force comes from.

For example, an organisation `Acme` whose reproduced bugs wait for a person's `accepted`, and whose people's issues merge on their own only when the review rates them low risk, up to medium in a repository that asks, writes only this in `Acme/.github/policy/autonomy.yml`:

```yaml
lanes:
  bugfix-reproduced:
    accept: human
  human-issue:
    merge: {max-risk: low}
    ceiling: {max-risk: medium}
```

A repository of Acme raises it in its own `.github/autonomy.yml` (`lanes: {human-issue: {merge: {max-risk: medium}}}`); past Acme's `ceiling`, Acme's ceiling applies, with a warning. Every other setting is the engine's (`tests/workflows/test_settings_acme.py` runs this).

Then, what no pull request can do (the installer prints it with each URL):

1. Organisation secrets: `DILUX_BOT_PRIVATE_KEY` (its App's key) and the Claude token.
2. Organisation variables: `DILUX_BOT_CLIENT_ID` (its App's client ID), and `DX_BOT_LOGIN`, `DX_BOT_APP` and `DX_BOT_ID` (its App's login, slug and bot user id), so the workflows recognise its App; no workflow names one, and a workflow that reads them stops while one is unset ([workflows](workflows.md#organisation-secrets-and-variables)).
3. An organisation ruleset requiring `<Org>/.github/.github/workflows/org-pull-request.yml` on every repository's default branch.

## Optional: private runners and the merge queue

- **Private runners.** Not required. Without the organisation variable `DX_RUNNER_HEAVY` every job runs on GitHub's runners: free in a public repository, from the plan's minutes in a private one. To run a private repository's jobs on runners of its own, register them in a runner group with the label the variable names and set `DX_RUNNER_HEAVY` to their labels as JSON (DiluxOne's: `["self-hosted","linux","x64","diluxone"]`, [workflows](workflows.md#organisation-secrets-and-variables)), visible to the private repositories only. The reproduction, the release and the autopilot's work on a reproduced bug always stay on GitHub's runners.
- **The merge queue** (#451). `org.yml` `merge-queue: auto | on | off` (auto when unset) and a repository's exception in `repos.yml` `merge-queue`; `scripts/sync-repos.py merge-queue` applies it. `auto` turns it on wherever GitHub gives one: every public repository of an organisation, and a private one only on GitHub Enterprise Cloud (GitHub refuses the rule in a private repository on Team or Free); the others are left ready (`DX_MERGE_QUEUE=off`) for the day it is allowed. Where it is on, a pull request runs the fast checks, the queue's group runs the slow suites, and the bot queues instead of merging.

## Known limits

- **Environment secrets across organisations.** A release that publishes with its environment's secrets (a WordPress plugin's `wordpress-org`: the SVN credentials and the release App's key) receives them only through `secrets: inherit`, which GitHub honours within one organisation. Its callers keep `inherit`, so from another organisation those secrets may not arrive: until the engine declares them, publishing a plugin to wordpress.org from another organisation is not supported.

- **GitHub Free.** Organisation rulesets need GitHub Team, so on Free nothing can require the pipeline of every repository: each repository adds it as its own `.github/workflows/pull-request.yml`, a copy of the organisation's `org-pull-request.yml`, and protects its default branch on its own.

## Install again

`install.py diff --org <Org> --app <app-slug> --app-id <app-id> --dir <checkout of Org/.github>` says what installing again would change, touching nothing. Nothing that is there is replaced: a file that exists is kept, and a repository `repos.yml` lacks is added. DiluxOne, whose configuration is this repository's own, comes out with nothing to change: installing again loses nothing (`install.py --test` holds it). For the same reason the organisation's copy of the pipeline and of the templates never follows the engine on its own, and `diff` does not report it: to take a newer one, delete that file and install again. A run while the installer's pull request is open builds on it; one after it was merged or closed starts again from the default branch.
