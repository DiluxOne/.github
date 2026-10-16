# The organisation's rules

What every change must meet, whatever agent or person writes it: one file per rule, with a header the checks read. The model they belong to is in [docs/model.md](../docs/model.md); a rule here is what an agent meets before the review flags it.

These are not the review's catalogue of rejections: what a review sends back for one kind of project is an entry in its pack, `kinds/<kind>/rules.yml`, with its fixtures. A rule here holds for the whole organisation (or a role across kinds), and says in words what the code must do.

## The header

```markdown
---
id: test-first
level: mandatory
applies_to: {all: true}
enforced_by: [review]
---
What the rule asks, and why, in plain paragraphs.
```

| Field | What it says |
| --- | --- |
| `id` | The file's name without `.md`. |
| `level` | `mandatory`: no repository can leave it out. `standard`: a repository can leave it out in its policy, with the reason, and a maintainer merges that. |
| `applies_to` | `{all: true}`, or the `kinds` and the `roles` (such as `front` and `back`) it holds for: `{roles: [front]}`. |
| `enforced_by` | How it is held: `review` (the review reads it), or `check: <name>` for a deterministic check that holds it. A rule no check holds yet says `review` only. |

`python3 scripts/rules.py check` holds every file to this header, and checks that the organisation's block of `AGENTS.md` (`agents-block.md`) names every rule, so an agent in any repository reads them.

## The rules

| Rule | Level | Applies to |
| --- | --- | --- |
| [test-first](test-first.md) | mandatory | everything |
| [front-no-credentials](front-no-credentials.md) | mandatory | the front end |

A rule is added, changed or removed by a pull request a maintainer merges: like the autonomy policy, the rules never change on their own.
