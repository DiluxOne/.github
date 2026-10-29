<!-- dx:org:start (kept in step by DiluxOne/.github, scripts/sync-repos.py; edit it there) -->
## The organisation's rules (the same in every DiluxOne repository)

You are working in a DiluxOne repository. Whoever you work for (the
maintainer, or someone contributing from a fork), these hold here, and the
step-by-step flow with its commands is in
[DiluxOne/.github, `docs/agents.md`](https://github.com/DiluxOne/.github/blob/main/docs/agents.md):

1. **Nothing starts without an accepted issue.** Find the issue, or open one
   with the form that fits (it sets the issue's Type: Bug, Feature, Docs or
   Task), and wait until a maintainer adds the `accepted` label. Never add it
   yourself. The pull request says `Closes #<number>`; CI fails it otherwise.
   **The code is written in GitHub Actions, by the autopilot.** Nobody
   writes it on their own machine (not the maintainer, not their agents,
   not someone from a fork) unless they first claim the issue: comment
   `/claim` on it (or tick "I want to work on this myself" in its form),
   and the autopilot steps aside; a claim with no pull request is released
   after 10 days. Without a claim, never edit code locally: open
   or improve the issue, answer the autopilot's questions on its pull
   request, and let it work; when it stops, give it a hint and add
   `autopilot:continue`, never finish its pull request by hand.
2. **The pull request's type fits the issue's Type**: `feat` (or any `!`)
   closes a Feature, `fix` a Bug; other types close any accepted issue.
3. **Branch** `<type>/<number>-<short-kebab>`; **commit and title** as a
   Conventional Commit of 72 characters or fewer (CI rejects more than 100);
   bodies are plain paragraphs, never hard-wrapped; no `Claude-Session:`.
4. **Only after a claim, check before the pull request** with `make pre-pr`, every check the
   pull request and the merge queue run, in every repository (`dx check`
   runs it, then the local review), and open it (`dx pr`) only when the
   person you work for says so.
5. **Never** push to `main`, create or move a tag, or approve a release.
6. **Say AI took part** with one line at the end of what you write on GitHub:
   `🤖 AI-generated · <model> (<maker>)` when you wrote it,
   `🤖 AI-assisted · <model> (<maker>)` when a person did with your help.
   Never "Generated with …".
7. **Say what waits on whom, with its link.** When a step waits on a
   person, tell the maintainer the action and the full URL, one per line
   ("Add `accepted` to https://github.com/DiluxOne/<repo>/issues/<n>",
   "Approve and merge https://github.com/DiluxOne/<repo>/pull/<n>"), never
   "the issue needs accepting" alone. Someone working from a fork or a
   clone cannot accept, approve or merge: never ask them for a
   maintainer's step; tell them a maintainer will review it and answer
   soon, with the link to where it waits. A repository's part of an
   accepted issue is opened as a sub-issue of it, and needs no
   acceptance of its own. Ask for `accepted` only on an issue that
   passes the schema check: it carries `awaiting-acceptance`, not
   `incomplete` (`python3 scripts/issue-schema.py check < issue.md` in
   DiluxOne/.github says the same before you open or edit it).
8. **A finding is not a new issue.** Something you find along the way that
   the task does not need goes in one list, at the end of what you report,
   with what you recommend; the maintainer picks what becomes work. A
   change for the whole organisation is one issue in DiluxOne/.github,
   never one per repository.
9. **Meet the organisation's rules** before the review asks for them:
   [test first](https://github.com/DiluxOne/.github/blob/main/rules/test-first.md)
   and [no credentials in the front end](https://github.com/DiluxOne/.github/blob/main/rules/front-no-credentials.md).
   The model they belong to (types of work, gates, what merges on its own)
   is [DiluxOne/.github, `docs/model.md`](https://github.com/DiluxOne/.github/blob/main/docs/model.md).
10. **Who signs what.** A model is never a co-author: a commit written
   with its help carries `Assisted-by: <model> (<maker>)`, e.g.
   `Assisted-by: Claude Opus 5.5 (Anthropic)`, never a `Co-authored-by`
   that names a model (the conventions check refuses it). A person is a
   co-author, `Co-authored-by: Name <id+login@users.noreply.github.com>`
   (GitHub's noreply address, never a private e-mail), when they wrote
   commits of the pull request, opened the issue whose "Proposed
   solution" it used, proposed in a comment on the issue what it used,
   or claimed the issue and wrote code for it; `Suggested-by:` when their
   idea was used in part, `Reported-by:` when they reported it without a
   proposal that was used. Never a co-author: the maintainer who accepts
   or merges, dilux-bot, Dependabot, any bot, a model. List the people in
   the pull request's Credits block (`## 🙌 Credits`, one
   `- @login: co-author|suggested|reported (<link>)` per line); the merge
   writes their trailers, and a maintainer corrects the list with
   `/coauthor @login` and `/uncoauthor @login`.
<!-- dx:org:end -->
