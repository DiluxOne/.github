# What happens on a pull request

The path every change takes in a DiluxOne repository, step by step. The short version, with a diagram, is in the [README](../README.md).

0. **An accepted issue first.** Every pull request, a maintainer's too,
   closes an issue a maintainer accepted: the description says
   `Closes #12` (or the issue is linked under *Development*), and the issue
   is open, in the same repository and carries the `accepted` label, added
   by a person. A bot's label never counts, so no automation can accept an
   issue, and only people with triage access or more can label one. The
   issue's **Type** (GitHub's own field: the organisation's Feature, Bug,
   Task and Docs) must fit the pull request's: a `feat` (or any `!`) closes
   a Feature, a `fix` a Bug; the issue forms set it (bug → Bug, feature →
   Feature, docs → Docs, maintenance task → Task) and a maintainer corrects
   it when accepting. Priority and Projects are the maintainer's, set when
   accepting. So an accepted bug report cannot
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
   links, a `docs` title that changes only documentation, and at most
   `max-changed-lines-untrusted` (600) lines from an author who is not
   trusted, `composer.lock`, `package-lock.json` and translation files aside) and the fast gates of the repository's kind of project, among them
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
   thread to resolve), `risk:*`, `complexity:*` and `type:*` labels (the type of the change read from the diff, which also corrects the title's type token; a person's own `type:*` label wins), one summary comment
   with what the run cost, red when blocking. It can raise the risk, never
   lower it. It reads the whole change once and only what you pushed since
   its last look after that, spends nothing when the same commit is re-run,
   uses the model and effort the policy names for that floor (read from the
   base branch, so a change cannot pick its own reviewer), skips the
   repository's code rules for text-only changes, and after `max-auto-reviews`
   (5) keeps the last verdict until the `review:full` label asks for more.
   Drafts and forks are not reviewed; pull requests Dependabot or the
   organisation's App open are (`allowed_bots`).
3. **Merge.** A human, with [`scripts/squash-merge.sh`](../scripts/squash-merge.sh)
   `<owner/repo> <number>` (description verbatim, co-authors kept), or
   GitHub's auto-merge when the floor is low, the verdict is low risk and low
   complexity, nothing blocks, the author is trusted and the policy says
   `auto-merge: true`.

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
