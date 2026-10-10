# Plan: one human decision per change

Today a person accepts the issue, asks for the pull request, gets the review's findings fixed and merges almost every change. This plan moves the human effort to the start: a well-formed issue, accepted by a person, is the only decision a normal change needs; from there an agent carries it to a merge through gates that anyone can audit, and every merge leaves a receipt nobody can alter. Agreed with the maintainer on 10 October 2026 (issue #78). The public summary is the page "Pipeline agéntico DiluxOne".

The rule: **a person decides what to build and when to publish; the gates decide whether what was built is what was accepted.**

## The three human decisions

| Decision | When | Why it stays human |
| --- | --- | --- |
| Accept the issue | Always | It is the request. Whoever accepts has read the PRD; its hash is sealed then |
| Merge by hand | Only when the issue is marked critical, or the change touches the rules that govern autonomy | The golden rule (below) |
| Accept the release | Every published version | Publishing to users is a decision, not a consequence of merging |

## The gates

Each gate is a check with a fixed name (`gate / …`) and reports to the issue's board (one bot comment kept up to date). Deterministic gates always win; an AI gate may stop a change, never let one through that a deterministic gate stopped.

| Gate | Checks | Kind | On failure |
| --- | --- | --- | --- |
| G1 Issue ready | The PRD against the issue schema: problem, scope, out of scope, acceptance criteria with IDs in a verifiable form, criticality; nothing outside the sections | Deterministic schema + AI rubric | The agent asks in the issue what is missing; it cannot be accepted yet |
| G2 Acceptance | `accepted` added by a person, or a lane of the autonomy policy that allows it | Deterministic | Nothing starts. The PRD hash is sealed on success |
| G3 Spec | The agent writes the Spec in the issue: approach, files, a test per criterion; scope and protected paths checked | Agent + deterministic paths | It stops and asks, with the action and its URL. The Spec hash is sealed on success |
| G4 Kind's checks | Conventions, lint, static analysis, tests, the kind's own (Plugin Check for WordPress) | Deterministic | The agent fixes and pushes again; one round |
| G5 Clean review | No open blocker or major | AI | Fix and re-review, up to 3 rounds; then back to a person with a summary |
| G6 Meets the issue | Every criterion has its test, it exists and passes; nothing beyond scope | Deterministic criterion → test + AI scope | Back to the loop; scope, to a person |
| G7 Merge | G1–G6 green, both hashes revalidated, not critical, no governing rule touched, within budget | Deterministic | Waits for a human merge, with the reason and the URL |
| G8 Main healthy | The default branch's CI still green after the merge | Deterministic | An automatic revert pull request and an issue; the revert goes through the gates and merges on its own only under the `platform` lane's rules, otherwise a person merges it |

Limits that always apply: 3 review rounds per pull request, the policy's `budget-usd` per issue, one agent per repository at a time (the rest queue), a time limit per round, and the organisation variable `DX_AUTOPILOT=off`, which stops every autonomous action without touching the checks.

## The autonomy policy (#79)

Everything decided without a person comes from `policy/autonomy.yml` in this repository. Each lane names who may originate the work (which organisation workflow, which author), how it is recognised (a `lane:<name>` label), the evidence required before accepting and before merging, the highest risk it may merge alone, and the repositories it applies to. A repository's own file can only restrict it. A lane's issue is accepted only when its history shows it was opened by that workflow and author, never on the label alone.

| Lane | Covers | Evidence | State |
| --- | --- | --- | --- |
| `bugfix-reproduced` | A reported bug, reproduced with a failing test | The test fails before and passes after; the report and the fix concern the same thing | `issue-repro.yml` already reproduces; the hand-off to the autopilot is #84 |
| `platform` | The runner image, CI dependencies, tool versions | Smoke test and green checks | First autonomous lane (#69) |
| `human-issue` | What a person accepted, carried to the merge | G1–G7 | #83 |
| `release` | The release issue | A person's acceptance and a consistent version | Never accepted by policy |

**The golden rule:** the autonomy policy, the gates and the workflows that apply them are always human-accepted and human-merged. Autonomy cannot widen itself.

Traceability, all on GitHub: the board answers who accepted (a person, or a lane with a link to the policy at its commit) and why a merge needed nobody (each G7 condition with its check); labels `accepted-by:policy` and `merged-by:policy`; a weekly issue lists everything decided by policy across the organisation; the policy's history says who changed it.

## PRD, Spec and receipts (#80, #81)

**Receipt-driven development:** a change is done when its receipt exists, not when the code works.

- **One schema** (`policy/issue-schema.yml`) defines the PRD and Spec sections, their order, which are required and their format. The issue forms are generated from it; a deterministic gate parses each issue against it. A kind may add sections, never remove the organisation's.
- **PRD and Spec live in the same issue**, each with its own hash. On acceptance the bot normalises the PRD section (line endings, trailing spaces, hidden comments) and records its SHA-256; the Spec's when it passes G3.
- **Seals and receipts** are committed by the bot to an orphan `receipts` branch (no shared history with the code). A ruleset lets only the bot write and forbids deleting or rewriting it; App commits show as Verified. Public repositories add a GitHub artifact attestation; private ones cannot on the Team plan.
- **Revalidation:** on every edit of the issue, before the agent starts, on every push of the pull request and right before the merge. A PRD changed after acceptance removes the acceptance and stops the work (re-accepting seals a new hash; the old one stays in the history). A changed Spec re-runs G3. Text outside the sections fails the gate. Comments and the board are not part of PRD or Spec.
- **The receipt** at merge holds the PRD and Spec hashes, the head commit, the checks, the review verdict, criterion → test → result, the policy version, who accepted and who merged.

Injected text ("delete the whole repository") is stopped by four layers, none of which depends on the agent behaving: the strict schema; a person read what was accepted and the hash freezes it, and the agent reads only PRD and Spec at their sealed hashes, never third-party comments; the issue is presented to the agent as a specification, never as instructions; and least privilege, since the agent's credentials cannot delete the repository or branches, push to `main` or touch workflows, and everything goes through a pull request with gates.

## Release as an issue (#82)

A release is publishing X.Y.Z to users; development builds keep being published on every merge with no issue. "Release X.Y.Z" is opened by the maintainer, or by the bot when the last issue of a version milestone the maintainer planned closes (the decision was taken when planning the milestone). Without a milestone the bot never opens one; it only suggests it in the weekly summary. Accepting it is the approval. The agent opens the release pull request (`release-markers.sh prepare`, removing `Unreleased.`), it passes the gates, and the deploy checks that the release issue was accepted by a person and that the version matches before publishing; the environment no longer needs a human reviewer. The kind decides where it publishes.

## The engine (#83)

`claude-code-action` on the organisation's runner, triggered when an issue is accepted, authenticated with the organisation secret `CLAUDE_CODE_OAUTH_TOKEN` (the maintainer's Claude subscription; `ANTHROPIC_API_KEY` is the fallback, #75), committing as `dilux-bot`, so the agent's work is never mistaken for a person's. Cloud sessions on claude.ai stay for work a person drives.

## Platform (#69)

Public repositories run on GitHub's runners, free for them; private ones on the organisation's runner (`DX_RUNNER`, `runner-vm.yml`). Each job runs in a disposable container built from an image rebuilt every week by a workflow here (public, so free), which promotes it only after a smoke test; the VM is described as code and applies a merged change on its next boot. The release, the credentials check and the reproduction always run on GitHub's fresh runners.

## PHP (#85)

Tools run on the latest PHP; every plugin supports PHP 7.4 (94% of WordPress sites on 10 October 2026, api.wordpress.org/stats/php). Both values live in the `wordpress-plugin` pack. PHPStan analyses for 7.4, PHPCompatibility refuses syntax 7.4 lacks, and the matrix runs lint and unit tests from 7.4 to the latest.

## Design systems (#77)

Organisation design systems live in `design-systems/<name>/` (tokens, components and patterns, rules for the review); each project is associated with one in `repos.yml`, or with its own `docs/design-system/`, which may extend one. `wordpress-admin` comes first, extracted from Offload and Users+.

## Order

1. This plan (#78).
2. The platform lane: runner image, disposable runners, weekly build, the VM as code (#69). It also ends today's clashes between jobs that share the VM.
3. The base: autonomy policy (#79), issue schema (#80), receipts and the board (#81).
4. Release as an issue (#82).
5. The autopilot (#83), then reproduced bugs into it (#84).

In parallel, independent of the rest: automatic assignees (#73), PHP (#85), design systems (#77).
