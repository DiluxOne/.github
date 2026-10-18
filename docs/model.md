# The agentic model

How work moves from an issue to a release in an organisation that runs on these workflows: who decides, what an agent does on its own, and what stops it. It holds for any kind of project; what one organisation or one kind of project sets lives in its data (`repos.yml`, `policy/`, `kinds/`), not here. An agent reads this from the link in its repository's `AGENTS.md`; the rules every change meets are in [`rules/`](../rules/README.md).

Not all of it is built yet. What is, and in which order the rest comes, is the work plan: [docs/plans/autonomy.md](plans/autonomy.md).

## In one paragraph

For a normal change, the only human decision is accepting a well-formed issue; from there it travels on its own to the merge, through gates that leave a record. A person still decides four things: accepting an issue, accepting an organisation decision (once, for every repository), merging what the policy leaves to a person (high risk, Critical, a security fix, the autonomy policy and the rules) and publishing a version.

## Four doors in

Work comes in through four doors: an issue, an organisation decision, the maintenance schedule and a private security report. All of them go through the same gates and end, depending on the kind of project, in Unreleased or in production.

## Five types of work

Five types are enough; everything else (refactor, docs, performance, hotfix, migration) falls inside one of them. What makes the process heavier or lighter is the risk, not the label.

| Type | When | Process | Who decides | Merges on its own |
| --- | --- | --- | --- | --- |
| Maintenance | Dependencies (majors included), the runner image, the organisation's templates and files | The kind's checks | Nobody: the rule is accepted once | Yes, on a schedule |
| Minor | The change fits in one sentence and does not change behaviour: text, a button, docs, a small refactor, a revert | Code, checks, review | A maintainer accepts the issue | Yes |
| Bugfix | Something behaves differently from what is expected, a performance regression included | A test that reproduces it, a test of what must not change, code, review, validation | The policy, if the bug was reproduced on its own; otherwise a maintainer | Up to medium risk |
| Feature | Something new, a public API or hook, a migration, a deprecation, a breaking change | PRD, impact, threats, architecture, code, review, independent validation | A maintainer accepts the PRD | Up to medium risk |
| Security | A vulnerability reported privately | In a public repository, a private advisory, never a public issue; in a private one, an issue labelled `security` | A maintainer | No: a person merges the fix |

**Not a type:** a spike produces no pull request. It is a step of the triage, when an issue cannot be classified or a maintainer asks for one: the agent investigates read-only, for a capped time, and ends in doing (the issue becomes a bug, a minor change or a feature), clarifying (it asks what is missing) or discarding (it closes with the reason). Release has its own flow.

**Escalation.** A minor change or a bugfix becomes a feature when it touches anything on its kind's risk list: permissions and authentication, stored data or its schema, public hooks or APIs, payments, data deletion. Deterministic code detects it, not the AI. Going up is automatic and stated in the issue; going down is a maintainer's call.

## Bugs, from report to fix

1. **Triage.** Anyone opens an issue. The triage classifies it: bug, product request, question, duplicate or security.
2. **Reproduction.** An agent writes a failing test, in a sandbox with no network and no secrets. If it cannot reproduce it, it says what it tried and what it is missing.
3. **Acceptance by policy.** A reproduced bug's fix is accepted by a lane of the policy, without a word of the original report: the test is the specification.
4. **Fix.** The autopilot makes the test pass, adds the test of what must not change, and passes every gate.
5. **Merge.** Up to medium risk it merges on its own, into Unreleased (or into production, for a continuous kind).
6. **Publish.** A maintainer decides when, by accepting a release issue.

The agent stops and asks a person when the fix contradicts documented behaviour, when the test does not pass in three rounds, or when it touches the risk list. When it must choose between two reasonable behaviours, the organisation's `autopilot-mode` decides (policy/autonomy.yml, and a repository's own file up to its ceiling): `guided`, the default, asks a maintainer, with the options and its recommendation, and goes on with their answer, written in their own words; `full` picks one, logs it on the pull request, and stops only when it is stuck. Asking is a comment with options, not a new issue.

## Product requests: minor or feature

A maintainer accepts the PRD, and from there the work is autonomous; a feature only carries more sections, in the same issue and the same pull request.

| Phase | Minor | Feature |
| --- | --- | --- |
| PRD with verifiable criteria and no open doubts (G1) | Short | Complete |
| Impact: what it touches, what can break | - | Yes |
| Threats (a short STRIDE), curated by a second AI, or a maintainer when Critical | - | Yes |
| Architecture: where it goes, which pattern it follows | - | Yes |
| Test-first code and the kind's checks (G4) | Yes | Yes |
| Review (G5) | Yes | Yes |
| Validation by an agent that did not write the code (G6) | Yes | Yes, also against impact and threats |

With more than 5 to 7 criteria, or more than 2 or 3 modules, the work is split into sub-issues. A failed validation sends the change back to the code; nothing is patched in the validation. A request from outside is at least a bugfix or a feature, never minor.

## Doubts

Doubts are settled before acceptance whenever possible: the PRD marks each with `[Doubt: …]`, and it cannot be accepted while one is left. After acceptance:

| The doubt | Who decides | Where it stays |
| --- | --- | --- |
| How, without contradicting the PRD | The agent, following the repository's conventions | The pull request's decision log |
| It changes the scope or a criterion | A maintainer | An amendment to the PRD, accepted again |
| It is bigger than it seemed | A maintainer: full PRD, go on, or split | The issue |

What the agent finds along the way never silently widens what was authorised: a finding the task does not need goes in a list for the maintainer, not into the change and not into a new issue.

## Gates

A change moves only if it passes each gate in order. The deterministic gates always win; the AI can stop one, never skip one.

| Gate | What it verifies | If it fails |
| --- | --- | --- |
| G1 Issue ready | Problem, scope, out of scope, verifiable criteria, the tests that prove them, criticality | It cannot be accepted; the agent asks for what is missing |
| G2 Acceptance | `accepted` from a person, or a lane of the policy | Nothing starts |
| G3 Plan | Files, approach and tests before code; in scope, no protected path | It asks the maintainer, with the action and its URL |
| G4 The kind's checks | Conventions, lint, static analysis, tests | The agent fixes and pushes again (a round) |
| G5 Clean review | No open blocker or major | The agent fixes; after 3 rounds, a person |
| G6 Meets the issue | Every criterion with its evidence, nothing out of scope | Back to the loop; a scope problem goes to a person |
| G7 Merge | G1 to G6 green, not Critical, not labelled `security`, no protected path, within budget | A person merges, with the reason and the URL |
| G8 Healthy main | The default branch's CI green after the merge | An automatic revert pull request and an issue |

Limits that always cut: rounds per pull request (3), runs per issue (5), what one agent's run may cost (`budgets-usd`), how many strangers' reports are reproduced a day and by one author, the agent's jobs in parallel, and an organisation switch (`DX_AUTOPILOT=off`) that stops everything autonomous without touching code, a planned release's approval by policy included.

## What merges on its own

| What | On its own | A maintainer |
| --- | --- | --- |
| Maintenance | Always, within its lanes | Only if a gate fails |
| Product changes and organisation decisions | Low and medium risk | High risk, an issue marked Critical, or a security fix |
| The autonomy policy, the gates, the workflows that apply them, and the rules | Never | Always |
| Publishing a version | Never | Always |
| Reverting what broke the default branch | Within its lane | The rest |

The review sets the risk, and a pull request cannot lower it: the high-risk paths are in the organisation's policy and in each repository's.

**The golden rule:** autonomy cannot widen itself. The autonomy policy and the rules always need a person to accept and merge them.

## The autonomy policy and its lanes

Everything decided without a maintainer comes from one file, `policy/autonomy.yml`. A repository can restrict it freely, or widen it only up to the ceiling the organisation sets. Each lane is a named entry, and nothing is accepted on its own unless it fits one: it says who can originate it (which workflow, which author), how it is recognised (a `lane:<name>` label, or, for a sub-issue of an issue a person accepted, its parent), what evidence it demands, up to which risk it merges on its own and in which repositories.

The gate ignores any label a bot adds, except a lane's label, and that only when the issue's history shows it was opened by the workflow and the author the lane names. A sub-issue needs no label: it is accepted while its parent stays open and accepted by a person, if a member of the organisation opened it and did not edit it after linking it.

## Where each rule lives

Three layers: the organisation (its `.github` repository), the kind, the repository. What is below adds or restricts; it never loosens what is above, except up to the ceiling the organisation sets.

| What | Organisation | Kind | Repository |
| --- | --- | --- | --- |
| Autonomy: lanes, thresholds, majors, what a person always merges (`person-merges`, security) | `policy/autonomy.yml` | - | Its policy file: restricts, or widens up to the ceiling |
| Gates and workflows | The central workflows | The kind's checks | The callers the sync copies |
| Mandatory rules | `rules/` | `kinds/<kind>/` | `AGENTS.md`: only adds |
| Conventions | This page and the `AGENTS.md` block the sync copies | `kinds/<kind>/` | `AGENTS.md`, under the block |
| Repositories and kinds | `repos.yml` | `kind.yml` | - |

**Rules.** One file per rule in `rules/`, with a header that declares its `level` (`mandatory`, never left out; `standard`, left out by a repository only with a reason a maintainer merges), what it `applies_to` (everything, a kind, or a role such as `front` or `back`) and how it is `enforced_by` (a deterministic check, the review, or both). Each repository declares the roles of its paths, so the rules that reach it are only those that apply, and the review uses those of the paths a change touches.

## Any kind of project

What changes between a plugin, a site, a library or a monorepo lives in a pack, the kind, not in the workflows' code: its checks, its risk list, its public surface, its Dependabot template, its changelog and how it publishes. A repository can have several kinds, each over its own paths; a change runs the checks of the kinds it touches, and the heavier process wins.

Each kind declares its release mode. **Versioned** (plugin, library, store app): merges pile up in Unreleased, and publishing is a release issue a maintainer accepts. **Continuous** (web, API, service): the merge deploys with gradual rollout and automatic rollback, and what is risky goes in behind a flag a maintainer turns on.

A repository is classified in `repos.yml`. Detection proposes a kind by pull request; a person accepts it. An unclassified repository gets triage and basic checks, and nothing merges on its own there.

## Organisation decisions

A decision for many repositories is one issue, accepted once. It states its scope as a filter over data (the kind, the attributes in `repos.yml`, what the repository contains), and a job resolves it into one sub-issue per repository, accepted by policy. A decision that must hold over time becomes a maintenance rule, enforced every day by the drift check.

## Traceability

Any automatic decision is answered in three clicks: the issue's board says what was decided, the rule says why, and the rule's commit says since when. The board is one comment the bot keeps up to date, a row per gate, with the result, who or which rule, and the link. A weekly issue lists everything accepted and merged by policy in the organisation, and what needed a person and why.

**PRD, Spec and receipts.** The issue carries the PRD, frozen by its hash when accepted, and the Spec, frozen when G3 passes; an edit after either is detected and needs acceptance again. On merge, the organisation's App commits a receipt (both hashes, the pull request, its checks, the review's verdict, who accepted and who merged) to the repository's `receipts` branch, which only the App can write.

## Text in issues is data

The agent reads text anyone can write. No layer depends on the agent behaving well:

1. The issue has exactly its form's headings; loose text fails the gate.
2. The maintainer reads the PRD before accepting, and the hash freezes it; the agent reads the PRD and the Spec at those hashes, never third parties' comments.
3. The prompt presents the issue as a specification, never as instructions.
4. The agent that can run commands holds no key and its token writes nothing: what it would do on GitHub, a separate job that runs no agent does, within a fixed list of actions (push onto its pull request's branch, never a workflow; tick, decide, ask, stop, reply), and everything goes through a pull request with gates.
5. A reproduction runs in a sandbox with no network and no secrets.
6. A reproduced bug's fix is accepted without the original report.
7. The AI can only stop a gate, never skip one.

## Learnings

The system learns from its receipts but does not change itself. The receipt records the findings (rounds, what the review flagged, escalations, reverts); a scheduled job finds what repeats (how often, and over how long, the policy sets) and opens a pull request to the rule it belongs to, with the receipts as evidence. A person decides; a closed proposal is recorded and not made again.

## Release

A release publishes an X.Y.Z version for users; development builds come out on their own. Publishing is a maintainer's decision, taken by accepting a "Release X.Y.Z" issue, which a maintainer opens, or the bot opens when every issue of a version's milestone is closed. Planning is deciding too: with the organisation's `planned-release: auto`, a milestone a maintainer planned is accepted when it is done, as that maintainer's decision; with `confirm`, accepting the issue is the last click. The organisation runs `confirm` until a planned release is bound to its plan (#287), and always while `DX_AUTOPILOT` is off. Once accepted, the agent opens the release pull request, it passes the gates and merges once its tree is proved to be exactly the release command's (no second approval: the decision was the acceptance), and the publishing job checks that the issue was accepted and that the version matches.

A **security patch** (#247, #287) is approved by a maintainer too, the one release that needs a click of its own. A private report that is reproduced and fixed in private becomes a patch on the version in production (the highest published release, checked against where the kind publishes it), holding only the fix, within the policy's limits of size and paths. The repository's checks run on it and a second model, which never sees the report, reviews it; the maintainers are told, with the patch's tree, and it publishes only when one of them adds `patch:go`. Everything up to then runs in private; a separate App, whose key lives only in the private repository, then pushes the patch to be released and publishes the advisory, and the fix is carried into the default branch on its own: a pull request of the `security-carry` lane cherry-picks it as it was released and merges while its commits are exactly that fix. Until it merges, no release goes out from the default branch (the carry lock), so a release never brings the vulnerability back.
