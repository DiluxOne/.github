# Installing the engine in another organisation

The engine is DiluxOne's; the configuration is the organisation's ([phase 12](plans/autonomy.md#phase-12--setup-for-other-organisations), #197). Another organisation never copies the workflows, scripts or gates: its callers name them by tag (`uses: DiluxOne/.github/.github/workflows/<name>.yml@v6`), and every run lays the organisation's own `.github` repository over the engine's defaults ([`scripts/config-overlay.sh`](../scripts/config-overlay.sh)). An improvement to the engine reaches it when the major tag moves; a breaking one comes in a new major, with its migration notes ([versioning](versioning.md)).

## What the organisation needs first

- **Its own App**, made by an administrator of the organisation and installed on every repository: Contents, Issues, Pull requests, Actions and Checks (read and write), Metadata (read). DiluxOne's App and its key never leave DiluxOne.
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
| `repos.yml` | Every repository and its kinds, from detection: correct what it got wrong before merging. |
| `.github/workflows/org-pull-request.yml` | The pull request pipeline every repository runs (conventions, review, auto-merge), calling the engine; each `secrets: inherit` written out as the secrets the called workflow asks for, since `inherit` does not cross organisations. |
| `workflow-templates/` | The callers a repository adds from *Actions, New workflow*. |

What it leaves out keeps the engine's default: `policy/` (the review and autonomy policies), `labels.yml`, `kinds/`. The organisation adds any of them to its `.github`, whole files, when it wants its own; a kind it adds joins the engine's.

Then, what no pull request can do (the installer prints it with each URL):

1. Organisation secrets: `DILUX_BOT_PRIVATE_KEY` (its App's key) and the Claude token.
2. Organisation variables: `DILUX_BOT_CLIENT_ID` (its App's client ID), and `DX_BOT_LOGIN`, `DX_BOT_APP` and `DX_BOT_ID` (its App's login, slug and bot user id), so the workflows recognise its App where they would recognise dilux-bot ([workflows](workflows.md#organisation-secrets-and-variables)).
3. An organisation ruleset requiring `<Org>/.github/.github/workflows/org-pull-request.yml` on every repository's default branch.

## Install again

`install.py diff --org <Org> --app <app-slug> --app-id <app-id> --dir <checkout of Org/.github>` says what installing again would change, touching nothing. Nothing that is there is replaced: a file that exists is kept, and a repository `repos.yml` lacks is added. DiluxOne, whose configuration is this repository's own, comes out with nothing to change: installing again loses nothing (`install.py --test` holds it).
