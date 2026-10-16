# DiluxOne: the agentic model

The work plan is the parent issue [#184](https://github.com/DiluxOne/.github/issues/184) and its sub-issues, one per phase; this file describes the model they build.

As of 2026-10-15

For a normal change, the only human decision becomes accepting a well-formed issue; from there it travels on its own to the merge, through verifiable gates that leave a record. A person still decides what is high risk or critical, an organisation decision (once, for every repository) and each release.

**Update v2 (2026-10-15):** on 2026-10-15 one decision ended in 33 `accepted` labels added by hand. This part orders the model by decision, not by repository, and by type of change.

## Work plan

For the team of the central repository (`.github`). Each phase is a sub-issue of a parent issue, "Agentic model: work plan", that a maintainer accepts and that replaces #78 (all of its parts are closed). A phase starts when the phases it depends on are done; phases that do not depend on each other can run in parallel. What the plan calls "today" comes from the review of `.github` on 2026-10-15, corrected against the repository the same afternoon. Before starting a phase, whoever takes it confirms the real state and writes it in its sub-issue.

**Before starting**

- Close #78 and create the parent issue and one sub-issue per phase, copying from this section what it delivers, when it is done and what it depends on.
- The queue #156 to #180 was reviewed on 2026-10-15: everything is merged or closed except #179, which moves to phase 4.
- The VM stays as it is.
- Already done, outside the phases: the PHP policy (#156), the wordpress-admin design system v0 (#151, #168, #169) and automatic assignees (#149).

| Phase | Delivers | Depends on | Absorbs |
| --- | --- | --- | --- |
| 0. Stabilise | Only the organisation turns the VM off; nothing waits more than 15 minutes | - | #183 |
| 1. Medium risk | human-issue merges on its own only up to medium risk | 0 | - |
| 2. The model, written | `docs/model.md`, `rules/` with the first rules, the `AGENTS.md` block | 1 | - |
| 3. The policy base | `policy/autonomy.yml` with a schema, default risk and ceiling, per-repository overrides, protected paths, a view of what is pending | 2 | - |
| 4. Organisation decisions | A decision issue with a repository filter, sub-issues by policy, sync on a schedule | 3 | #179 |
| 5. Platform | Daily image, ephemeral runners, where each job runs | 3 | - |
| 6. Organisation config and several kinds | `repos.yml` and `kinds/` with schemas, roles, release mode, detection, new repositories, code without proper names | 3 | - |
| 7. Release and deploy | Release by milestone, an environment with no approver, continuous deploy with flags | 5, 6 | - |
| 8. Autopilot by type of work | G1, types of work, escalation by kind, feature phases, review loop, G6, auto-merge, disambiguation, spike | 3, 6 | - |
| 9. Security | Private advisory; merge by the policy, with a 4-hour veto | 8 | - |
| 10. Reproduced bugs | A real bug end to end through the lane that already exists | 8 | - |
| 11. Learnings | Findings in the receipt, a weekly job, pull requests with evidence | 8 | - |
| 12. Setup for other organisations | Installer, base kinds, configuration with an agent | 6, 11 | - |

### Phase 0 · Stabilise what runs today

- **Today:** Mail #25 and #23 and Users+ #28 are no longer stuck (two merged, one closed). The real problem is another: another repository sharing the VM turned it off with a daily schedule without checking whether it was in use (on 2026-10-15 it cut jobs at 06:20 UTC), and #183 reports jobs waiting for the VM for more than 15 minutes.
- **Do:** remove that schedule, and have that repository turn the VM off only when no runner is working; find out why the jobs in #183 wait.
- **Done when:** a week goes by with no jobs cut off and no waits over 15 minutes.

### Phase 1 · human-issue up to medium risk

- **Today:** the queue #156 to #180 is closed (only #179 is still open, and it moves to phase 4). The human-issue lane merges on its own up to high risk (`policy/autonomy.yml`, `max-risk: high`), more than the model says.
- **Do:** lower human-issue to `max-risk: medium`.
- **Done when:** a high-risk pull request that comes from human-issue is left for a person to merge.
- **Done:** lowered in #186; the high-risk pull requests of human-issue wait for a person.

### Phase 2 · The model, written

- **Today:** the model lives in a working document; the rules live in the code or in each agent's memory.
- **Delivers:**
  - `docs/model.md`: this model, without the parts specific to DiluxOne.
  - `rules/` with the header schema (`level`, `applies_to`, `enforced_by`) and the first mandatory rules: test-first, and no credentials in the front end.
  - The `AGENTS.md` block the sync copies, with the rule on findings.
- **Done when:** a maintainer merged the three, and an agent in any repository reads them from its `AGENTS.md`.
- **Done:** [docs/model.md](../model.md), [rules/](../../rules/README.md) (held by `scripts/rules.py`) and items 8 and 9 of `agents-block.md`, in #187; the sync brings the block to every repository.

### Phase 3 · The policy base

- **Today:** these already exist: the lanes in `policy/autonomy.yml`, the gate that accepts a lane's label after `autonomy.py` verifies it (and rejects any other bot's), the `accepted-by:policy` and `merged-by:policy` labels, the weekly issue #118 "Decided by policy", `autopilot-rounds: 3` and the `DX_AUTOPILOT` switch. What is below is missing.
- **Delivers:**
  - A schema for `policy/autonomy.yml`, with a default risk (medium) and a ceiling (high), majors on auto, security fixes with a 4-hour veto, a budget per issue, 2 jobs in parallel and 30 minutes per spike.
  - `.github/policy.yml` in each repository, with a check that does not let it pass the organisation's ceiling.
  - Protected paths (`policy/` and `rules/`) in G3 and G7.
  - The issue's board.
  - The view of the organisation's Project filtered by `needs:maintainer`.
- **So far:** a lane's `ceiling` (human-issue: medium by default, high at most), up to which a repository's `.github/autonomy.yml` may raise it; `autonomy.py check` holding the policy to its schema in CI; `rules/**` and `docs/model.md` among the protected paths. The repository's file keeps its name, `.github/autonomy.yml`, not `.github/policy.yml`. Majors, the security veto, the budget, the parallel jobs and the spike's time join the schema with the phase that first reads each, so the policy names nothing that nothing applies.
- **One issue per run:** each build of the runner image and each week's digest opens its own issue (`run:runner-image`, `run:autonomy-digest`, `scripts/run-issue.sh`): closed as completed when the run needs no one, open with `needs:maintainer` when it does; a build that passes settles the failed ones. #93 and #118 close.
- **The board and the view:** a lane's acceptance and a merge by policy link the rule they followed on the issue's board; what waits on a maintainer is one search over the organisation (`needs:maintainer` or `needs-human`), linked from `docs/maintaining.md`, with nothing to build.
- **Done when:** changing a threshold is a pull request to one file; every automatic decision shows on the board with a link to its rule; and `DX_AUTOPILOT=off` stops everything autonomous.

### Phase 4 · Organisation decisions

- **Today:** only the mechanical sync reaches each repository. On 2026-10-15, one decision ended in 33 acceptances by hand.
- **Delivers:**
  - The decision issue, with its scope as a filter over `repos.yml` and what each repository contains.
  - The job that resolves the filter, writes the table of repositories and opens sub-issues accepted by policy.
  - The sync on a schedule, not only the check.
  - Decisions that must hold over time become class 1, watched by the daily drift check.
- **Done when:** an organisation decision is accepted once, and no repository needs an acceptance of its own.
- **So far:** the `delegated` lane (#179): a sub-issue of an issue a person accepted is accepted by policy, while its parent stays open and accepted, if a member opened it and did not edit it after linking it.
- **The sync on a schedule:** `org-drift.yml` runs every day and first brings the labels and the shared files in step as dilux-bot, through the org-sync lane, then checks what is left (#210).
- **The decision issue:** an optional `Repositories` section in the PRD (`all`, `kind:`, `visibility:`, `has:`, `name:`); accepting the issue opens a sub-issue in each repository it selects (`scripts/decision.py`), and the daily run opens one for a repository that matches later. A decision whose rule must keep holding ("always PHP 7.4") still needs its own check in the kind's pack; the daily run only keeps every matching repository with its sub-issue.

### Phase 5 · Platform

- **Today:** the image rebuilds itself every day (#190). Each job already runs in its own container of the image, a one-job runner from a just-in-time configuration (`scripts/runner-vm/dx-runner-slot.sh`), so jobs no longer share the operating system. These are also in place: the VM as code (`scripts/runner-vm/`, #69), the organisation's Dependabot (#180; bringing it to each repository is pending) and the G8 sweep every 15 minutes (#165).
- **Delivers:**
  - A daily image build, with a smoke test and promotion to `stable`.
  - Ephemeral runners, each in its own container.
  - The `DX_RUNNER_HEAVY` and `DX_RUNNER_LIGHT` variables, the runner group and the block on forks.
- **Done when:** a week of CI goes by with no jobs stepping on each other, and the image updates itself.
- **Signed commits:** the bots push through GitHub's API (`scripts/api-commit.py`), which signs their commits: the autopilot and its agent, the release pull request, the reproduction, the weekly learnings and the revert. Then the organisation's ruleset requires signed commits on every branch.
- **Where jobs run:** the shared jobs read `DX_RUNNER_HEAVY`, the `runs-on` value as JSON (`["self-hosted","linux","x64","diluxone"]` here; `"ubuntu-latest"` sends them back to GitHub), so no workflow names DiluxOne's runners. The old `DX_RUNNER` stays until the repositories' own jobs that name it move. The runner group `private-repos-vm` (selected repositories, no public ones) and the approval of first-time contributors' pull requests were already in place. `DX_RUNNER_LIGHT` comes with phase 6, which takes the organisation's own workflows off proper names.

### Phase 6 · Organisation config and several kinds

- **Today:** each repository has a single kind (wordpress-plugin), Unreleased is fixed in `readme.txt`, and workflows and scripts name DiluxOne, the App or the maintainer 661 times, in 54 files.
- **Delivers:**
  - `repos.yml` with a schema: kinds with paths and roles, design system and attributes.
  - `kinds/<kind>/kind.yml`: how to recognise it, checks, risk list, public surface, Dependabot, changelog and release mode.
  - The configuration check (paths that do not overlap).
  - Detection that proposes by pull request, and new repositories by an App event plus a daily schedule.
  - The sync builds, from the roles, the rules that apply to each repository.
  - An organisation configuration file, and workflows and scripts without proper names.
- **So far:** `repos.yml` `repos:` lists every repository with its kinds, paths and roles, held to its schema by `scripts/repos-config.py` (no overlapping paths, known kinds and roles, every repository another section names); `sync-repos.py` reads a repository's kind from there, and the daily drift check reports one missing (a new repository) or whose review policy names another kind.
- **Done when:** a monorepo with two kinds runs the checks of each; a new repository shows up as a pull request to `repos.yml`; and searching for "DiluxOne" in workflows and scripts finds nothing.

### Phase 7 · Release and deploy

- **Today:** release as an issue already exists (#159): with an accepted "Release X.Y.Z" issue, the environment asks for no approver; without one, the environment's reviewers approve, as a fallback.
- **Delivers:**
  - Closing a milestone opens the "Release X.Y.Z" issue.
  - The release pull request the agent prepares.
  - Removing the environment's reviewers, once the issue is enough.
  - For continuous kinds: deploy on merge, with gradual rollout, automatic rollback and feature flags.
- **Done when:** a plugin is published by accepting an issue, and the environment has no human approver.

### Phase 8 · Autopilot by type of work

- **Today:** the sealed PRD (G1), the Spec (G3) and the evidence per criterion (G6) exist. The agent stops and asks for a person, and the public surface detection (#144, merged in #164) only looks at outside authors.
- **Delivers:**
  - The type field, with the process of each type.
  - G1 "Issue ready", with a single schema (`policy/issue-schema.yml`) and a rubric.
  - Escalation by the kind's risk list, applied to the autopilot and to G7 too.
  - The feature phases: impact, threats (curated by a second AI, or by a maintainer when Critical) and architecture.
  - The review loop capped at 3 rounds; G6 run by an agent that did not write the code; auto-merge at G7.
  - Disambiguation: `[Doubt]` marks, rounds of 5 questions, a decision log and a PRD amendment that is sealed again.
  - The spike in the triage.
  - The layers of "Malicious text in issues", in all five types.
- **Done when:** a minor change and a feature go from accepted to merged with no other intervention, and a high-risk one stops for a maintainer.

### Phase 9 · Security

- **Today:** `SECURITY.md` exists, and the triage locks the issue and sends it to private reporting.
- **Delivers:**
  - The private advisory flow, with the fix in the private fork.
  - Merge by the policy: low or medium risk merges on its own with a 4-hour veto; high or Critical is merged by a maintainer.
  - Private reporting in private repositories too.
- **Done when:** a test advisory goes from report to merge through the veto window.

### Phase 10 · Reproduced bugs

- **Today:** the triage, the reproduction, the autopilot, the bugfix-reproduced lane (#166) and reproduction off the VM (#167, merged in #175) exist. It has never been tried with a real bug.
- **Delivers:** a real bug end to end through that lane, and reproduction without hand-written PHPUnit.
- **Done when:** a real bug is reported, reproduced and merged without anyone accepting anything.

### Phase 11 · Learnings

- **Delivers:** findings in the receipt; the weekly job that detects what repeats 3 times; pull requests with the receipts as evidence; and the record of what was rejected.
- **Done when:** the job opened at least one pull request with real evidence and a maintainer decided it.

### Phase 12 · Setup for other organisations

- **Delivers:** an installer that sets up `.github` with defaults, runs detection and opens the `repos.yml` pull request; the base kinds (wordpress-plugin, web-app, web-api and library); and later configuration with an agent.
- **Done when:** DiluxOne is reinstalled with the setup without losing anything, and a test organisation is up and running by accepting a single pull request.

## The flow end to end

Work comes in through four doors: an issue, an organisation decision, the maintenance schedule and a private security report. All of them go through the same gates and end, depending on the kind, in Unreleased or in production. A maintainer appears in four places: accepting an issue, accepting an organisation decision (once, for every repository), merging what the policy leaves to a person (high risk, a security fix) and publishing.

## Five types of work

Five types are enough; everything else (refactor, docs, perf, hotfix, migration) falls inside one of them. What makes the process heavier or lighter is the risk, not the label.

| Type | When | Process | Who decides | Merges on its own |
| --- | --- | --- | --- | --- |
| Maintenance | Dependencies (majors included), the runner image, the organisation's templates and files | The kind's checks | Nobody: the rule is accepted once | Yes, on a schedule |
| Minor | The change fits in one sentence and does not change behaviour: text, a button, a select, docs, a small refactor, a revert | Code, checks, review | A maintainer accepts the issue | Yes |
| Bugfix | Something behaves differently from what is expected, a performance regression included | A test that reproduces it, a test of what must NOT change, code, review, validation | The policy, if the bug was reproduced on its own; otherwise a maintainer | Yes, up to medium risk |
| Feature | Something new, a public API or hook, a migration, a deprecation, a breaking change | PRD, impact, threats, architecture, code, review, independent validation against PRD and Spec | A maintainer accepts the PRD | Yes, up to medium risk |
| Security | A vulnerability reported privately | A private GitHub advisory, never a public issue | A maintainer | Up to medium risk, with a veto |

**What is not a type:** a spike or investigation produces no pull request; it is an outcome of the triage and ends in doing, clarifying or discarding. Release has its own flow (the "Release X.Y.Z" issue).

**Spike or investigation.** It is a step of the triage, not a type of work. It starts when the triage cannot classify an issue (it is a question, it is unclear whether it is a bug or a request, or something has to be measured before deciding), or when a maintainer adds the `spike` label. The agent investigates in the sandbox, read-only and for at most 30 minutes (configurable), and leaves a comment with what it found. It ends in one of three ways: do (it turns into a bug, minor or feature and follows that path), clarify (it asks the author if data is missing, or a maintainer if a decision is missing) or discard (it closes with the reason; when in doubt, a maintainer decides).

**Automatic escalation.** A minor change or a bugfix becomes a feature if it touches anything on its kind's risk list: permissions and authentication, stored data or its schema, public hooks or APIs, payments, data deletion. Deterministic code detects it (like the public surface check of #144), not the AI. Going up is automatic and is stated in the issue; going down is a maintainer's call.

## Bugs: from report to fix, with no person

A reproduced bug is fixed on its own and stays in Unreleased or is deployed, depending on the kind's release mode. A maintainer appears only if the AI asks to escalate, or when deciding to publish.

1. **Triage.** Anyone opens an issue, inside the organisation or outside it. The triage classifies it: bug, product request, question, duplicate or security. If it is really a request, it changes the type and leaves it waiting for a maintainer.
2. **Reproduction.** If it is a bug, an agent writes a failing test, in a sandbox with no network, no secrets and never on the VM (#167). If it cannot reproduce it, it says what it tried and what it is missing, and waits for more data.
3. **Acceptance by policy.** If it reproduces it, the `bugfix-reproduced` lane accepts the fix's issue, without a word of the original report: the test is the specification.
4. **Fix.** The autopilot makes that test pass, writes the test of what must not change and passes every gate. If it touches anything on the risk list, it becomes a feature and stops for a maintainer.
5. **Merge.** It merges on its own up to medium risk, inclusive. The change goes into the changelog under Unreleased, with the rest. If the kind is continuous, the merge deploys.
6. **Publish.** Changes pile up until a maintainer accepts a "Release X.Y.Z" issue. Publishing is always theirs. A continuous kind has no release: what the maintainer decides is turning a flag on.

**When it escalates.** The AI stops and asks for a person if the fix contradicts documented behaviour, if it needs to choose between two reasonable behaviours, if it cannot make the test pass in three rounds, or if it touches the risk list. Escalating is a comment with options, not a new issue.

## Product requests: minor or feature

A maintainer accepts the PRD, and from there the work is autonomous; what changes between a minor change and a feature is how many sections the Spec carries, all in the same issue and the same pull request.

| Phase | Minor | Feature | What it leaves |
| --- | --- | --- | --- |
| PRD with verifiable criteria and no open doubts (G1) | Short | Complete | The issue, sealed |
| Impact analysis: what it touches, sibling implementations, what can break | No | Yes | A section of the Spec |
| Threat model (short STRIDE: data, permissions, inputs), curated by a second AI | No | Yes | A section of the Spec |
| Architecture: where it goes, which pattern it follows, what it does not break | No | Yes | A section of the Spec |
| Test-first code and the kind's checks (G4) | Yes | Yes | The pull request |
| Review (G5) | Yes | Yes, plus the architecture check | Comments |
| Validation by an agent that did not write the code: each criterion with its test, nothing out of scope (G6) | Yes | Yes, also against impact and threats | The receipt |

**If it is big, it is split.** With more than 5 to 7 criteria, or more than 2 or 3 modules, the autopilot proposes sub-issues; each runs its own process and the parent issue stays as an index.

**If validation fails, it goes back to the code:** nothing is patched in the validation. A request from outside is at least a bugfix or a feature, never minor.

## Maintenance and infrastructure

Maintenance runs on a schedule and merges on its own; the mechanism is generic and DiluxOne's configuration lives apart, so another organisation copies it by changing only its data.

| Task | Frequency | Generic (any organisation) | Specific to DiluxOne |
| --- | --- | --- | --- |
| Dependencies on their latest version, majors included | Daily | A Dependabot template per kind, and the sync that brings it to each repository | The kinds it uses and their exceptions in `repos.yml` |
| Runner image | Daily | A workflow that builds, tests and promotes | The VM, the registry, the packages PHP needs |
| The organisation's files and templates | On change in `.github`, and a weekly check | The sync and the drift check | CODEOWNERS, the `AGENTS.md` block, callers |
| Watched decisions ("always PHP 7.4", "every repository with repro-triaged") | Daily | The drift check as a maintenance rule | Each closed decision |
| Revert when something breaks `main` (G8) | Every 15 min | The sweep and the revert pull request | Its limits in `platform` |

**For another organisation to copy it:** workflows and scripts do not name DiluxOne; everything specific lives in `repos.yml`, `policy/` and `kinds/`. Today that does not fully hold; "What we have and what changes" says where.

## Scope: which repositories a decision touches

An organisation decision states its scope as a filter over data, and the system works out the repositories; nobody lists them by hand. It works for any kind of project, not only WordPress.

- **The filter** uses what the organisation already knows about each repository: its kind (`wordpress-plugin`, site, library, whatever comes), its attributes in `repos.yml` (public or private, design system, Project) and what it contains (`package.json`, `composer.json`, `Dockerfile`). Example: "every repository with a `composer.json`".
- **When the issue is accepted**, a job resolves the filter, writes the table of affected repositories in the issue and opens a sub-issue in each. A new repository that enters the filter later gets its own on the next run.
- **What is new for each kind** (its tools, its language version, its Dependabot template) lives in its pack, `kinds/<kind>/`, as it does today. A new kind is a new pack, not new code.

**On a schedule or on request?** Both, depending on the class:

- **Class 1, on a schedule:** the accepted rule says "every repository on the latest version of X", and a schedule enforces it every day (dependencies, the runner image). It asks nobody; it opens the pull request, passes the gates and merges on its own.
- **Class 2, on request:** it fires once, on acceptance. If the decision has to hold over time ("always PHP 7.4 at least"), on closing it becomes a class 1 rule that watches it: the drift check reports it and the maintenance lane fixes it.

So: what is decided once and stays is class 2 that ends as class 1. The "how" of each is the filter plus the job.

## Disambiguation

Doubts are settled before acceptance whenever possible; after it, the agent decides what does not change the scope and asks only about what does.

**Before acceptance:** the PRD marks each doubt with `[Doubt: …]`, and G1 does not let it be accepted while one is left. The triage asks up to 5 multiple-choice questions, the recommended option first, all in a single comment; the answers stay in the PRD with a date. If there are more than 5, they go in rounds: first those that change the scope most, and the rest stay marked as doubts. If doubts remain after two rounds, the issue is too big or badly defined, and the triage proposes splitting it into sub-issues or hands it to a maintainer as a spike.

**After acceptance:**

| The doubt | Who decides | Where it stays | Accepted again? |
| --- | --- | --- | --- |
| About how, without contradicting the PRD | The agent, following the repository's conventions | The pull request's decision log (what, why, when) | No |
| It changes the scope or a criterion | A maintainer | An amendment to the PRD with the difference marked | Yes, looking only at the difference |
| It is bigger than it seemed | A maintainer, choosing between three options: write the full PRD, go on taking the risk, or split it | The issue | Depending on the option |

- What the agent finds along the way never silently widens what was authorised.
- While it waits for an answer, it goes on with what does not depend on it and leaves the pull request as a draft. No timeout decides on its own.

## What merges on its own

With the gates green, everything product-related up to medium risk inclusive merges on its own, and all maintenance does. A maintainer merges what is critical, the autonomy policy, the rules and releases.

| What | Merges on its own | Merged by a maintainer |
| --- | --- | --- |
| Maintenance (class 1) | Always, within the `platform` and `org-sync` lanes | Only if a gate fails |
| Product and organisation decisions (classes 2 and 3) | Low and medium risk, inclusive | High risk, or an issue marked Critical |
| The autonomy policy and the rules (`policy/autonomy.yml`, the gates and the workflows that apply them) | Never | Always |
| Publishing a version | Never | Always (the "Release X.Y.Z" issue) |
| Reverting something that broke `main` (G8) | Within the limits of `platform` | The rest |

The review sets the risk and a pull request cannot lower it: the high-risk paths are in each repository's policy and in the organisation's.

## Any kind of product

The model is the same for a plugin, a site, a library or a monorepo; what changes by kind of project lives in a package, the kind, not in the workflows' code.

- **A kind** brings its checks and tests, its risk list for escalation, its public surface, its Dependabot template, how it keeps its changelog and how it publishes (wordpress.org, npm, an image, a deploy). Today `wordpress-plugin` exists, and the base setup adds web-app and web-api (continuous) and library (versioned); a new kind is a new package in `kinds/`, not new code.
- **A repository can have several kinds**, each over its paths: a monorepo with an API, a front end and a plugin declares three, and a change runs the checks and the process of the kinds it touches. If it touches two, the heavier process wins.
- **Each kind declares its release mode.** Versioned (plugin, store app, library): the merge piles up in Unreleased, wherever the kind says (`readme.txt`, a `CHANGELOG.md`, a release note), and publishing is the "Release X.Y.Z" issue. Continuous (web, API, service): the merge deploys to production with gradual rollout and automatic rollback; what is risky goes in behind a feature flag, and turning it on is a maintainer's decision. The changelog comes from the deploys.
- **The organisation's rules** (the five types, who decides, what merges on its own) live in `docs/model.md` and in `policy/`, and any agent reads them from each repository's `AGENTS.md`. They do not live in an agent's memory. Every threshold (up to which risk something merges on its own, majors, security fixes) is set in `policy/` for the organisation, and each repository overrides it in its own without passing the ceiling the organisation sets.
- **It is installed once and then configured with an agent.** The setup installs `.github` with defaults. After that, any change (runners, thresholds, kinds, lanes, repositories) is asked of an agent in plain language: it reads `docs/model.md` and each file's schema, and opens the pull request. Since everything is a file with a schema that a check validates, the agent needs to know nothing else. If the change touches the autonomy policy or the rules, a maintainer merges it.

### How a repository is classified

It is a method of the organisation's `.github` repository, the same for any organisation: the data goes in `repos.yml` and the rules in `kinds/`.

- **The source of truth is `repos.yml`.** Each repository lists its kinds, and each kind its `paths` and its exceptions. A single-kind repository uses `paths: ["**"]`.
- **The pack says what each kind is.** `kinds/<kind>/kind.yml` declares how to recognise it, its checks, its risk list, its public surface, its Dependabot, its changelog and its release mode (`versioned` or `continuous`).
- **Detection proposes, it does not decide.** A job looks for each pack's signals (a plugin header and its `readme.txt`, a publishable `package.json`, a service's `Dockerfile`, an `app.json`) and opens a pull request to `repos.yml` with what it found. A maintainer accepts it.
- **Unclassified, no autopilot.** A repository with no entry in `repos.yml` has triage and basic checks, but nothing merges on its own until it is classified.
- **Monorepo:** the paths of its kinds do not overlap. A path in two kinds, or code outside all of them, fails the configuration check. A change runs the checks of the kinds it touches; if it touches two, the heavier process wins, and each kind publishes in its own mode.
- **The setup for another organisation** installs `.github` with the generic packs, runs detection over all its repositories and opens a single pull request with the proposed `repos.yml`. Accepting it is what gets everything running; nothing names DiluxOne.
- **A new repository joins on its own.** The GitHub App receives the repository-created event and runs detection at once. A daily schedule in `.github` compares the organisation's repositories with `repos.yml` as a safety net; if an archived or deleted repository is left over, it proposes removing it. Either way a pull request to `repos.yml` comes out with the proposed kind, which a maintainer accepts. Once it is merged, the sync installs the organisation's files and the repository is in. Until then it has triage and basic checks, with no autopilot.

An example, with a simple repository and a monorepo:

```yaml
repos:
  offload:
    kinds:
      - kind: wordpress-plugin
        paths: ["**"]
  platform:
    kinds:
      - kind: web-api        # continuous
        paths: ["api/**"]
      - kind: web-app        # continuous
        paths: ["web/**"]
      - kind: wordpress-plugin   # versioned
        paths: ["plugin/**"]
```

### Where each rule lives

Three layers, from the strongest to the most local: the organisation (in `.github`), the kind and the repository.

| What | Organisation (`.github`) | Kind | Repository | Who merges a change |
| --- | --- | --- | --- | --- |
| Autonomy: lanes, thresholds, majors, security, veto | `policy/autonomy.yml` | - | `.github/policy.yml`: restricts, or widens up to the ceiling | A maintainer |
| Gates and workflows | The workflows of `.github` | The kind's checks | The callers the sync copies | A maintainer |
| Mandatory rules (test-first, security…) | `rules/` (level: mandatory) | `kinds/<kind>/` | `AGENTS.md`: only adds | A maintainer |
| Conventions and good practice | `docs/model.md` and the `AGENTS.md` block the sync copies | `kinds/<kind>/` | `AGENTS.md`, under the block | Organisation and kind: a maintainer. The repository's own: a lane, if it only tightens |
| Repositories and kinds | `repos.yml` | `kind.yml` | - | A maintainer |
| Infrastructure | Organisation variables (`DX_RUNNER_*`, `DX_AUTOPILOT`) | - | Repository variables | A maintainer |

What is below adds or restricts; it never loosens what is above, except up to the ceiling the organisation sets. The drift check watches that nobody edits what the sync copies. Every file has a schema a check validates, which is why an agent can configure everything without knowing anything else.

### The organisation's rules

How we review, styles, formats, what every change must meet, and the guides for back end, front end or data live in `.github/rules/`, one file per rule. It is not a separate library: it is documentation with a header, and the system reads it.

- **Each rule says its level, what it applies to and how it is enforced.** The header declares `level`, `applies_to` and `enforced_by`. The level is `mandatory` (it cannot be excluded, like test-first) or `standard` (a repository can exclude it with a reason). `applies_to` says whether it applies to everything, to a kind or to a role such as `front` or `back`, and `enforced_by` whether a deterministic check or the review enforces it.
- **Each repository declares its roles.** In `repos.yml`, each kind carries its roles. A monorepo can have `web/**` as front and `api/**` as back; a back-end-only repository never receives the front-end rules.
- **The sync builds each repository's list.** The `AGENTS.md` block it copies lists only the rules that apply, so the agent does not load rules that do not belong.
- **The review uses those of the paths touched.** A pull request that touches `web/` and `api/` is reviewed against both sets.
- **The repository adds, and excluding needs a reason.** A repository adds its own in its own `.github/rules/`. To opt out of an organisation standard, it declares it in its `policy.yml` with the reason, and a maintainer merges that. A mandatory rule cannot be excluded.

```markdown
---
id: front-no-credentials
level: mandatory
applies_to: { roles: [front] }
enforced_by: [check: secret-scan, review]
---
The front end never stores credentials or long-lived tokens...
```

## What we have and what changes

The base is there (autopilot, gates, receipts, lanes, packs per kind); what is missing is splitting the work by type, taking WordPress and DiluxOne out of the code, and taking the maintainer out of the mechanical work. Review of `.github` as of 2026-10-15.

| Part of the model | Today | Missing |
| --- | --- | --- |
| Maintenance | Automatic daily image (#190); a drift check that only reports; the sync run by hand. The organisation's Dependabot (#180), the sync lane (#171) and revert (#165) are merged | A schedule that runs the sync, not only the check; dependencies with majors merging on their own (today `composer.json` and `package.json` are high risk) |
| Bugs | Triage, reproduction, autopilot, gates and the reproduced-bugs lane (#166) exist | Making "Unreleased" part of the model: today it lives in WordPress's `readme.txt`; reproduction without hand-written PHPUnit |
| Product | Sealed PRD (G1), Spec (G3), evidence per criterion (G6) | The type field (minor or feature); impact, threats and architecture; validation by an independent agent. **And lowering `human-issue` from high to medium risk:** today it merges on its own more than agreed |
| Security | `SECURITY.md`; the triage locks the issue and sends it to private reporting | The private advisory flow; private reporting in private repositories too |
| Organisation decisions | Only the mechanical sync reaches each repository | The decision issue, the repository filter, delegated sub-issues (#179) |
| Disambiguation | The agent stops and asks for a person | Doubt marks in G1, a decision log, a PRD amendment that is sealed again |
| Escalation by risk | High-risk paths and public surface detection (#144), but only for outside authors | A risk list per kind (permissions, data, API, payments, deletion) applied to the autopilot and to G7 too |
| Any product | Packs per kind; only `wordpress-plugin`; one kind per repository | Several kinds per repository with their paths; moving into the pack what is fixed for WordPress today |
| Copyable by another organisation | No: 661 mentions of DiluxOne, the App or the maintainer in 54 workflow and script files | An organisation configuration file; workflows and scripts without proper names |

## Decisions taken on open questions

- [x] **Dependency majors:** they merge on their own if the checks pass, and the revert undoes them if they break `main`. Set in `policy/autonomy.yml` with `majors: auto | human`, for the whole organisation, with an override per kind or per repository. Decided on 2026-10-15: auto by default, and human where a major hurts more, such as payments or data.
- [x] **Who curates a feature's threat model:** decided on 2026-10-15: a second AI, and a maintainer only if the issue is Critical.
- [x] **Where the maintainer sees what waits for them:** every pending question or decision lives in the issue of its repository, labelled `needs:maintainer`. Decided on 2026-10-15: a view of the organisation's Project filtered by that label, which is already in use and needs nothing built.
- [x] **Lowering `human-issue` to medium risk now:** today the lane of issues a maintainer accepts merges on its own up to high risk, more than the model says (medium). Decided on 2026-10-15: it is fixed now, because it is a configuration change that closes a gap that exists today. The risk up to which something merges on its own is configurable in `policy/autonomy.yml`: the organisation sets a default (medium) and a ceiling (high; Critical never merges on its own), and each repository overrides it. Lowering it is free; raising it, only up to the ceiling. As part of the autonomy policy, a change to it is merged by a maintainer.
- [x] **Security fixes:** decided on 2026-10-15: configurable per organisation, and each repository overrides it. By default, low or medium risk merges on its own, after the gates and the independent validation, with a veto window (the maintainer is told and can stop it for 4 hours, configurable); high risk or Critical is merged by a maintainer.

## Today vs proposed

Today a maintainer steps into five points of every change; with the proposed model, into one (accepting the issue), plus what the policy leaves to a person and releases.

| Moment | Today | Proposed |
| --- | --- | --- |
| Writing the issue | A maintainer or an agent writes it, with no standard for "ready" | An agent completes it until it passes the "Issue ready" gate |
| Accepting the issue | A maintainer (`accepted`) | A maintainer, the only human decision; marks it `critical` if needed |
| Opening the pull request | A maintainer asks for it (for cost) | The agent opens it on its own, as soon as the issue is accepted |
| Fixing what the review flags | An agent, when a maintainer asks | An automatic loop until the review is clean, with a cap on rounds |
| Merging | A maintainer, except low risk and complexity | Auto-merge if every gate passes; a person only if it is `critical` or touches the autonomy policy or the rules |
| Approving the release | An accepted "Release X.Y.Z" issue (#159), with the environment's reviewers as a fallback | A maintainer accepts the release issue; the environment has no reviewers |
| Platform issues (image, drift, Dependabot) | Accepted on their own by the `platform` lane | Accepted on their own by policy, with a record |

## The full flow

From issue to release there are eight gates and three human decisions: accepting the issue, merging what the policy leaves to a person, and accepting the release. An organisation decision, the fourth place a person decides, is accepted once, outside any single change. If a gate fails, the change does not move: the agent fixes it and tries again within its caps, or hands it back to the maintainer in the issue with the action and the URL.

## Gates

A change moves only if it passes each gate in order; each gate is a GitHub check with a fixed name (`gate / …`) and leaves its result on the issue's board. The deterministic ones (no AI) always win; the AI can only stop one, never skip a deterministic one.

| Gate | What it verifies | Kind | Where it stays | If it fails |
| --- | --- | --- | --- | --- |
| G1 Issue ready | Problem, scope, out of scope, verifiable acceptance criteria, which tests prove it, criticality, kind | Form + an agent that completes and validates | The issue's card (pinned comment) + the `ready` label | The agent asks for what is missing in the issue; it cannot be accepted |
| G2 Acceptance | `accepted` added by a person, or a lane of the policy that allows it | Deterministic | Board: who accepted, or which rule, with a link to the policy's commit | Nothing starts |
| G3 Plan | Files to touch, approach and tests, before writing code; that it stays in scope and touches no protected path (autonomy policy and rules) | Agent + a deterministic path check | A "Plan" comment in the issue | It stops and asks the maintainer in the issue, with the action and its URL |
| G4 The kind's checks | Conventions, issue gate, lint, static analysis, tests, Plugin Check… | Deterministic | The pull request's checks | The agent fixes it and pushes again (counts as a round) |
| G5 Clean review | No open blocker or major | AI | Review comment + threads | Loop: the agent fixes and re-reviews; capped at 3 rounds, then `needs-human` with a summary |
| G6 Meets the issue | Every acceptance criterion with its evidence (the test that proves it), and nothing out of scope | AI + a verifiable table | A "Criteria" comment in the pull request | Back to the loop; if it is scope, `needs-human` |
| G7 Merge | G1 to G6 green, issue not `critical`, no protected paths, within budget | Deterministic | Board: "merged by policy X" | Left for a person to merge, with the reason and the URL |
| G8 Healthy main | `main`'s CI green after the merge | Deterministic | Board + the weekly issue | Automatic revert pull request (`platform` lane) + an issue |

**The issue's board** is a single comment the bot keeps up to date: one row per gate, with ✓ or ✗, when, who or which rule, and the link. It is the first thing to look at to know where a change is and why.

**Limits that always cut:** rounds per pull request (3), cost per issue (the policy's `budget-usd`), the agent's jobs in parallel (2), time per round, and a general switch `DX_AUTOPILOT=off` in the organisation that stops everything autonomous without touching code.

## Autonomy policy and lanes

Everything decided without a maintainer comes from a single file, `policy/autonomy.yml` in `DiluxOne/.github`: a repository overrides it in its `.github/policy.yml`, and can restrict it freely or widen it only up to the ceiling the organisation sets. Each lane is a named entry, and nothing is accepted on its own unless it fits one.

Each lane says: who can originate it (which organisation workflow and which author, for example `dilux-bot` from `runner-image.yml`), how it is recognised (a `lane:<name>` label), what evidence it demands before accepting and before merging, up to which risk it can merge on its own, and in which repositories it applies.

| Lane | What it covers | Evidence |
| --- | --- | --- |
| `platform` | The runner image, Dependabot for actions and images, the organisation's drift, the PHP version of the tools | The image's smoke test, green checks |
| `human-issue` | Issues a maintainer accepts: the autopilot end to end | G1 to G7 |
| `release` | The release issue | The maintainer's acceptance + a consistent version |
| `bugfix-reproduced` | A reported bug, reproduced by a failing test, and a fix that makes it pass | The test red before and green after, and the report and the fix talking about the same thing |
| `org-sync` | The issues and pull requests the sync opens to bring a repository in line | The run's marker, its fingerprint and only the paths the run may change |

**The golden rule:** the autonomy policy (`policy/autonomy.yml`, the review policy, the gates and the workflows that apply them) and the rules in `rules/` always need human acceptance and merge. Autonomy cannot widen itself.

The gate ignores, on purpose, any label a bot adds. The only exception is a lane's label, and it is valid only if the issue was opened by the workflow the lane names, with the author it names; the gate checks that against the issue's history, not against the label.

## Traceability

Any automatic decision is answered in three clicks: the issue's board says what was decided, the rule says why, and the rule's commit says since when.

| The maintainer's question | Where the answer is |
| --- | --- |
| Who or what accepted this issue? | The issue's board, row G2: the maintainer's user, or "lane `platform`" with a link to `policy/autonomy.yml` at the exact commit |
| Why was it merged without me? | Board, row G7: each condition with its result and the link to the check |
| What did the agent change, and why? | The "Plan" comment in the issue and the loop's rounds in the pull request ("Round 2/3: fixed X because the review said Y") |
| Does it meet what I asked for? | The "Criteria" comment in the pull request: criterion, the test that proves it, result |
| What was decided on its own this week? | The weekly issue "Decided by policy" (#118) in `.github`, with everything accepted and merged by policy in the organisation |
| Who changed the policy? | The history of `policy/autonomy.yml`: each change is a pull request a maintainer merged, by the golden rule |

Everything stays in GitHub: comments, checks and labels (`accepted-by:policy`, `merged-by:policy`). There is no separate system to maintain.

## PRD, Spec and receipts

The issue has two sections, each with its own hash: PRD and Spec. On merge, the bot stores a signed receipt in a branch only the bot can write to. The PRD is frozen when the issue is accepted, the Spec when G3 passes, and the receipt records both hashes with the merge.

- **PRD:** a maintainer writes it (or an agent with them). On acceptance its hash is stored; if someone edits it later, the gate detects it and it has to be accepted again.
- **Spec:** the agent completes it at G3 in the same issue. When G3 passes its hash is stored; if it changes, G3 runs again and it is recorded.
- **Receipt:** a JSON the bot commits to the repository's `receipts` branch. It is an orphan branch (it shares no history with `main`); a ruleset lets only `dilux-bot` write to it and forbids deleting or rewriting it. A GitHub App's commits come out signed and "Verified". Public repositories add a GitHub artifact attestation (a Sigstore signature); in private ones that feature needs Enterprise Cloud.

## Malicious text in issues

**Injected text ("delete the whole repository"):** the agent reads text anyone writes. These layers apply to all five types of work, and none depends on the agent behaving well.

1. **Strict structure:** the issue has exactly the form's headings and nothing outside them; loose text between sections fails the gate. Deterministic, no AI.
2. **Acceptance covers the content:** the maintainer reads the PRD before accepting, and the hash freezes it. The agent reads only the PRD and the Spec at those hashes, never third parties' comments.
3. **Text is data, not orders:** the prompt presents the issue as a specification to implement, never as instructions for the agent.
4. **Least privilege:** the agent's token cannot delete the repository or branches, push to `main` or touch workflows; everything goes through a pull request with gates, and a destructive pull request triggers scope (G3), the review and high risk.
5. **A sandbox to reproduce:** a bug's reproduction runs with no network, no secrets and never on the VM (#167).
6. **The report does not reach the one who executes:** the fix's issue is accepted without a word of the original report; the test is the specification.
7. **The AI only stops:** deterministic gates always win; the AI can stop one, never skip it.

## Learnings

The system learns from its own receipts, but it does not change itself: it proposes, and a person decides what matters.

1. **Record.** On merge, the receipt also stores the findings: how many rounds it took, what the review flagged, whether there was an escalation or a revert.
2. **Analyse.** A weekly job in `.github` reads the receipts of the whole organisation and looks for what repeats. A finding counts as a learning when it shows up at least three times. The frequency and the threshold are configurable.
3. **Propose.** For each learning, the agent opens a pull request with the change to the rule it belongs to (a standard, the kind, a repository's `AGENTS.md`), and puts in the description the links to the receipts that prove it.
4. **Decide.** If the pull request touches the rules or the autonomy policy, or loosens anything, it shows in the Project with `needs:maintainer`, and a maintainer merges or closes it. If it only tightens a repository's local convention, it can go in through a lane. A closed pull request is recorded and not proposed again.

**Example:** in two weeks, the review flags "the REST endpoint's input is not sanitised" in four pull requests across three repositories. The job opens a pull request that adds `rules/rest-sanitize-input.md`, with the four receipts as evidence. A maintainer merges it, the sync spreads it, and from then on the agent meets it and the review checks it.

## Release as an issue

A release is only publishing an X.Y.Z version for users (wordpress.org, a downloadable zip, npm…); `-dev` builds come out on their own on every merge and need no issue. Publishing is a maintainer's decision, and the release issue is how they take it.

| How the "Release X.Y.Z" issue is born | Who decides |
| --- | --- |
| A maintainer opens it when they want to publish | The maintainer, by opening and accepting it |
| The bot opens it when the last issue of a version milestone closes | The maintainer, when planning the milestone; they still accept it |
| The bot never opens it on its own initiative | It only suggests in the weekly summary: "7 unpublished changes in Offload for 30 days" |

Once accepted: the agent opens the release pull request (removes `Unreleased.`, sets the markers), it passes the gates and merges, and the deploy checks that a person accepted the issue and that the version matches before publishing. The GitHub environment is left with no human approver: the approval is the issue. For other software, the `kind` defines where it is published; the circuit is the same.

## Execution engine

The agent runs as `claude-code-action` on the organisation's VM, authenticated with the maintainer's subscription and committing as `dilux-bot`; that way the agent's work is never mistaken for the maintainer's.

**Each organisation chooses where it runs:** GitHub's runners, its own (a VM like ours) or a mix. It is chosen with the organisation variables `DX_RUNNER_HEAVY` and `DX_RUNNER_LIGHT` (see Platform), without touching the workflows. DiluxOne uses the mix: the heavy work on the VM, the light work on GitHub.

|  | Anthropic's cloud (routines) | `claude-code-action` on the VM (chosen) |
| --- | --- | --- |
| Uses | The maintainer's subscription | The maintainer's subscription |
| Fires on acceptance | Yes, through the `/fire` URL | Yes, `issues: labeled` |
| Commits and pull requests come out as | The maintainer | `dilux-bot`, signed "Verified" |
| Resources | Does not use the VM | One VM runner while it works |

**Why the VM:** if the agent commits as the maintainer, the gates and the receipts cannot tell one's work from the other's, and the maintainer is a trusted author. Cloud sessions are kept for what is worked by hand.

**Done on 2026-10-10:** every Claude run in the organisation (review, replies, learnings, triage, reproduction) uses the maintainer's subscription; the API key stays as a fallback ([.github #76](https://github.com/DiluxOne/.github/pull/76)).

**Concurrency:** one agent per repository at a time; in total, as many as the runners leave free. An accepted issue waits in line if there is no room.

## Platform: the first lane

The VM moves to running each job in a disposable container, made from an image that rebuilds itself every day; it is the first work accepted and published without a maintainer.

- **Why:** today jobs share the operating system and step on each other: apt locked, `setup-php` changing everyone's PHP, `composer` rewritten while in use, wp-env folders owned by root, a full disk.
- **Image:** `ghcr.io/diluxone/runner`, public (free on GHCR), an Ubuntu base pinned by digest, with what is common (git, Docker CLI, Node LTS, Chromium's libraries). Each job installs its stack with `setup-php`, `setup-node` and so on, as on GitHub. It serves PHP, Node, Python or whatever comes.
- **Ephemeral runners:** each runner runs in its own container with `--ephemeral` and is recreated after each job. They use the VM's Docker for wp-env.
- **Daily build:** a workflow in `.github` (public, free) builds a candidate, runs the smoke test (git, Node, Docker, `setup-php`, Chromium opens, wp-env brings up WordPress) and, if it passes, promotes it to `stable`. If it fails, `stable` does not change and an issue is opened with the log.
- **A record with no approval:** each successful build comments in the pinned issue "Runner image" (#93) with the date and which versions changed.
- **Going back:** dated images are kept; going back to the previous one is a click, or automatic if the VM's jobs start failing all at once (second stage).
- **The VM as code:** a script in `.github` (`scripts/runner-vm/`) leaves the VM as it should be on every boot (runner containers, cleanup before shutdown). A merged change reaches the VM on the next boot.
- **Where each job runs:** what is heavy or uses secrets (the repositories' CI, the agent, wp-env) goes to the VM; what is light and the organisation's (the G8 sweep, the image build, the sync, the drift check) goes to GitHub's runners from `.github`, which is public and spends no minutes. Each workflow chooses with `runs-on: ${{ vars.DX_RUNNER_HEAVY }}` or `${{ vars.DX_RUNNER_LIGHT }}`, organisation variables. In DiluxOne they are `diluxone-vm` and `ubuntu-latest`; another organisation sets its own without touching the workflows.
- **Who uses the VM:** the runners register at the organisation level with the `diluxone-vm` label, in a runner group that says which repositories may use them. A pull request from a fork never runs on the VM: it asks for approval and the group leaves it out.

## PHP policy

Build with the highest PHP (8.5 today) and support the lowest with a market: 7.4, 94% of WordPress sites. They are two different things and do not step on each other.

- **Build on 8.5:** PHPStan, PHPCS, Psalm, wp-env and the tests run on the latest version.
- **Hold the code to 7.4 while building on 8.5:** PHPStan analyses as if for 7.4 (`phpVersion: 70400`), PHPCompatibility (a PHPCS standard) flags any syntax that does not exist in 7.4, and the matrix runs lint and unit tests from 7.4 to 8.5 (PHPUnit 9.6 runs on all of them).
- **Cost:** PHPCompatibility says exactly what each of the organisation's plugins has to change to go down to 7.4.

| Minimum | WordPress sites that can use it |
| --- | --- |
| 7.4 | 94% |
| 8.0 | 78% |
| 8.1 | 74% |
| 8.2 | 63% |
| 8.3 | 39% |

Source: [wordpress.org's PHP statistics](https://api.wordpress.org/stats/php/1.0/), as of 2026-10-10.

The tools' version lives in one place (the `kinds/wordpress-plugin` pack), and the `platform` lane raises it when a new PHP comes out; the minimum lives there too, and only a maintainer changes it.

## PRD and Spec quality

A single schema in `.github` (`policy/issue-schema.yml`) defines the PRD and Spec sections; the issue forms are generated from it and the gate reads it, so form and validation never drift apart.

| Layer | What it ensures | How |
| --- | --- | --- |
| Deterministic | Form | Exact headings in order, nothing outside them, required fields filled, criteria with an ID (`C1: Given… when… then…`), a non-empty "out of scope", each PRD ID with its test in the Spec |
| AI rubric (G1, G3) | Substance | Scores clarity, testability and ambiguity; comments on what is missing. It can only stop, never approve alone |
| Closing the loop (G6) | That it was met | The tests the Spec names exist and pass; a problem the review finds that came from a weak PRD becomes a rubric rule |

Each kind can add sections (WordPress: impact on multisite), never remove the organisation's.

## Design systems

The global design systems live in `.github/design-systems/<name>/`, and each project is associated with one, or has its own, which can extend a global one.

| System | Where | For whom |
| --- | --- | --- |
| `wordpress-admin` (first) | `.github/design-systems/wordpress-admin/` | The plugins' admin screens; based on Offload and Users+ as they are |
| `app` | `.github/design-systems/app/` | Applications |
| The project's own | `docs/design-system/` in its repository | A project that cannot reuse a global one; it can extend it |

- **What each one brings:** tokens in JSON (the standard design tokens format) that generate CSS variables, components and patterns with examples, and rules for the review. It is versioned with the organisation's tags.
- **Association:** in `repos.yml` (`design-system: wordpress-admin`) or `design-system: local`.
- **Enforcement:** a deterministic lint (stylelint) forbids colours and sizes outside the tokens, and the kind's review reads the associated system and flags UI that does not follow it.
- **Starting point:** Offload and Users+ already use the WordPress admin palette (`#2271b1`, `#1d2327`, `#646970`, `#dcdcde`), but typed by hand in each stylesheet. The v0 extracts tokens, typography, spacing and patterns (tabs, cards, notices, tables) from both; then each plugin swaps the hex values for the variables.

## Decisions taken

- [x] The model, with gates, lanes, traceability and the golden rule.
- [x] PHP minimum: 7.4 for the whole organisation, tools on 8.5.
- [x] Cap on the review loop's rounds: 3.
- [x] Concurrency: one agent per repository; in total, what the runners leave.
- [x] Who pays: the maintainer's subscription, already applied to every Claude run.
- [x] Release: a maintainer or a milestone opens it; the bot only suggests.
- [x] PRD and Spec in the same issue, with a hash per section; the receipt in the orphan `receipts` branch.
- [x] Engine: `claude-code-action` on the VM, commits as `dilux-bot`.
- [x] The VM: it stays as it is.
