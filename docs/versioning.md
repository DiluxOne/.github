# Versioning the engine

What a version of this repository means for whoever calls its workflows, and how one is made. The products' own versions (a plugin's `X.Y.Z`, decided by the labels of what merged) are in [CONTRIBUTING.md](../CONTRIBUTING.md#how-a-change-becomes-a-version); this page is about the engine: the reusable workflows, the scripts and policy they run, the kinds and the workflow templates.

## What each part of a version means

Every version is a tag `vX.Y.Z` (on `main`, or on an older major's line for a patch there), a GitHub Release with its notes, and an entry in [CHANGELOG.md](../CHANGELOG.md). The question is always the caller's: does a repository that calls these workflows have to change anything to keep working?

| Part | When | Examples |
| --- | --- | --- |
| **Major** `X.0.0` | A caller must change something | A new required input or secret; an input, output, workflow or script a caller names, removed or renamed; more permissions the caller must grant; a policy key removed; a default that now refuses a configuration it accepted |
| **Minor** `X.Y.0` | Something new a caller may use, or a check that catches more of what it was always meant to stop, with nothing to change | A new workflow, script, kind or optional input or secret; a gate that now finds a case it missed |
| **Patch** `X.Y.Z` | A fix, with no new capability | A bug fixed, a message, docs |

A breaking change is said in its commit (`!`), so the changelog lists it first; a minor before it announces it when it can.

## Which version a caller runs

- **This organisation's repositories** call `@v5`: a moving tag that points at the last `v5.Y.Z`. Their callers are kept in step by `scripts/sync-repos.py`, so a change their callers need ships with the callers changed. Moving it is a release to every repository at once: it moves only once a change ran end to end in the sandbox, and always as a lightweight tag (an annotated one breaks the organisation's required workflow).
- **Any other organisation** pins a full commit SHA, with the version in a comment: `uses: DiluxOne/.github/.github/workflows/<name>.yml@<sha> # v5.25.0`. Dependabot (the `github-actions` ecosystem) proposes the next version as a pull request, with its release notes, and they merge it when they choose. A major never reaches them on its own.

## How a version is made

1. The pull request that releases it rebuilds the changelog with the version: `python3 scripts/changelog.py build --next vX.Y.Z > CHANGELOG.md`.
2. Once it merges and `main` is green, an administrator tags that commit `vX.Y.Z`.
3. The tag's push publishes its GitHub Release, with the notes of that version (`engine-release.yml`, `scripts/changelog.py notes`). The notes are read from git at the tag, so they hold everything in it; the changelog the pull request wrote catches up at the next rebuild if something merged after it.
4. When it is to reach this organisation's repositories, `v5` moves to it.
