# Review profile: the engine's test repository (kind `engine-test`)

For the organisation's test repository (org.yml `test-repo`, #563), where
the release lane plays the scenarios of `tests/release/scenarios.yml` before
`v7` moves. Its pull requests are opened by the scenarios with a fixed
change that calls no model, and closed after each run: what is reviewed is
the flow, never the code.

- **Nothing is published from it.** A release, a tag, a catalog entry or a
  deploy in a pull request here is a blocker.
- **No secret in a scenario.** A scenario's text is data: a token, a key or
  a credential in a file it writes is a blocker.
- **The fork scenario runs without secrets.** A change that gives a pull
  request from a fork a secret, or `pull_request_target` with its code, is
  a blocker.
- **The fixed change matches its description by construction.** A pull
  request of the fixed change (one marker file per criterion under the
  pack's `fixed-change.file`, written with no model) is not judged as a real
  fix: the review judges the flow, not whether the marker "fixes" the PRD's
  bug, and sets `description_matches` true for it. G7 does not hold such a
  pull request on the description either (#887). Nor are its criteria
  judged as a real fix's: a marker with no assertion is what the fixed
  change writes, not a stub, so the review sets each of its criteria
  `met: true`, and G7 does not hold it on the criteria verdict either
  (#894).
