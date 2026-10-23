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
2. **The pull request's type fits the issue's Type**: `feat` (or any `!`)
   closes a Feature, `fix` a Bug; other types close any accepted issue.
3. **Branch** `<type>/<number>-<short-kebab>`; **commit and title** as a
   Conventional Commit of 72 characters or fewer (CI rejects more than 100);
   bodies are plain paragraphs, never hard-wrapped; no `Claude-Session:`.
4. **Check before the pull request** (`dx check`, or the repository's
   `make pre-pr`) and open it (`dx pr`) only when the person you work for
   says so.
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
<!-- dx:org:end -->
