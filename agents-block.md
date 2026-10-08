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
<!-- dx:org:end -->
