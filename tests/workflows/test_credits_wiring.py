"""Who signs what (#491): every way a pull request merges writes the body
scripts/credits.py composes (the description, then the Credits block's
people and the commits' human co-authors), never one of its own."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CREDITS = 'body=$(python3 "$RUNNER_TEMP/central/scripts/credits.py" body "$GITHUB_REPOSITORY" "$PR")'


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def steps(name, job):
    return workflow(name)["jobs"][job]["steps"]


def merges(run):
    return [l.strip() for l in run.split("\n") if re.search(r"gh pr merge .*--body", l)]


def test_every_auto_merge_path_passes_the_credits_body():
    """C4: the merge queue squashes with the body given to --auto; every
    step that enables it (the autopilot's, a revert's, a release's, a sync
    run's and the usual decision) composes that body through credits.py,
    and nothing else writes co-authors."""
    seen = 0
    for step in steps("auto-merge.yml", "decide"):
        run = step.get("run", "")
        for line in merges(run):
            seen += 1
            assert '--body "$body"' in line, (step.get("name"), line)
            before = run[: run.index(line)]
            assert before.rfind(CREDITS) > before.rfind("body=$(gh "), step.get("name")
            assert CREDITS in before, step.get("name")
    assert seen == 5
    text = (ROOT / ".github/workflows/auto-merge.yml").read_text(encoding="utf-8")
    assert "grep -iE '^co-authored-by:'" not in text


def test_the_usual_decision_has_the_central_scripts_and_disables_first():
    step = next(s for s in steps("auto-merge.yml", "decide") if s.get("name") == "Enable or disable")
    run = step["run"]
    assert step["env"]["CENTRAL_REF"] == "${{ inputs.central-ref || job.workflow_sha }}"
    # Off before the body is read: a read that fails leaves nothing set to
    # merge with an old body.
    assert run.index("--disable-auto") < run.index(CREDITS) < run.index("--auto ${METHOD")
    assert run.index('fetch -q --depth 1 https://github.com/DiluxOne/.github "$CENTRAL_REF"') < run.index(CREDITS)


def test_the_hand_squash_passes_the_credits_body():
    """C4: scripts/squash-merge.sh, the maintainer's direct squash, is the
    same call, with the maintainer who merges as the one never credited."""
    text = (ROOT / "scripts/squash-merge.sh").read_text(encoding="utf-8")
    assert 'body=$(python3 "$here/credits.py" body "$repo" "$pr" "$merger")' in text
    assert "merger=$(gh api user --jq .login)" in text
    assert 'gh pr merge "$pr" --repo "$repo" --squash --delete-branch --body "$body"' in text
    assert "co-authored-by" not in text.lower().replace("co-authors", "")


def test_coauthor_runs_only_for_a_maintainer_and_comments_the_change():
    """C5: `/coauthor @login` and `/uncoauthor @login` on a pull request edit
    its Credits block, only for someone with the maintain or admin role (the
    repository's answer, never author_association), with the central script
    and none of the pull request's code, and the bot says what changed."""
    wf = workflow("review-reply.yml")
    job = wf["jobs"]["credits"]
    cond = " ".join(job["if"].split())
    assert "github.event_name == 'issue_comment'" in cond and "github.event.issue.pull_request" in cond
    assert "startsWith(github.event.comment.body, '/coauthor')" in cond and "startsWith(github.event.comment.body, '/uncoauthor')" in cond
    who = next(s for s in job["steps"] if s.get("id") == "who")
    # Who decides (#588): scripts/deciders.py, within maintain or admin.
    assert 'deciders.py may credits "$LOGIN"' in who["run"] and "write)" not in who["run"]
    assert "author_association" not in str(job)
    checkouts = [s for s in job["steps"] if "actions/checkout" in s.get("uses", "")]
    assert [c["with"]["repository"] for c in checkouts] == ["DiluxOne/.github"]
    edit = next(s for s in job["steps"] if s.get("name") == "Correct the Credits block")
    assert edit["if"] == "steps.who.outputs.ok == 'true'"
    assert edit["env"]["COMMENT"] == "${{ github.event.comment.body }}" and "${{" not in edit["run"]
    assert 'python3 .dx-central/scripts/credits.py command "$LOGIN"' in edit["run"]
    assert 'gh api -X PATCH "repos/$GITHUB_REPOSITORY/pulls/$PR" -F body=@"$RUNNER_TEMP/new.md"' in edit["run"]
    assert 'gh pr comment "$PR"' in edit["run"]
    # The token only writes pull requests; it reads what decides (#588).
    bot = next(s for s in job["steps"] if s.get("id") == "bot")
    assert {k: v for k, v in bot["with"].items() if k.startswith("permission-")} == {"permission-pull-requests": "write", "permission-contents": "read", "permission-issues": "read"}


def test_a_credits_command_wakes_neither_the_reply_nor_the_autopilot():
    wf = workflow("review-reply.yml")
    for name in ("answer", "reply"):
        cond = " ".join(wf["jobs"][name]["if"].split())
        assert "!startsWith(github.event.comment.body, '/coauthor')" in cond, name
        assert "!startsWith(github.event.comment.body, '/uncoauthor')" in cond, name


def test_the_command_writes_the_block_and_says_what_changed(tmp_path):
    import os
    import subprocess
    out = tmp_path / "new.md"
    body = "## 📝 What changes\n\nx\n\n## 🧪 How I tested it\n\ny\n"
    run = subprocess.run(["python3", str(ROOT / "scripts/credits.py"), "command", "boss", str(out)], input=body, capture_output=True, text=True,
                         env=dict(os.environ, COMMENT="/coauthor @ana\n/uncoauthor @zed"), check=True)
    assert run.stdout.splitlines() == ["- @ana is a co-author now.", "- @zed was not in the Credits block."]
    assert "<!-- dx-credits -->\n- @ana: co-author (/coauthor by @boss)\n<!-- /dx-credits -->" in out.read_text(encoding="utf-8")


def test_every_repository_reads_the_same_who_signs_what():
    """C7: the organisation's AGENTS.md block, which `sync-repos.py files`
    writes into every repository, carries the rule, and this repository's
    AGENTS.md holds it as that sync writes it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_repos", ROOT / "scripts/sync-repos.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    block = (ROOT / "agents-block.md").read_text(encoding="utf-8")
    rule = " ".join(block.split("**Who signs what.**", 1)[1].split("<!-- dx:org:end -->", 1)[0].split())
    for said in ("A model is never a co-author", "`Assisted-by: <model> (<maker>)`", "`Assisted-by: Claude Opus 5.5 (Anthropic)`",
                 "Co-authored-by: Name <id+login@users.noreply.github.com>", "never a private e-mail", "`Suggested-by:`", "`Reported-by:`",
                 "Never a co-author: the maintainer who accepts or merges, dilux-bot, Dependabot, any bot, a model", "`/coauthor @login`"):
        assert said in rule, said
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert sync.with_block(agents, block) == agents
    assert block.rstrip("\n") in agents


def test_the_texts_no_longer_ask_for_a_model_as_co_author():
    for path in ("CONTRIBUTING.md", "docs/agents.md", "agents-block.md", "scripts/autopilot.py"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "Co-Authored-By:` is fine" not in text and "`Co-Authored-By:` trailer is fine" not in text, path
    prompts = (ROOT / "scripts/autopilot.py").read_text(encoding="utf-8")
    assert 'ending with "Co-Authored-By: Claude' not in prompts and '"Co-Authored-By: Claude <noreply@anthropic.com>")' not in prompts
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "### Who signs what" in contributing and "Co-authored-by: Ana Pérez <1234+ana@users.noreply.github.com>" in contributing
    template = (ROOT / "pull_request_template.md").read_text(encoding="utf-8")
    assert "## 🙌 Credits" in template and "<!-- dx-credits -->\n<!-- /dx-credits -->" in template
    assert "Credits block" in (ROOT / "review-profiles/general.md").read_text(encoding="utf-8")


def test_the_attribution_switch_comes_from_the_organisation_and_starts_at_warn():
    """C1's switch: the conventions check reads org.yml `attribution`
    through org.py, never the pull request's, and it starts at warn."""
    all_steps = steps("conventions.yml", "conventions")
    names = [s.get("name") for s in all_steps]
    mode = next(s for s in all_steps if s.get("id") == "attribution")
    assert 'mode=$(python3 .dx-central/scripts/org.py attribution)' in mode["run"]
    check = next(s for s in all_steps if s.get("name") == "Check branch, title and commits")
    assert check["env"]["ATTRIBUTION"] == "${{ steps.attribution.outputs.mode }}"
    assert names.index("Checkout the conventions script") < names.index(mode["name"]) < names.index(check["name"])
    assert yaml.safe_load((ROOT / "org.yml").read_text(encoding="utf-8"))["attribution"] == "warn"
