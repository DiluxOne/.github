# AGENTS.md

Rules for any coding agent working in `DiluxOne/.github`.

- This repository defines how every DiluxOne repository is checked, reviewed,
  merged and released. A mistake here reaches all of them at once. Every change
  is high risk and is merged by a human.
- Workflows are reusable (`on: workflow_call`) unless they are specific to this
  repository. Name them after what they do; add a stack suffix (`-wp`) only
  when the steps are stack-specific.
- Pin every third-party action to a full commit SHA with the version in a
  comment (`uses: owner/action@<sha> # vX.Y.Z`). Declare the minimum
  `permissions:`. Pass untrusted text (titles, branch names) through `env:`,
  never `${{ }}` inside a `run:` script.
- Nothing that runs with secrets may run on a fork's code.
- Branches, PR titles and commits follow Conventional Commits; CI enforces it.
  PR descriptions use the template sections (What changes and Why are
  required); commit and PR bodies are plain paragraphs, never hard-wrapped.
- When you write a pull request, issue or comment, end it with the AI line from
  CONTRIBUTING.md ("Saying that AI was involved"), e.g.
  `🤖 AI-generated · Claude Opus 5.5 (Anthropic)`. Never "Generated with …".
- Never push to `main`, create or move tags, or change organisation settings.
- Keep `README.md`, `CONTRIBUTING.md`, the review profiles, the workflow
  templates and the workflow header comments in step with what the workflows
  do, in the same PR.
