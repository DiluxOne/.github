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
