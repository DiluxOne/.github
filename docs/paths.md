# The paths and the scenarios that play them

Every path [the agentic model](model.md) describes, and every setting that changes one, with the release scenarios of [`tests/release/scenarios.yml`](../tests/release/scenarios.yml) that play it in the test repository before `v7` moves ([docs/versioning.md](versioning.md)). The scenarios also cover each workflow event and each transition of the autopilot one by one; this table is how they add up to the paths, so a combination that breaks fails the release lane instead of reaching people (#696).

[`scripts/release-scenarios.py`](../scripts/release-scenarios.py) `paths` holds the table to the file, in `coverage` (the scripts job) and in `--test`: every path and setting it requires has its row, every row names at least one scenario (each in backticks, in the second column), and every scenario named exists. A path or a setting added to the model adds its row here and its name to the script's `PATHS`, in the same pull request.

| Path or setting | Scenarios | How |
| --- | --- | --- |
| a person's bug to its merge | `bug-by-person-merges`, `bug-not-reproduced`, `low-risk-merges`, `merge-queue` | A bug no reproduction confirmed, accepted by a maintainer and worked by the autopilot to its pull request; the merge on its own and through the queue are played on pull requests of their own, since the test repository's review is a model's. |
| a reproduced bug merged by policy | `bug-reproduced` | The reproduction confirms it and its lane opens the fix's issue, accepted by policy; the review's fix round is held by `scripts/autopilot.py --test` (`statically:` in the scenarios' file). |
| a feature accepted and built | `accepted-spec`, `spec-to-draft`, `core-one-at-a-time` | Accepted after its triage, sealed, its Spec, its draft and every box ticked; a second change to the same core waits for the first. |
| a claim and its release | `claim-and-release`, `claim-pull-request` | `/claim` before the acceptance, the autopilot steps aside, `/unclaim` releases it; a claimant's own pull request. |
| a stop answered | `stop-answered`, `stop-hint-continue`, `question-answered` | The fixed Spec stops on the pack's question (`fixed-change.ask`); an answer in a comment alone brings it back and it does not ask again, as does a hint with `autopilot:continue`, and an answer to the autopilot's question. |
| an edit after acceptance and the new acceptance | `prd-edited-after-acceptance`, `stop-edited-reaccepted-answered` | G2 takes `accepted` off an edited PRD; after a stop, an edit, a decider's answer and a new acceptance, it goes on with no `autopilot:continue`, with one stop. |
| the release and its watch | `release-issue` | A release issue accepted by someone who may not approve one is refused. The release lane's own watch of the adopted repositories after `v7` moves runs in no test repository: `scripts/release-lane.py --test` holds it. |
| acceptance by policy | `bug-reproduced`, `decision-sub-issues` | The `bugfix-reproduced` lane accepts the fix's issue; a decision that names only the test repository is accepted and sealed. |
| `who-decides` | `question-answered`, `stop-answered`, `stop-edited-reaccepted-answered` | The test identity decides only in the test repository (its pack's `identity`): its answers bring the autopilot back and reach its prompt. |
| a claim | `claim-and-release`, `claim-pull-request` | A claimed issue is not the autopilot's until it is released. |
| merge on its own or by a person | `low-risk-merges`, `merge-queue`, `high-risk-waits` | A low-risk change merges on its own, through the merge queue; a high-risk one waits for a person. |
| its `ceiling` | `high-risk-waits`, `fork-without-secrets` | Past what the policy lets merge on its own, a person merges; a fork's change runs with no secrets and does not merge. |
