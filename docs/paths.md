# The paths and their scenarios

Every path [the model](model.md) describes, from an issue to its merge or its release, and every setting that changes one, played whole by the release lane in the test repository: each row names the scenarios of [`tests/release/scenarios.yml`](../tests/release/scenarios.yml) that play it ([versioning](versioning.md), "How a version is made"). A combination that breaks fails the lane before `v7` moves, instead of reaching people (#696).

`release-scenarios.py coverage` (the scripts job) and its `--test` fail when a path or a setting below has no row, when a row names no scenario, or when it names one that is not in the file (`paths`); the list of rows it asks for is in the script, from the model.

| Path or setting | Scenarios |
| --- | --- |
| A person's bug to its merge | `bug-by-person-merges` |
| A reproduced bug merged by policy | `bug-reproduced` |
| A feature accepted and built | `accepted-spec`, `spec-to-draft` |
| A claim and its release | `claim-and-release`, `claim-pull-request` |
| A stop answered | `stop-answered`, `stop-hint-continue`, `question-answered` |
| An edit after acceptance and the new acceptance | `prd-edited-after-acceptance`, `stop-edited-reaccepted-answered` |
| The release and its watch | `release-issue` |
| Acceptance by policy | `bug-reproduced`, `decision-sub-issues` |
| `who-decides` | `stop-answered`, `stop-edited-reaccepted-answered`, `question-answered` |
| A claim | `claim-and-release`, `claim-pull-request` |
| Merge on its own or by a person | `low-risk-merges`, `merge-queue`, `high-risk-waits`, `bug-by-person-merges` |
| Its `ceiling` | `high-risk-waits` |
| The flow with no label by hand | `marker-g1-start`, `conventions-fix`, `hint-no-needs-human`, `settled-rerun` |

What each row plays:

- **A person's bug to its merge**: a bug the reproduction did not confirm, so no lane takes it, which a maintainer accepts; the autopilot's fix merges and closes it.
- **A reproduced bug merged by policy**: the reproduction confirms it, and the `bugfix-reproduced` lane opens its own issue and fixes it.
- **A feature accepted and built**: accepted after its triage, sealed, its Spec written and its draft worked to ready.
- **A claim and its release**: `/claim` before the acceptance, so the autopilot steps aside, then `/unclaim`; and a claimant's own pull request.
- **A stop answered**: the Spec stops (the test repository's fixed change asks on its pack's `fixed-change.ask` phrase), and an answer in a comment alone brings it back; with a hint and `autopilot:continue`; and a question answered.
- **An edit after acceptance and the new acceptance**: G2 withdraws the acceptance; and, after a stop, the edit, an answer by someone who decides and the new acceptance, after which it goes on with no `autopilot:continue` and asks nothing again.
- **The release and its watch**: a release issue the test identity may not approve gets its refusal. The engine's own watch after a release (`release-lane.py watch`) is no test-repository scenario: `release-lane.py --test` holds it.
- **Acceptance by policy**: the reproduction's lane, and a decision's sub-issue accepted by its parent.
- **`who-decides`**: the test identity decides there (its pack's `identity`), so its answer brings the autopilot back.
- **A claim**: as its path above.
- **Merge on its own or by a person**: a low-risk change merges on its own, through the merge queue too; a high-risk one waits for a person.
- **Its `ceiling`**: a change past the risk the policy lets merge on its own (`high-risk-waits`, its path high for kind engine-test) waits for a person.
- **The flow with no label by hand** (#699): an issue with the release lane's mark before its first section passes G1 and the autopilot's start alike; a failed conventions check on the autopilot's pull request starts its fix round, which gives the title back; a hint of someone who decides on one that waits on the autopilot brings it back with no `needs-human`; an answer that settles a review finding runs the review again on the same head. Each moves no label by hand but the acceptance (`hands`), and the file's `flows:` lists them, so one with no scenario fails `coverage`. An edit that makes a refused issue pass (C2) and the release lane's own bug (C6) are no test-repository scenario: `statically:` names the tests that hold them.
