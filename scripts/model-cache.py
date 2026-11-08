#!/usr/bin/env python3
"""No model call spent twice on the same question by an automatic re-run,
and what each run spent (#694).

The triage (issue-triage.yml) and the review (claude-review.yml) keep their
model's answer as an artifact of the run that asked (`model-answer-<key>`,
the Spec's option A: it touches nothing on GitHub that people read, and it
expires with the run's retention). An automatic re-run of that run (a
later attempt the bot started, never a person) on the same input, with the
same prompt and the same policy, downloads it and calls no model; a
person's re-run always calls the model. The key is the input (the head SHA
for a pull request, the body's hash for an issue), the prompt's hash (the
brief the model reads) and the policy's version (the model and its effort).

  model-cache.py key --input TEXT | --input-file FILE --prompt FILE ... --policy TEXT
        prints `key=<hex>`, for GITHUB_OUTPUT
  model-cache.py automatic
        prints `automatic=true` on an automatic re-run, else `automatic=false`:
        RUN_ATTEMPT past 1 and TRIGGERING_ACTOR a bot (a login ending in
        `[bot]`), or no TRIGGERING_ACTOR and the event's SENDER a bot
  model-cache.py save --dir DIR
        the answer (ANSWER, the model step's structured output) into
        DIR/answer.json, for the artifact
  model-cache.py reuse --dir DIR
        prints `hit=true` and the answer (`answer`, a multi-line output) when
        DIR/answer.json holds one, else `hit=false`
  model-cache.py summary --started EPOCH|ISO [--log [NAME=]FILE ...] [--title TEXT] [--reused]
        the run's cost as Markdown, for GITHUB_STEP_SUMMARY: its runner
        minutes since EPOCH (the job's start) and its model's tokens, from
        each execution file (claude-code-action's `execution_file`); a
        reused answer spent none
  model-cache.py --test
"""
import argparse
import hashlib
import json
import os
import secrets
import sys
import time

ANSWER = "answer.json"


def key(input_id, prompts, policy):
    """The cache key: the input, each prompt file's hash, and the policy's
    version. Pure."""
    h = hashlib.sha256()
    for part in [str(input_id)] + [hashlib.sha256(p).hexdigest() for p in prompts] + [str(policy)]:
        h.update(part.encode() + b"\0")
    return h.hexdigest()[:40]


def is_bot(login):
    return str(login or "").endswith("[bot]")


def automatic(attempt, triggering_actor, sender):
    """Whether this run is an automatic re-run, which may reuse the earlier
    answer: a later attempt (`attempt` past 1) the bot started. A person's
    re-run (a triggering actor who is not a bot) never is. Pure."""
    try:
        later = int(attempt or 1) > 1
    except ValueError:
        later = False
    if not later:
        return False
    if triggering_actor:
        return is_bot(triggering_actor)
    return is_bot(sender)


def reuse(directory):
    """The answer kept in `directory`, or None. A file that is not JSON is
    no answer: the model is called."""
    path = os.path.join(directory, ANSWER)
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        json.loads(text)
        return text.strip()
    except (OSError, ValueError):
        return None


def save(directory, answer):
    """`answer` kept in `directory`; False when it is no JSON (nothing is
    kept, so a re-run calls the model)."""
    try:
        json.loads(answer)
    except (TypeError, ValueError):
        return False
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, ANSWER), "w", encoding="utf-8") as fh:
        fh.write(answer)
    return True


def tokens(events):
    """The tokens an execution log spent, from its last `result` message:
    {input, output, cache_read, cache_write, cost}. Pure."""
    result = ([e for e in events if isinstance(e, dict) and e.get("type") == "result"] or [{}])[-1]
    usage = result.get("usage") or {}
    return {"input": int(usage.get("input_tokens") or 0), "output": int(usage.get("output_tokens") or 0),
            "cache_read": int(usage.get("cache_read_input_tokens") or 0), "cache_write": int(usage.get("cache_creation_input_tokens") or 0),
            "cost": float(result.get("total_cost_usd") or 0)}


def read_log(path):
    try:
        with open(path, encoding="utf-8") as fh:
            got = json.load(fh)
        return got if isinstance(got, list) else []
    except (OSError, ValueError):
        return []


def summary(started, now, logs, title="The run's cost", reused=False):
    """The run's cost as Markdown: runner minutes from `started` to `now`
    (epoch seconds) and the model's tokens of each log ({name: events}).
    Pure."""
    minutes = max(0.0, (now - started) / 60) if started else 0.0
    rows = [(name, tokens(events)) for name, events in logs.items()]
    total = {k: sum(t[k] for _, t in rows) for k in ("input", "output", "cache_read", "cache_write", "cost")}
    lines = [f"## {title}", "", f"- Runner minutes: {minutes:.1f}",
             f"- Model tokens: {total['input'] + total['output'] + total['cache_read'] + total['cache_write']} "
             f"(input {total['input']}, output {total['output']}, cache read {total['cache_read']}, cache write {total['cache_write']})"
             + (f", ${total['cost']:.2f}" if total["cost"] else "")]
    if reused:
        lines.append("- The model was not called: an automatic re-run reused the earlier answer.")
    elif not rows:
        lines.append("- The model was not called.")
    for name, t in rows:
        lines.append(f"  - {name}: input {t['input']}, output {t['output']}, cache read {t['cache_read']}, cache write {t['cache_write']}")
    return "\n".join(lines) + "\n"


def parse_start(value):
    """Epoch seconds, or an ISO time (`2026-11-08T10:00:00Z`); 0 when
    neither. Pure."""
    import datetime
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return 0.0


def output(name, value):
    """A GITHUB_OUTPUT line, multi-line safe."""
    if "\n" not in value:
        return f"{name}={value}\n"
    eof = f"DX_{secrets.token_hex(16)}"
    return f"{name}<<{eof}\n{value}\n{eof}\n"


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    k = key("abc", [b"brief"], "opus/high")
    check("C6: the key is the same for the same input, prompt and policy", key("abc", [b"brief"], "opus/high"), k)
    check("C6: another input, prompt or policy is another key",
          len({k, key("abd", [b"brief"], "opus/high"), key("abc", [b"brief2"], "opus/high"), key("abc", [b"brief"], "opus/max")}), 4)
    check("C6: an automatic re-run (a later attempt the bot started) reuses", automatic("2", "dilux-bot[bot]", "someone"), True)
    check("C6: a person's re-run calls the model, whoever sent the event", (automatic("2", "maintainer", "dilux-bot[bot]"), automatic("3", "someone", "someone")), (False, False))
    check("C6: a first attempt calls the model", (automatic("1", "dilux-bot[bot]", "dilux-bot[bot]"), automatic("", "", "")), (False, False))
    check("C6: a later attempt with no triggering actor reads the event's sender", (automatic("2", "", "dilux-bot[bot]"), automatic("2", "", "person")), (True, False))
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        answer = json.dumps({"category": "question", "reply": "Hi", "summary": "s", "language": "en"})
        check("C6: the model's answer is kept, and an automatic re-run reads it back", (save(d, answer), reuse(d)), (True, answer))
        check("C6: no answer kept is a call of the model", reuse(os.path.join(d, "none")), None)
        check("C6: an answer that is not JSON is never kept", save(os.path.join(d, "bad"), "not json"), False)
        with open(os.path.join(d, ANSWER), "w") as fh:
            fh.write("{broken")
        check("C6: a kept file that is not JSON is no answer", reuse(d), None)

        def flow(attempt, actor, kept):
            """What the workflow does: the model is called unless the run is
            automatic and an answer is kept. Returns the calls of the model."""
            calls = []
            directory = os.path.join(d, f"flow-{attempt}-{actor}-{kept}")
            if kept:
                save(directory, answer)
            got = reuse(directory) if automatic(attempt, actor, "") else None
            if got is None:
                calls.append("model")
            return calls
        check("C6: an automatic re-run with the earlier answer calls no model", flow("2", "dilux-bot[bot]", True), [])
        check("C6: a person's re-run calls the model, with an answer kept or not", (flow("2", "a-person", True), flow("2", "a-person", False)), (["model"], ["model"]))
        check("C6: an automatic re-run with no answer kept calls the model", flow("2", "dilux-bot[bot]", False), ["model"])
        log = os.path.join(d, "exec.json")
        with open(log, "w") as fh:
            json.dump([{"type": "assistant"}, {"type": "result", "total_cost_usd": 0.42,
                                               "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 300, "cache_creation_input_tokens": 5}}], fh)
        text = summary(1000, 1000 + 150, {"Classify": read_log(log)}, "The triage's cost")
        check("C6: the summary has the runner minutes and the model's tokens",
              ("Runner minutes: 2.5" in text, "Model tokens: 425 (input 100, output 20, cache read 300, cache write 5), $0.42" in text, "Classify: input 100" in text), (True, True, True))
        check("C6: a reused answer's summary says the model was not called, with no tokens",
              ("Model tokens: 0" in summary(1000, 1060, {}, reused=True), "not called: an automatic re-run reused" in summary(1000, 1060, {}, reused=True)), (True, True))
        check("C6: an unreadable log counts no tokens", read_log(os.path.join(d, "none.json")), [])
    check("summary: its start as epoch seconds or an ISO time", (parse_start("1000"), parse_start("1970-01-01T00:16:40Z"), parse_start("x")), (1000.0, 1000.0, 0.0))
    check("output: a multi-line value is a heredoc", (output("a", "x"), output("a", "x\ny").startswith("a<<DX_")), ("a=x\n", True))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for wf, steps in (("issue-triage.yml", ("model-cache.py automatic", "model-cache.py reuse", "model-cache.py save", "model-cache.py summary")),
                      ("claude-review.yml", ("model-cache.py automatic", "model-cache.py reuse", "model-cache.py save", "model-cache.py summary")),
                      ("autopilot.yml", ("model-cache.py summary",))):
        text = open(os.path.join(root, ".github", "workflows", wf), encoding="utf-8").read()
        check(f"C6: {wf} runs {', '.join(steps)}", [s for s in steps if s not in text], [])
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    p = argparse.ArgumentParser(prog="model-cache.py")
    p.add_argument("mode", choices=("key", "automatic", "save", "reuse", "summary"))
    p.add_argument("--input", default=None)
    p.add_argument("--input-file", default=None)
    p.add_argument("--prompt", action="append", default=[])
    p.add_argument("--policy", default="")
    p.add_argument("--dir", default="")
    p.add_argument("--started", default="")
    p.add_argument("--log", action="append", default=[])
    p.add_argument("--title", default="The run's cost")
    p.add_argument("--reused", action="store_true")
    a = p.parse_args(argv)
    if a.mode == "key":
        if a.input_file:
            with open(a.input_file, "rb") as fh:
                input_id = hashlib.sha256(fh.read()).hexdigest()
        else:
            input_id = a.input or ""
        prompts = []
        for path in a.prompt:
            try:
                with open(path, "rb") as fh:
                    prompts.append(fh.read())
            except OSError:
                prompts.append(b"")
        sys.stdout.write(output("key", key(input_id, prompts, a.policy)))
        return 0
    if a.mode == "automatic":
        auto = automatic(os.environ.get("RUN_ATTEMPT"), os.environ.get("TRIGGERING_ACTOR"), os.environ.get("SENDER"))
        sys.stdout.write(output("automatic", "true" if auto else "false"))
        return 0
    if a.mode == "save":
        if not save(a.dir, os.environ.get("ANSWER") or ""):
            print("::warning::the model's answer is no JSON: nothing is kept, a re-run calls the model.", file=sys.stderr)
            return 1
        return 0
    if a.mode == "reuse":
        got = reuse(a.dir)
        sys.stdout.write(output("hit", "true" if got else "false") + (output("answer", got) if got else ""))
        return 0
    started = parse_start(a.started)
    logs = {}
    for item in a.log:
        name, _, path = item.rpartition("=") if "=" in item else ("", "", item)
        if path and os.path.exists(path):
            logs[name or os.path.basename(path)] = read_log(path)
    sys.stdout.write(summary(started, time.time(), logs, a.title, a.reused))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
