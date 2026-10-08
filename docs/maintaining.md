# Maintaining this repository

For whoever changes `DiluxOne/.github`: what the tokens may do, and how a change ships to every repository.

Every place the bot's token is minted asks only for what that job does: the review, the replies and the triage get `contents: read` while the model runs; `contents: write` is minted only by the merge, the reproduction push, the weekly learnings, and the step that resolves review threads after the model has finished (resolving a thread is a write on the repository), which nothing that read the pull request's text ever holds. Tags are not creatable by `dilux-bot` at all: the ruleset an adopting repository sets at step 3 allows `X.Y.Z` tag creation to administrators and the release App only, and this repository's `v*` tags (the moving `v5`, the frozen `v4`, `v3`, `v2` and `v1`) can be created, moved or deleted only by administrators (ruleset `moving tags`: creation, update, deletion). The wordpress.org credentials live in the repository environment `wordpress-org`, whose deployment policy admits only `X.Y.Z` tags and `main`, so no pull request or branch job can read them; the check `svn-auth-check.yml` runs inside that environment.

Almost everything here is high risk, and a human merges it. A change that touches only the pages people read (`README.md`, the Markdown of `profile/`, and `docs/` except what agents and the review read as rules: `docs/agents.md`, `docs/architecture.md`, `docs/testing-and-quality.md`) can merge on its own under the usual conditions; [`.github/review-policy.yml`](../.github/review-policy.yml) lists the rest, and `policy.py --test` fails when a file is in no list. After merging, move
`v5` (or cut `v6` for a breaking change: `scripts/next-version.py --tag-prefix v`
says which) and tag the exact version. Moving `v5` also ships the review
profiles, the packs, the default policy and the organisation's required
workflow, which every repository on `v5` reads from that tag. A run that
already exists keeps the workflow it was created with: re-running a failed
job after `v5` moved re-runs the old workflow. Reopen the pull request, or
push to it, for a run on the new one. `v4`, `v3`, `v2` and `v1` stay where
they are.
