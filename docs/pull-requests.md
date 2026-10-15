# What happens on a pull request

The path every change takes in a DiluxOne repository, step by step. The short version, with a diagram, is in the [README](../README.md).

0. **An accepted issue first.** Every pull request, a maintainer's too,
   closes an issue a maintainer accepted: the description says
   `Closes #12` (or the issue is linked under *Development*), and the issue
   is open, in the same repository and carries the `accepted` label, added
   by a person. A bot's label never counts, so no automation can accept an
   issue, and only people with triage access or more can label one. The one
   exception is explicit and narrow: a lane of the autonomy policy
   ([`policy/autonomy.yml`](../policy/autonomy.yml), read by
   [`scripts/autonomy.py`](../scripts/autonomy.py)) accepts an issue that
   its App opened from one of its own workflows' runs, named in the issue
   and checked against the API, never on a label alone. The `org-sync`
   lane (#155) accepts the Task issue `scripts/sync-repos.py` opens
   (`files`, `callers`) from a maintainer's machine: opened and labelled by
   a person the lane names, never edited, naming a commit merged here and
   the fingerprint of the files the run wrote, which its pull request's
   files must give again, from the run's branch, touching only the paths
   that kind of run writes; never in this repository. `issue-accepted.yml`
   says on the issue when a lane accepts it, with `accepted-by:policy`, and
   the gate asks again on the pull request. A repository's own
   `.github/autonomy.yml` can only make that stricter, and the organisation
   variable `DX_AUTOPILOT=off` stops every lane. When a person accepts an
   issue its PRD is sealed (its SHA-256 on the repository's `receipts`
   branch, [`scripts/receipts.py`](../scripts/receipts.py)); a PRD edited
   after that fails the gate until a maintainer accepts it again, and so does
   a seal that cannot be read. An issue a lane accepted carries
   `accepted-by:policy`; its gate checks its origin instead of a person's
   label. A reproduced bug is the first lane that reaches the autopilot
   (#84): when the reproduction's test fails, dilux-bot opens an issue of
   its own for the fix (`lane:bugfix-reproduced`), whose PRD is fixed text
   and the reproduction's facts, never the report's words, with that test,
   its SHA-256 and its branch as the specification; the lane accepts it from
   GitHub's history, the workflow seals its PRD as accepted by the policy,
   and the autopilot starts. A report the triage reads as a request is
   retyped Feature instead and waits for a person; one that does not
   reproduce gets what was tried and what would settle it, and waits. The
   issue's **Type** (GitHub's own field: the organisation's Feature, Bug,
   Task and Docs) must fit the pull request's: a `feat` (or any `!`) closes
   a Feature, a `fix` a Bug; the issue forms set it (bug → Bug, feature →
   Feature, docs → Docs, maintenance task → Task, release → Task) and a maintainer corrects
   it when accepting. Priority and Projects are the maintainer's, set when
   accepting. The issue is assigned to whoever accepted it, unless it has
   an assignee, and passes to the member of the organisation who opens the
   pull request that closes it; an outside contributor's or a bot's pull
   request leaves it as it is (#73, `pull-request-assignee.yml`). So an
   accepted bug report cannot
   carry a feature in. Bots'
   own pull requests (Dependabot, releases) are exempt. This is where a
   feature that is already planned, or that belongs to a paid add-on, is
   stopped: before anyone writes it, by not accepting its issue. The gate
   is a deterministic step of the conventions check
   ([`scripts/issue-gate.sh`](../scripts/issue-gate.sh), the policy's
   `issue-gate`, read from the base branch), so it runs on forks too, with
   a read-only token. When the issue is accepted after the pull request
   opened, `issue-accepted.yml` re-runs the failed check on its own (GitHub
   does not start the organisation's required workflow on an edit of the
   description); otherwise push, or re-run the job.
1. **Checks.** The conventions (branch name, title, every commit, the
   description's required sections, no "Generated with" footer, relative doc
   links, a `docs` title that changes only documentation (the
   organisation's `docs-paths` and the kind's), no new public surface (a
   WordPress plugin's settings, options, REST routes, AJAX endpoints, admin
   pages, post types, taxonomies, hooks, shortcodes, blocks: the kind's
   `surface.yml`) in a pull request that is not a `feat` from an author who
   is not trusted, read from the diff alone so it holds on forks (#144,
   [`kinds/`](../kinds/README.md#public-surface)), and at most
   `max-changed-lines-untrusted` (600) lines from an author who is not
   trusted, `composer.lock`, `package-lock.json` and translation files aside;
   an autopilot pull request a maintainer took over, with `needs-human`
   added, `autopilot` removed and a commit of the maintainer's own pushed
   from a clone, counts as the maintainer's) and the fast gates of the repository's kind of project, among them
   its review rules: what that kind's reviewers sent back before, as data
   ([`kinds/`](../kinds/)). Deterministic, no AI.
2. **Review.** [`scripts/policy.py`](../scripts/policy.py) sets the lowest risk
   the change can have from its paths alone
   ([`policy/review-policy.default.yml`](../policy/review-policy.default.yml) plus
   the repository's `.github/review-policy.yml`; `policy.py --test` checks
   its rules). Then Claude reviews it with
   the [review profiles](../review-profiles/) (general, and the kind's
   `kinds/<kind>/review-profile.md`) and the repository's `AGENTS.md`
   and `docs/architecture.md`: inline comments for blockers and majors (each a
   thread to resolve), `risk:*`, `complexity:*` and `type:*` labels (the type of the change read from the diff, which also corrects the title's type token; a person's own `type:*` label wins, over the title too), one summary comment
   with what the run cost, red when blocking. It can raise the risk, never
   lower it. It reads the whole change once and only what you pushed since
   its last look after that, spends nothing when the same commit is re-run,
   uses the model and effort the policy names for that floor (read from the
   base branch, so a change cannot pick its own reviewer), skips the
   repository's code rules for text-only changes, and after `max-auto-reviews`
   (5) keeps the last verdict until the `review:full` label asks for more.
   Drafts and forks are not reviewed; pull requests Dependabot or the
   organisation's App open are (`allowed_bots`).
3. **Merge.** The autopilot works in a draft pull request (#109): the Spec
   as a checklist, a commit per criterion, each box ticked once its commit is
   pushed; the review and the merge decision start when it marks it ready.
   A pull request the autopilot opened (#83, label `autopilot`)
   merges by policy when gate G7 passes ([`scripts/autopilot.py`](../scripts/autopilot.py)
   `decide`): the issue is not Critical, no protected path of
   [`policy/autonomy.yml`](../policy/autonomy.yml) changes, the review does
   not block and its description is true, risk and complexity are within the
   caps of the lane it was worked under (`human-issue` for an issue a person
   accepted, the lane's own for a lane's issue), the Spec is complete and every criterion's test is a test
   file the pull request adds or changes; for a reproduced bug, the
   reproduction test is in it with the SHA-256 the PRD sealed (the test that
   failed before; the autopilot ran it only in the sandbox, where it must
   pass before the pull request is ready, and the pull request's own checks
   run it too); it is labelled `merged-by:policy`. While the review blocks,
   the autopilot fixes and pushes, up to three rounds, then hands it to a
   person (`needs-human`). A sync run's pull request (lane `org-sync`)
   merges by policy too ([`scripts/autonomy.py`](../scripts/autonomy.py)
   `lane-merge`) when the lane accepts its issue and every file it changes
   is what the commit of this repository the issue names holds (CODEOWNERS
   as `repos.yml` has it, only the `dx:org` block of `AGENTS.md`, each
   caller job a template's but the repository's own inputs), the review
   does not block and its description is true, within the lane's caps; a
   job that changes its permissions or the secrets it passes, a new one
   too, is high risk and waits for a person. Any other pull request: a human, with [`scripts/squash-merge.sh`](../scripts/squash-merge.sh)
   `<owner/repo> <number>` (description verbatim, co-authors kept), or
   GitHub's auto-merge when the floor is low, the verdict is low risk and low
   complexity, nothing blocks, the author is trusted and the policy says
   `auto-merge: true`.

4. **Release.** Merging publishes nothing by itself. A person opens the
   issue "Release X.Y.Z" (the Release form) and accepts it; that opens the
   release pull request (the `Unreleased.` hold removed, the version
   markers set: the command the kind names), which goes through steps 1 to
   3 and closes the issue. When it merges, the release workflow publishes
   only if that issue was accepted last by a person, not a bot, with the
   admin or maintain role on the repository (triage or write is not
   enough), and its title still names the version the labels give
   ([`scripts/release-issue.py`](../scripts/release-issue.py) `verify`,
   [`scripts/release-gate.py`](../scripts/release-gate.py)). The bot never
   opens a release issue and no policy accepts one.

5. **After the merge (G8).** When a merged pull request turns the default
   branch red, it is reverted
   ([`revert-on-red.yml`](../.github/workflows/revert-on-red.yml), every 15
   minutes over every repository, [`scripts/revert.py`](../scripts/revert.py)).
   It reads where the red began: the first run of a workflow on the default
   branch that failed after a green one, on the merge commit of a pull
   request whose head passed the same jobs. Its failed jobs run again once:
   green, and the run says it was flaky and nothing is reverted; red again,
   and dilux-bot opens a Bug issue linking the merge, the failing run and the
   original pull request, a pull request `revert: <original title>` that
   closes it, labels the original `reverted` and reopens its issues (the
   cause is theirs to fix). The revert goes through the same checks and
   review; it merges on its own only within the `platform` lane of
   [`policy/autonomy.yml`](../policy/autonomy.yml) (its repositories and
   caps, no protected path), and otherwise its issue says why it waits and
   "Approve and merge" with its URL. A red that was there before the merge,
   a job that never ran on the pull request, a revert's own merge, or
   `DX_AUTOPILOT=off`: nothing is reverted, and the run says why.

Mention `@dilux-bot` in a review thread or in the conversation and Claude
answers there; it resolves its own thread when the point is settled.

Nothing runs twice for one change. An edit of the title or the description
re-runs only the conventions, the review (free on a commit it already
read) and the auto-merge decision, never the suites. A push to `main` runs
the slow suites only when it must: the job verifies that the commit is the
squash merge of a pull request of this repository, that its tree is the
one that pull request's checks ran on and that every check there passed;
any doubt runs everything. A pull request whose base branch changed after
its last push fails the conventions on every edit until a push runs the
suites against the new base. The conventions read the labels as they are
when they run, not as the event carried them, so a re-run sees the
`type:*` label the review set since; they compare the title's type with it
once the review has read the commit (the review App's last record names
it) or has reached its cap, so a push that changes the title waits for the
review's new reading instead of failing on the old label. An edit's review
runs in a concurrency group of its own: it cancels nothing and nothing
cancels it, since a cancelled run leaves a cancelled check that blocks the
merge. It spends nothing: on a commit the review read it reuses the
verdict, and on one its push's run is still reviewing it waits for that
verdict and reuses it, or fails when none comes. Once a week everything
runs against today's WordPress and tools, and a failure opens one
`ci:weekly` issue; *Run workflow* runs everything by hand, and its failure
is in the run alone.
