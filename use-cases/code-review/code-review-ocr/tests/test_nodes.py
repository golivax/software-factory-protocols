"""One MR through every code node, the prompt rendering and the poster.

The MR is the oracle's change set (a Go handler gaining a lock, a Python fix, a
TypeScript eval, a rename, a deletion, a binary, a secret file, a vendored
file, a test file, …), checked out at its head as a `checkout` node sees it.
The agents' answers are written here, as a review agent would answer; every
code node runs for real, as the factory runs it (sf_protocol_kit.run_node).
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import pytest
from sf_protocol_kit import run_node

PKG = pathlib.Path(__file__).resolve().parents[1]
WF = PKG / "workflows"
GOLDEN = PKG / "tests" / "golden"


def _gen_cases():
    spec = importlib.util.spec_from_file_location("gen_cases", GOLDEN / "oracle" / "gen_cases.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mr(tmp_path_factory):
    gen = _gen_cases()
    repo = tmp_path_factory.mktemp("repo")
    _, base, head = gen.build_repo(str(repo))
    diff = gen.git(str(repo), "diff", base, head).decode("utf-8", "surrogateescape")
    files = gen.git(str(repo), "diff", "--name-only", base, head).decode().split()
    return {"repo": str(repo), "diff": diff, "files": files,
            "pr": {"number": 7, "title": "t", "body": "", "head_sha": head, "base_sha": base}}


def node(name, tmp_path, mr, inputs, params=None, inputs_ctx=None, env=None):
    ctx = {"pr": "7", "protocol_inputs": inputs_ctx or {}}
    if params:
        ctx["params"] = params
    workdir = tmp_path / f"{name.removesuffix('.py')}-{len(list(tmp_path.glob(name.removesuffix('.py') + '-*')))}"
    ev, _ = run_node(WF / name, workdir, inputs, ctx=ctx,
                     env={"GITHUB_WORKSPACE": mr["repo"], **(env or {})},
                     diff=mr["diff"], files=mr["files"], pr=mr["pr"])
    return ev


def render(task, tmp_path, mr, inputs):
    """agent_prompt.py as an agent job's step runs it: inputs under the
    workspace, the snapshot at $SF_SUBJECT_DIR."""
    ws = tmp_path / f"ws-{task}-{len(list(tmp_path.glob('ws-*')))}"
    (ws / "inputs").mkdir(parents=True)
    for alias, doc in inputs.items():
        (ws / "inputs" / f"{alias}.json").write_text(json.dumps(doc))
    subject = ws / ".sf-subject"
    subject.mkdir()
    (subject / "diff.patch").write_text(mr["diff"])
    (subject / "pr.json").write_text(json.dumps(mr["pr"]))
    out = ws / "agent"
    r = subprocess.run([sys.executable, str(WF / "agent_prompt.py"), task, str(out)], capture_output=True,
                       text=True, env={**os.environ, "GITHUB_WORKSPACE": str(ws), "SF_SUBJECT_DIR": str(subject)})
    return r, out


# -- select ----------------------------------------------------------------------

def test_select_applies_upstreams_gates(tmp_path, mr):
    ev = node("select.py", tmp_path, mr, {})
    reasons = {e["path"]: e["reason"] for e in ev["excluded"]}
    assert reasons["img/logo.png"] == "binary"
    assert reasons[".env"] == "secret_exclude"
    assert reasons["svc/handler_test.go"] == "default_path"
    assert reasons["vendor/lib/x.go"] == "provider_directory"
    assert reasons["notes.weird"] == "unsupported_ext"
    assert reasons["docs/remove_me.md"] == "unsupported_ext"   # the gates run before the deletion check
    assert reasons[".env.example"] == "unsupported_ext"          # a template, not a secret
    assert "api/vendor/y.go" not in ev["selected"]
    assert ev["strategy"] == "llm"                     # more than GROUPING_MIN_FILES files
    assert ev["file_list"].startswith("[0] ADDED   Makefile (+2/-0)\n[1] RENAMED   app/new_name.py (+1/-1)\n")


def test_select_reads_the_repositorys_rule_json(tmp_path, mr):
    rules = pathlib.Path(mr["repo"]) / ".opencodereview" / "rule.json"
    rules.parent.mkdir()
    rules.write_text(json.dumps({"include": ["**/*.weird"], "exclude": ["app/**"]}))
    try:
        ev = node("select.py", tmp_path, mr, {})
    finally:
        rules.unlink()
        rules.parent.rmdir()
    assert "notes.weird" in ev["selected"]
    assert not [p for p in ev["selected"] if p.startswith("app/")]


def test_a_snapshot_without_a_base_fails_the_node(tmp_path, mr):
    bad = {**mr, "pr": {**mr["pr"], "base_sha": ""}}
    with pytest.raises(AssertionError, match="could not compute"):
        node("select.py", tmp_path, bad, {})


# -- the whole flow --------------------------------------------------------------

@pytest.fixture
def flow(tmp_path, mr):
    select = node("select.py", tmp_path, mr, {})
    idx = {p: i for i, p in enumerate(select["selected"])}
    grouping = {"groups": [{"label": "service", "files": [idx["svc/handler.go"], idx["src/üñí/naïve file.go"]]},
                           {"label": "web", "files": [idx["web/index.ts"], 999]}]}
    partition = node("partition.py", tmp_path, mr, {"select": select, "grouping": grouping})
    return tmp_path, mr, select, partition


def test_partition_follows_the_grouping_answer(flow):
    _, _, select, partition = flow
    groups = {g["label"]: g["files"] for g in partition["groups"]}
    assert groups["service"] == ["svc/handler.go", "src/üñí/naïve file.go"]
    assert groups["web"] == ["web/index.ts"]
    named = {f for g in partition["groups"] for f in g["files"]}
    assert named == set(select["selected"])            # a file no group names gets its own
    assert [g["id"] for g in partition["groups"]][:2] == ["g001", "g002"]


def test_a_failed_grouping_falls_back_to_one_group_per_file(tmp_path, mr):
    select = node("select.py", tmp_path, mr, {})
    part = node("partition.py", tmp_path, mr, {"select": select})
    assert [g["files"] for g in part["groups"]] == [[p] for p in select["selected"]]
    assert part["warnings"][0]["type"] == "grouping_failed"


def test_one_group_end_to_end(flow):
    tmp_path, mr, select, partition = flow
    group = next(g for g in partition["groups"] if g["label"] == "service")
    prepare = node("prepare.py", tmp_path, mr, {"select": select, "group": group},
                   inputs_ctx={"effort": "high", "language": "Chinese", "background": "Adds a lock"})
    assert prepare["key"] == "src/üñí/naïve file.go,svc/handler.go"
    assert prepare["rounds"] == 3 and prepare["plan"] is False   # 24 changed lines: under both thresholds
    assert "#### " in prepare["system_rule"] and "<rules for=" not in prepare["system_rule"]

    r, out = render("review", tmp_path, mr, {"select": select, "prepare": prepare})
    assert r.returncode == 0, r.stderr
    prompt = (out / "ocr-prompt.md").read_text()
    assert "Always respond in Chinese." in prompt and "Adds a lock" in prompt
    assert '<file path="svc/handler.go">' in prompt and "### Review Plan" not in prompt
    assert "### Previously Confirmed Findings" not in prompt
    assert (out / "ocr_tools.py").is_file()
    for name in ("task_done", "code_comment", "code_search", "file_read", "file_read_diff", "file_find"):
        tool = out / f"ocr-tool-{name}.json"
        assert json.loads(tool.read_text())["name"] == name and tool.stat().st_size <= 6000
    # an agent CLI truncates a long output: the parts are what the agent reads
    n = int((out / "ocr-prompt.parts").read_text())
    chunks = [(out / f"ocr-prompt.part-{i:03d}.md").read_text() for i in range(1, n + 1)]
    assert n > 1 and "".join(chunks) == prompt
    assert all(len(c.encode()) <= 6000 for c in chunks)

    review = {"state": "DONE", "comments": [
        {"path": "svc/handler.go", "content": "The lock does not cover the map's creation.",
         "existing_code": "mu.Lock()\ncache[id] = name\nmu.Unlock()", "suggestion_code": None,
         "category": "bug", "severity": "medium"},
        {"path": "svc/handler.go", "content": "eval on input is code execution.",
         "existing_code": "export function g(s: string) { return eval(s); }",
         "suggestion_code": "return JSON.parse(s);",
         "category": "security", "severity": "critical"},
        {"path": "src/üñí/naïve file.go", "content": "F's result is a constant.",
         "existing_code": "func F() int {  return 1  }", "suggestion_code": None,
         "category": "style", "severity": "Low"},
        {"path": "svc/handler.go", "content": "", "existing_code": "x", "suggestion_code": None,
         "category": "bug", "severity": "low"}]}
    locate = node("locate.py", tmp_path, mr, {"select": select, "prepare": prepare, "review": review})
    placed = locate["comments"]
    assert len(placed) == 3                                  # an empty comment is dropped
    assert (placed[0]["start_line"], placed[0]["end_line"]) == (17, 19)
    assert placed[1]["path"] == "web/index.ts"               # re-filed to the one file holding its code
    assert locate["warnings"][0]["type"] == "comment_refiled"
    assert placed[2]["severity"] == "low" and placed[2]["start_line"] == 0
    assert [r["index"] for r in locate["relocations"]] == [2]

    r, out = render("relocate", tmp_path, mr, {"select": select, "relocation": locate["relocations"][0]})
    assert r.returncode == 0, r.stderr
    assert "func F() int {  return 1  }" in (out / "ocr-prompt.md").read_text()
    rows = [{"leg_id": "x", "key": locate["relocations"][0]["id"], "state": "done",
             "evidence": {"response": "```go\nfunc F() int { return 1 }\n```"}}]
    settle = node("settle.py", tmp_path, mr, {"select": select, "prepare": prepare, "locate": locate,
                                               "relocations": rows})
    assert settle["comments"][2]["start_line"] == 3
    assert settle["candidates"] == [0, 2] and settle["filter"] is True   # group order; web/index.ts is not in it

    r, out = render("filter", tmp_path, mr, {"select": select, "prepare": prepare, "settle": settle})
    assert r.returncode == 0, r.stderr
    filt_prompt = (out / "ocr-prompt.md").read_text()
    assert '"id":"c-1","path":"src/üñí/naïve file.go"' in filt_prompt

    answer = {"tool": "report_incorrect_comments", "analysis": ["c-1: F is not constant-folded"],
              "comment_ids": ["c-1", "c-9", "bogus"]}
    c1 = node("confirm.py", tmp_path, mr, {"prepare": prepare, "settle": settle, "filter": answer},
              params={"round": 1})
    assert [c["path"] for c in c1["confirmed"]] == ["svc/handler.go"]
    assert [c["path"] for c in c1["comments"]] == ["svc/handler.go", "web/index.ts"]
    assert c1["continue"] is True

    r, out = render("review", tmp_path, mr, {"select": select, "prepare": prepare, "previous": c1})
    assert "<confirmed_findings>\n1. svc/handler.go\n   code: mu.Lock() cache[id] = name mu.Unlock()" in \
        (out / "ocr-prompt.md").read_text()

    # Round 2's agent failed: its locate sees no review, its group keeps round 1.
    locate2 = node("locate.py", tmp_path, mr, {"select": select, "prepare": prepare})
    settle2 = node("settle.py", tmp_path, mr, {"select": select, "prepare": prepare, "locate": locate2,
                                                "relocations": []})
    c2 = node("confirm.py", tmp_path, mr, {"prepare": prepare, "settle": settle2, "previous": c1},
              params={"round": 2})
    assert c2["continue"] is False and c2["comments"] == c1["comments"]
    assert c2["warnings"][-1]["type"] == "review_round_failed"
    collected = node("collect.py", tmp_path, mr, {"prepare": prepare, "round-1": c1, "round-2": c2})
    assert collected["comments"] == c1["comments"]

    calls, ev = post(tmp_path, mr, select, partition, [
        {"leg_id": "a", "key": "g001", "state": "done", "evidence": collected},
        {"leg_id": "b", "key": "g002", "state": "done", "evidence": {"comments": [], "warnings": []}}])
    assert ev["conclusion"] == "success"
    review_calls = [c for c in calls if "/reviews" in c["argv"][3]]
    assert len(review_calls) == 1
    body = json.loads(review_calls[0]["stdin"])
    assert body["event"] == "COMMENT" and body["commit_id"] == mr["pr"]["head_sha"]
    assert body["body"].startswith("<!-- ocr-review-run:")
    inline = {c["path"]: c for c in body["comments"]}
    assert inline["svc/handler.go"]["start_line"] == 17 and inline["svc/handler.go"]["line"] == 19
    assert inline["svc/handler.go"]["side"] == "RIGHT"
    assert "![bug · medium](https://img.shields.io/badge/bug-medium-orange)" in inline["svc/handler.go"]["body"]
    assert "**Suggestion:**\n```suggestion\nreturn JSON.parse(s);\n```" in inline["web/index.ts"]["body"]
    summaries = [json.loads(c["stdin"])["body"] for c in calls if "/comments" in c["argv"][3] and c["stdin"]]
    final = summaries[-1]
    assert final.startswith("<!-- ocr-summary -->\n<!-- ocr-summary-run:")
    assert "🔍 **OpenCodeReview** found **2** issue(s) in this PR." in final
    assert "- ✅ Successfully posted inline: 2 comment(s)" in final
    assert "(`review_round_failed`): round 2: the review agent failed" in final


def test_task_done_failed(tmp_path, mr):
    """RunMainTask's `task failed`: round 1 fails the group's files, a later
    round keeps what it filed, unfiltered, and warns."""
    prepare = {"key": "a.go", "files": ["a.go"], "rounds": 3}
    filed = [{"path": "a.go", "content": "c", "existing_code": "x", "start_line": 0, "end_line": 0}]
    settle = {"ran": True, "state": "FAILED", "comments": filed, "candidates": [0], "filter": False}
    first = node("confirm.py", tmp_path, mr, {"prepare": prepare, "settle": settle}, params={"round": 1})
    assert first["failure"]["class"] == "provider" and first["continue"] is False
    previous = {"confirmed": [], "comments": [{"path": "a.go", "content": "earlier"}], "warnings": []}
    later = node("confirm.py", tmp_path, mr, {"prepare": prepare, "settle": settle, "previous": previous},
                 params={"round": 2})
    assert "failure" not in later and later["continue"] is False
    assert [c["content"] for c in later["comments"]] == ["earlier", "c"]
    assert later["warnings"][-1]["message"] == "round 2: task failed: task_done reported FAILED"
    collected = node("collect.py", tmp_path, mr, {"prepare": prepare, "round-1": first})
    assert collected["failure"]["class"] == "provider"


def test_the_next_rounds_prompt_budget_stops_the_group(tmp_path, mr):
    """checkPromptBudget before round 2, on a template whose MAX_TOKENS is tiny."""
    import shutil
    wf = tmp_path / "wf"
    shutil.copytree(WF, wf)
    tpl_file = wf / "ocr" / "upstream" / "task_template.json"
    tpl = json.loads(tpl_file.read_text())
    tpl["MAX_TOKENS"] = 2000
    tpl_file.write_text(json.dumps(tpl))
    select = node("select.py", tmp_path, mr, {})
    prepare = {"key": "svc/handler.go", "files": ["svc/handler.go"], "rounds": 2, "date": "d",
               "system_rule": "r" * 9000, "language": "English"}
    settle = {"ran": True, "state": "DONE", "candidates": [0], "filter": False,
              "comments": [{"path": "svc/handler.go", "content": "c", "existing_code": "x"}]}
    ev, _ = run_node(wf / "confirm.py", tmp_path / "confirm-budget",
                     {"select": select, "prepare": prepare, "settle": settle},
                     ctx={"pr": "7", "params": {"round": 1}}, env={"GITHUB_WORKSPACE": mr["repo"]},
                     diff=mr["diff"], files=mr["files"], pr=mr["pr"])
    assert ev["continue"] is False
    assert ev["warnings"][-1]["type"] == "token_threshold_exceeded"
    assert ev["warnings"][-1]["message"].endswith("exceed 80% of max_tokens(2000) [round 2]")


# -- post ------------------------------------------------------------------------

FAKE_GH = '''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
stdin = sys.stdin.read() if "--input" in argv else ""
with open(os.environ["FAKE_GH_LOG"], "a") as f:
    f.write(json.dumps({"argv": argv, "stdin": stdin}) + "\\n")
method, path = argv[2], argv[3]
fail = os.environ.get("FAKE_GH_FAIL", "")
if fail and fail in path:
    sys.stderr.write("HTTP 422: Unprocessable Entity\\n")
    sys.exit(1)
if method == "GET":
    print(os.environ.get("FAKE_GH_COMMENTS", "[]"))
else:
    print(json.dumps({"id": 41, "html_url": "u"}))
'''


def post(tmp_path, mr, select, partition, rows, env=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.unlink(missing_ok=True)
    log.touch()
    ev = node("post_review.py", tmp_path, mr, {"select": select, "partition": partition, "groups": rows},
              env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_GH_LOG": str(log),
                   "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "9", **(env or {})})
    return [json.loads(line) for line in log.read_text().splitlines()], ev


def test_no_findings_posts_only_the_sticky_summary(flow):
    tmp_path, mr, select, partition = flow
    existing = json.dumps([{"id": 5, "body": "unrelated"}, {"id": 6, "body": "<!-- ocr-summary -->\nold"}])
    calls, _ = post(tmp_path, mr, select, partition,
                    [{"leg_id": "a", "key": "g001", "state": "done", "evidence": {"comments": [], "warnings": []}}],
                    env={"FAKE_GH_COMMENTS": existing})
    writes = [c for c in calls if c["argv"][2] != "GET"]
    assert len(writes) == 1 and writes[0]["argv"][2] == "PATCH" and writes[0]["argv"][3].endswith("/comments/6")
    assert json.loads(writes[0]["stdin"])["body"] == ("<!-- ocr-summary -->\n✅ **OpenCodeReview**: Review "
                                                      f"complete: 0 finding(s) across {len(select['selected'])} "
                                                      "selected item(s).")


def test_a_refused_batch_is_posted_comment_by_comment(flow):
    tmp_path, mr, select, partition = flow
    comments = [{"path": "svc/handler.go", "content": "c", "existing_code": "mu.Lock()", "category": "bug",
                 "severity": "high", "start_line": 0, "end_line": 0},
                {"path": "svc/handler.go", "content": "unplaced", "existing_code": "nowhere",
                 "category": "", "severity": "", "start_line": 0, "end_line": 0}]
    calls, _ = post(tmp_path, mr, select, partition,
                    [{"leg_id": "a", "key": "g001", "state": "done",
                      "evidence": {"comments": comments, "warnings": []}}],
                    env={"FAKE_GH_FAIL": "/reviews"})
    singles = [json.loads(c["stdin"]) for c in calls if c["argv"][3].endswith("/pulls/7/comments")]
    assert len(singles) == 1 and singles[0]["line"] == 17        # placed by the output pass
    final = json.loads([c for c in calls if "/issues/" in c["argv"][3] and c["stdin"]][-1]["stdin"])["body"]
    assert "### 📄 `svc/handler.go`\n\n⚠️ GitHub could not post this as an inline comment: " \
           "No line information available\n\nunplaced" in final


def test_a_failed_group_fails_the_review_and_posts_nothing(flow):
    """`ocr review` exits nonzero on a review some file of which failed for anything
    but a budget, and upstream's Action then posts nothing and fails the job."""
    tmp_path, mr, select, partition = flow
    found = {"comments": [{"path": "web/index.ts", "content": "c", "existing_code": "x", "start_line": 2,
                           "end_line": 2}], "warnings": []}
    calls, ev = post(tmp_path, mr, select, partition,
                     [{"leg_id": "a", "key": "g001", "state": "failed", "evidence": None},
                      {"leg_id": "b", "key": "g002", "state": "done", "evidence": found}])
    assert calls == []
    assert ev["conclusion"] == "failure"
    assert ev["summary"].startswith("review incomplete: 2 of ")
    assert "Review partially complete: 1 finding(s); 2 of " in ev["summary"]


def test_a_budget_stop_is_a_partial_review_still_posted(flow):
    tmp_path, mr, select, partition = flow
    stopped = {"files": ["svc/handler.go", "src/üñí/naïve file.go"], "comments": [],
               "failure": {"class": "budget", "reason": "prompt exceeded the configured token budget"},
               "warnings": [{"type": "token_threshold_exceeded", "file": "k", "message": "too big"}]}
    calls, ev = post(tmp_path, mr, select, partition,
                     [{"leg_id": "a", "key": "g001", "state": "done", "evidence": stopped}])
    assert ev["conclusion"] == "success"
    body = json.loads([c for c in calls if c["stdin"]][-1]["stdin"])["body"]
    assert body.startswith("<!-- ocr-summary -->\n⚠️ **OpenCodeReview**: Review partially complete: "
                           f"0 finding(s); 2 of {len(select['selected'])} selected item(s) failed.")
    assert "`k` (`token_threshold_exceeded`): too big" in body


def test_no_supported_files(tmp_path, mr):
    select = {"strategy": "none", "kept": [], "selected": [], "included": []}
    calls, _ = post(tmp_path, mr, select, {"groups": [], "warnings": []}, [])
    body = json.loads([c for c in calls if c["stdin"]][-1]["stdin"])["body"]
    assert body == "<!-- ocr-summary -->\n✅ **OpenCodeReview**: Review skipped: no items were selected."


def test_a_retried_post_does_not_post_its_comments_twice(flow):
    tmp_path, mr, select, partition = flow
    select = {**select, "run": "r1"}
    found = {"comments": [{"path": "svc/handler.go", "content": "c", "existing_code": "mu.Lock()",
                           "category": "bug", "severity": "high", "start_line": 0, "end_line": 0}],
             "warnings": []}
    rows = [{"leg_id": "a", "key": "g001", "state": "done", "evidence": found}]
    first, _ = post(tmp_path, mr, select, partition, rows)
    [review] = [json.loads(c["stdin"]) for c in first if c["argv"][3].endswith("/reviews")]
    on_the_mr = json.dumps([{"id": 9, "body": rc["body"]} for rc in review["comments"]])
    again, ev = post(tmp_path, mr, select, partition, rows, env={"FAKE_GH_COMMENTS": on_the_mr})
    assert not [c for c in again if c["argv"][3].endswith(("/reviews", "/pulls/7/comments"))
                and c["argv"][2] == "POST"]
    assert ev["conclusion"] == "success" and "1 posted inline" in ev["summary"]
    other_run, _ = post(tmp_path, mr, {**select, "run": "r2"}, partition, rows,
                        env={"FAKE_GH_COMMENTS": on_the_mr})
    assert [c for c in other_run if c["argv"][3].endswith("/reviews")]   # a new run posts again


def test_every_forge_call_names_the_mr_and_a_refused_edit_posts_anew(flow):
    tmp_path, mr, select, partition = flow
    existing = json.dumps([{"id": 6, "body": "<!-- ocr-summary -->\nold"}])
    calls, _ = post(tmp_path, mr, select, partition,
                    [{"leg_id": "a", "key": "g001", "state": "done", "evidence": {"comments": [], "warnings": []}}],
                    env={"FAKE_GH_COMMENTS": existing, "FAKE_GH_FAIL": "/comments/6"})
    assert all(c["argv"][4:6] == ["-H", "X-SF-Pr-Iid: 7"] for c in calls)
    assert [c["argv"][2] for c in calls] == ["GET", "PATCH", "POST"]
