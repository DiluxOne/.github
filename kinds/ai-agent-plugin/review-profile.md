# Review profile: plugin for coding agents (kind `ai-agent-plugin`)

For plugins wired into coding agents (Claude Code, Codex, Copilot, Cursor,
Gemini, OpenCode) and published in the organisation's catalog
(org.yml `catalogs`). A plugin runs on the machine of whoever installs it:
its hooks on every tool call, its skills, agents and commands as what the
agent is told to do. What a script can check is a rule in `rules.yml` beside
this file, run on every pull request (`Review rules (ai-agent-plugin)`), and
the manifests are held to each other by `scripts/agent-manifests.py check`;
this profile is for what only reading can find.

## Hooks and the commands a plugin installs

- **A hook does only what its name says, inside the project.** It reads the
  event the tool hands it and the project's files; it writes only to the
  project (its own state directory) or to the data directory the tool gives
  the plugin. Writing to the home directory, the shell's profile, another
  tool's settings or the system is a blocker, whatever the reason.
- **No download runs.** A hook, a skill or a command that fetches a script
  and runs it (`curl … | sh`, `bash <(curl …)`, `npx some-package@latest`
  with no pinned version) runs code nobody reviewed on every user's
  machine. What runs ships in the plugin, pinned.
- **A hook fails closed or says so.** A gate that exits 0 when its own
  check could not run (a missing `jq`, a parse error) enforces nothing:
  each failure path either blocks with a message or is named in the
  plugin's docs as a known gap.
- **Paths come from the tool's variables** (`${CLAUDE_PLUGIN_ROOT}`,
  `${CLAUDE_PROJECT_DIR}`, the equivalents of each tool), quoted; never a
  path built from the event's text without checking it stays inside the
  project.
- **The event's text is data.** A hook never passes a prompt, a file's
  content or a tool's argument to `eval`, `sh -c` or a command line
  unquoted.

## What the plugin asks the agent to run

- **No privileged commands.** A skill, an agent or a command never tells the
  agent to use `sudo`, change system settings or install software globally;
  what needs it is a step for a person, in the README.
- **No instruction to skip a check.** A skill never tells the agent to pass
  `--no-verify`, turn off a hook, push to a protected branch or approve its
  own work.
- **Destructive commands are named and scoped.** `rm -rf`, `git reset
  --hard`, `git push --force` appear only with an explicit path or ref the
  plugin owns, and the skill says when the agent asks the person first.

## Credentials

- **No credential anywhere in the plugin**: not in a manifest, a hook, a
  skill, an example or a test fixture that ships. What needs one reads it
  from the user's environment at run time, by name
  (rules/front-no-credentials.md: a plugin is a client the user controls).
- **Nothing the plugin collects leaves the machine** unless its README says
  what, where and why, and the user turns it on.

## The manifests of every tool

- **Every tool's manifest agrees** on the plugin's name, version and
  description (kinds/ai-agent-plugin/tools.yml lists them); the check fails
  when two disagree, but read the other fields too: a hook file one tool's
  manifest names and another's does not, or a skills path that exists for
  one tool only, is a plugin that behaves differently per tool.
- **A tool is declared only when the plugin works there**: its manifest,
  its hooks in that tool's dialect, and a line in the README on how to
  install it there.
- **The version is the release's.** A change that bumps it bumps it in every
  manifest at once, and the changelog says what changed.
