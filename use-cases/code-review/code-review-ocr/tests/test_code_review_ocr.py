"""code-review-ocr's checks, its expand-findings expander and its publishing
code nodes (reduce-file, post-review), each run on hand-made inputs."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from sf_protocol_kit import check_env, make_ctx

PROTOCOL = Path(__file__).resolve().parents[1]   # this test's protocol


def _ctx_check(check, evidence, ctx, params=None):
    """Run a check as the engine does: `<check> <evidence.json>`, ground truth in $CHECK_CTX."""
    extra = {} if params is None else {"CHECK_PARAMS": json.dumps(params)}
    r = subprocess.run(["python3", str(check), str(evidence)], text=True,
                       capture_output=True, env=check_env(ctx, **extra))
    return json.loads(r.stdout)


# ---------------------------------------------------------------------------
# Task 4 — the expand-findings expander
# ---------------------------------------------------------------------------


EXPF = str(PROTOCOL / "expand/expand-findings")


def test_expand_findings_one_item_per_finding(tmp_path):
    ev = {"files": [{"path": "a.py", "findings": [
        {"finding_id": "a.py:1", "existing_code": "x=1", "side": "RIGHT", "line": 1, "comment": "c1"},
        {"finding_id": "a.py:2", "existing_code": "y=2", "side": "RIGHT", "line": 2, "comment": "c2"}]}]}
    ctx = make_ctx(tmp_path, inputs={"main-review": ev})
    r = subprocess.run([EXPF, str(tmp_path), "pr-1"], capture_output=True, text=True,
                       env=check_env(ctx))
    assert r.returncode == 0, r.stderr
    items = json.loads(r.stdout)["items"]
    assert [i["finding_id"] for i in items] == ["a.py:1", "a.py:2"]
    assert items[0]["path"] == "a.py" and items[0]["comment"] == "c1"


def test_expand_findings_no_evidence_fails_loud(tmp_path):
    r = subprocess.run([EXPF, str(tmp_path), "pr-1"], capture_output=True, text=True,
                       env=check_env(make_ctx(tmp_path)))
    assert r.returncode != 0
    assert "expand-findings" in r.stderr


def test_the_findings_fork_declares_its_expanders_input():
    """The expander reads `inputs/main-review.json`: the fork must name
    main-review as that input, or its round holds nothing to read."""
    proto = json.loads((PROTOCOL / "protocol.json").read_text())

    def forks(states):
        for n in states:
            if n.get("id") == "findings":
                yield n
            for leg in [n.get("each")] if isinstance(n.get("each"), dict) else []:
                yield from forks(leg.get("states") or [])
            yield from forks(n.get("states") or [])
    (fork,) = forks(proto["states"])
    assert fork["inputs"] == [{"from": "main-review", "as": "main-review"}]


# ---------------------------------------------------------------------------
# Task 5 — code-review-ocr checks: schema-valid + traces-exist-in-diff (reused)
# + filter-verdict-valid (new)
# ---------------------------------------------------------------------------


FVCHECK = str(PROTOCOL / "checks/filter-verdict-valid.py")


@pytest.mark.parametrize("ev,ok", [
    ({"finding_id": "a.py:1", "keep": True, "anchor": {"side": "RIGHT", "line": 3}}, True),
    ({"finding_id": "a.py:1", "keep": False}, True),                 # dropped: no anchor needed
    ({"finding_id": "a.py:1", "keep": True}, False),                 # kept but no anchor
    ({"keep": True, "anchor": {"side": "RIGHT", "line": 3}}, False), # no finding_id
    ([], False), ("x", False), ({"finding_id": "a", "keep": "yes"}, False),  # garbage / non-bool
])
def test_filter_verdict_valid(ev, ok, tmp_path):
    p = tmp_path / "e.json"; ctx = make_ctx(tmp_path)
    json.dump(ev, open(p, "w"))
    r = _ctx_check(FVCHECK, p, ctx)     # raises if the check crashed / non-JSON stdout
    assert r["check"] == "filter-verdict-valid"
    assert r["pass"] is ok


# ---------------------------------------------------------------------------
# Task 5b — fix the code-review-ocr checks that were mis-copied from
# code-review (a RUBRIC files->verdicts->category shape) so they actually
# validate OCR's FLAT evidence shapes: a new dependency-free
# evidence-schema-valid.py (driven by CHECK_PARAMS.schema) replaces the
# rubric-only schema-valid.py, and traces-exist-in-diff.py is adapted to read
# OCR's flat files->findings shape directly (it used to iterate `verdicts`
# only, so on OCR evidence it always found zero and vacuously passed —
# proven below by a genuinely-mismatched anchor now failing).
# ---------------------------------------------------------------------------


ESVCHECK = str(PROTOCOL / "checks/evidence-schema-valid.py")
OCR_TRACES = str(PROTOCOL / "checks/traces-exist-in-diff.py")


_PLAN_SCHEMA_PARAMS = {"schema": "plan.evidence.schema.json"}
_MAIN_REVIEW_SCHEMA_PARAMS = {"schema": "main-review.evidence.schema.json"}
_FILTER_SCHEMA_PARAMS = {"schema": "filter.evidence.schema.json"}

_VALID_PLAN_EV = {"examined": ["src/foo.py"], "plan_items": ["check auth"]}
_VALID_MAIN_REVIEW_EV = {"files": [{"path": "src/foo.py", "findings": [
    {"finding_id": "f1", "existing_code": "x = 1", "side": "RIGHT", "line": 2, "start_line": None,
     "comment": "looks off"}]}]}
_VALID_FILTER_EV = {"finding_id": "f1", "keep": True,
                    "anchor": {"side": "RIGHT", "line": 2, "start_line": None}, "reason": "r",
                    "path": "src/foo.py", "existing_code": "x = 1", "comment": "c"}


@pytest.mark.parametrize("ev,params,ok", [
    (_VALID_PLAN_EV, _PLAN_SCHEMA_PARAMS, True),
    ({"plan_items": ["x"]}, _PLAN_SCHEMA_PARAMS, False),              # missing required `examined`
    (_VALID_MAIN_REVIEW_EV, _MAIN_REVIEW_SCHEMA_PARAMS, True),
    ({"files": [{"path": "a.py"}]}, _MAIN_REVIEW_SCHEMA_PARAMS, False),  # file entry missing `findings`
    (_VALID_FILTER_EV, _FILTER_SCHEMA_PARAMS, True),
    ({"keep": True}, _FILTER_SCHEMA_PARAMS, False),                   # missing required `finding_id`
])
def test_evidence_schema_valid_validates_ocr_flat_shapes(ev, params, ok, tmp_path):
    p = tmp_path / "e.json"; ctx = make_ctx(tmp_path)
    json.dump(ev, open(p, "w"))
    r = _ctx_check(ESVCHECK, p, ctx, params)
    assert r["check"] == "evidence-schema-valid"
    assert r["pass"] is ok


@pytest.mark.parametrize("garbage", [[], None, "x", 42])
def test_evidence_schema_valid_exits_0_on_garbage(garbage, tmp_path):
    p = tmp_path / "e.json"; ctx = make_ctx(tmp_path)
    json.dump(garbage, open(p, "w"))
    r = _ctx_check(ESVCHECK, p, ctx, _MAIN_REVIEW_SCHEMA_PARAMS)
    assert r["check"] == "evidence-schema-valid"
    assert r["pass"] is False


def test_evidence_schema_valid_no_schema_param_fails_not_crashes(tmp_path):
    """No params.schema in CHECK_PARAMS -> a failing verdict (exit 0), not a crash."""
    p = tmp_path / "e.json"; ctx = make_ctx(tmp_path)
    json.dump(_VALID_MAIN_REVIEW_EV, open(p, "w"))
    r = _ctx_check(ESVCHECK, p, ctx, {})
    assert r["check"] == "evidence-schema-valid"
    assert r["pass"] is False


_OCR_DIFF = """diff --git a/src/foo.py b/src/foo.py
index abc..def 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,2 +1,3 @@
 def foo():
+    x = 1
     return x
"""


def test_traces_exist_in_diff_ocr_flat_pass_and_fail(tmp_path):
    """GENUINE proof this now validates OCR's flat files->findings shape (the
    pre-fix copy iterated `entry["verdicts"]`, found none on OCR evidence, and
    vacuously passed every time — it never actually checked an anchor). Here a
    finding whose existing_code/side/line MATCH the diff passes, and a finding
    whose anchor does NOT match fails — proving real validation now happens."""
    ctx = make_ctx(tmp_path, diff=_OCR_DIFF, files=["src/foo.py"])

    good_ev = tmp_path / "good.json"
    json.dump({"files": [{"path": "src/foo.py", "findings": [
        {"finding_id": "f1", "existing_code": "x = 1", "side": "RIGHT", "line": 2, "comment": "c"}]}]},
        open(good_ev, "w"))
    r_good = _ctx_check(OCR_TRACES, good_ev, ctx)
    assert r_good["check"] == "traces-exist-in-diff"
    assert r_good["pass"] is True, r_good["feedback"]

    bad_ev = tmp_path / "bad.json"
    json.dump({"files": [{"path": "src/foo.py", "findings": [
        {"finding_id": "f1", "existing_code": "this is not on that line", "side": "RIGHT", "line": 2,
         "comment": "c"}]}]},
        open(bad_ev, "w"))
    r_bad = _ctx_check(OCR_TRACES, bad_ev, ctx)
    assert r_bad["check"] == "traces-exist-in-diff"
    assert r_bad["pass"] is False
    assert "does not match" in r_bad["feedback"]


# ---------------------------------------------------------------------------
# Task 6 — code-review-ocr publish: per-file `reduce-file` + top `post-review`
# (reuses code-review/scripts/_review.py verbatim).
# ---------------------------------------------------------------------------


REDUCE_FILE = str(PROTOCOL / "workflows/reduce-file.py")
PINNED = "a1b2c3d4" * 5          # protocol_context.json's `sha`: the run's commit
POST_REVIEW = str(PROTOCOL / "workflows/post-review.py")


def _run_node(script, tmp_path, inputs, env=None):
    """A dispatched OCR node's script as its job runs it: its inputs in
    $SF_INPUTS_DIR/<as>.json, its verdict in $SF_EVIDENCE_OUT. -> the evidence."""
    d = tmp_path / f"job-{len(list(tmp_path.glob('job-*')))}"
    (d / "inputs").mkdir(parents=True)
    for alias, rows in inputs.items():
        (d / "inputs" / f"{alias}.json").write_text(json.dumps(rows))
    (d / "protocol_context.json").write_text(json.dumps({"pr": "1", "sha": PINNED}))
    out = d / "evidence-out.json"
    r = subprocess.run(["python3", script], capture_output=True, text=True,
                       env={**os.environ, "SF_INPUTS_DIR": str(d / "inputs"),
                            "SF_CONTROL_DIR": str(d), "SF_EVIDENCE_OUT": str(out),
                            **(env or {})})
    assert r.returncode == 0, r.stderr
    return json.loads(out.read_text())


def test_reduce_file_keeps_survivors(tmp_path):
    """Only keep:true findings survive; a survivor round-trips path/comment/
    existing_code when the filter evidence echoed them back."""
    rows = [
        {"leg_id": "f1", "state": "done", "evidence": {
            "finding_id": "a:1", "keep": True, "anchor": {"side": "RIGHT", "line": 1},
            "path": "a.py", "comment": "c1", "existing_code": "x=1"}},
        {"leg_id": "f2", "state": "done", "evidence": {"finding_id": "a:2", "keep": False}},
    ]
    out = _run_node(REDUCE_FILE, tmp_path, {"findings": rows})
    assert out["conclusion"] == "success"
    assert [s["finding_id"] for s in out["survivors"]] == ["a:1"]
    s = out["survivors"][0]
    assert s["path"] == "a.py" and s["comment"] == "c1" and s["existing_code"] == "x=1"
    assert s["side"] == "RIGHT" and s["line"] == 1


def test_reduce_file_uses_relocated_anchor(tmp_path):
    """A filter agent may relocate the anchor; reduce-file uses the anchor's
    side/line/start_line, never a stray top-level side/line."""
    rows = [{"leg_id": "f1", "state": "done", "evidence": {
        "finding_id": "a:1", "keep": True, "side": "RIGHT", "line": 1,
        "anchor": {"side": "LEFT", "line": 9, "start_line": 5}}}]
    s = _run_node(REDUCE_FILE, tmp_path, {"findings": rows})["survivors"][0]
    assert s["side"] == "LEFT" and s["line"] == 9 and s["start_line"] == 5


def test_reduce_file_no_survivors_still_succeeds(tmp_path):
    """All findings dropped -> a vacuous-but-successful reduce, not an error."""
    out = _run_node(REDUCE_FILE, tmp_path, {"findings": [
        {"leg_id": "f1", "state": "done", "evidence": {"finding_id": "a:1", "keep": False}}]})
    assert out["conclusion"] == "success" and out["survivors"] == []


class _Forge:
    """A fake forge API ($GITHUB_API_URL): records requests; `reject` refuses the
    first review whose event is in it."""
    def __init__(self, reject=()):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        forge = self
        self.requests, self.reject = [], set(reject)

        class H(BaseHTTPRequestHandler):
            def _reply(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                forge.requests.append(("GET", self.path, dict(self.headers), None))
                self._reply(200, {"head": {"sha": "head123"}})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                forge.requests.append(("POST", self.path, dict(self.headers), body))
                if body.get("event") in forge.reject:
                    forge.reject.discard(body["event"])
                    return self._reply(422, {"message": "Can not approve your own pull request"})
                self._reply(200, {"id": 7})

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.env = {"GITHUB_API_URL": f"http://127.0.0.1:{self.srv.server_port}",
                    "GITHUB_TOKEN": "job-tok", "GITHUB_REPOSITORY": "acme/repo"}

    def reviews(self):
        return [b for m, path, _, b in self.requests if m == "POST" and path.endswith("/reviews")]


def test_post_review_dedups_regroups_and_posts_one_review(tmp_path):
    """Two file legs' survivors are gathered from inputs/files.json, cross-file
    deduped by (path,side,line,existing_code), and posted as ONE review on the
    commit the run reviewed, with the job's own token: never on the MR's head
    now, which the fake forge says has moved (head123)."""
    rows = [
        {"leg_id": "L1", "state": "done", "evidence": {
            "conclusion": "success", "summary": "1 finding(s) kept", "survivors": [
                {"finding_id": "a:1", "path": "a.py", "existing_code": "x=1",
                 "comment": "issue A", "side": "RIGHT", "line": 3}]}},
        {"leg_id": "L2", "state": "done", "evidence": {
            "conclusion": "success", "summary": "2 finding(s) kept", "survivors": [
                # same (path,side,line,existing_code) as a:1 above -> collapses to ONE
                {"finding_id": "a:1-dup", "path": "a.py", "existing_code": "x=1",
                 "comment": "issue A (dup)", "side": "RIGHT", "line": 3},
                {"finding_id": "b:1", "path": "b.py", "existing_code": "y=2",
                 "comment": "issue B", "side": "RIGHT", "line": 7}]}},
    ]
    forge = _Forge()
    try:
        out = _run_node(POST_REVIEW, tmp_path, {"files": rows}, env=forge.env)
    finally:
        forge.srv.shutdown()
    assert out["conclusion"] == "failure" and out["event"] == "REQUEST_CHANGES", out
    (review,) = forge.reviews()
    assert review["event"] == "REQUEST_CHANGES" and review["commit_id"] == PINNED
    assert not [r for r in forge.requests if r[0] == "GET"], "it read the MR's live head"
    assert len(review["comments"]) == 2                 # deduped: 2 distinct, not 3
    assert {c["path"] for c in review["comments"]} == {"a.py", "b.py"}
    posts = [r for r in forge.requests if r[0] == "POST"]
    assert posts[0][1] == "/repos/acme/repo/pulls/1/reviews"
    assert posts[0][2]["Authorization"] == "Bearer job-tok"


def test_post_review_approves_with_no_survivors_and_falls_back_to_comment(tmp_path):
    """No survivors anywhere (incl. a leg whose evidence is None) -> APPROVE; a
    repo that forbids self-approval gets the same review as COMMENT."""
    rows = [
        {"leg_id": "L1", "state": "done", "evidence": {
            "conclusion": "success", "summary": "0 finding(s) kept", "survivors": []}},
        {"leg_id": "L2", "state": "done", "evidence": None},
    ]
    forge = _Forge(reject={"APPROVE"})
    try:
        out = _run_node(POST_REVIEW, tmp_path, {"files": rows}, env=forge.env)
    finally:
        forge.srv.shutdown()
    assert out["conclusion"] == "success", out
    assert [r["event"] for r in forge.reviews()] == ["APPROVE", "COMMENT"]


# ---------------------------------------------------------------------------
# The factory's diff (engine 19.0.0): `git diff` of the run's pinned commit.
# _GIT_DIFF is what the factory computed for an MR that changes a binary file,
# a mode, deletes a file, edits a path with a space and renames an edited file.
# ---------------------------------------------------------------------------

_GIT_DIFF = (
    'diff --git a/img/logo.png b/img/logo.png\nindex c86626638e0bc8cf47ca49bb1525b40e9737ee64'
    '..5663091be8ca2b5e57d3c2323a38840a729caf66 100644\nBinary files a/img/logo.png and '
    'b/img/logo.png differ\ndiff --git a/run.sh b/run.sh\nold mode 100644\nnew mode 100755\n'
    'diff --git a/src/gone.py b/src/gone.py\ndeleted file mode 100644\nindex '
    'c626f529f8e2c0bb51074d71fbc040252ea362ba..0000000000000000000000000000000000000000\n'
    '--- a/src/gone.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-def gone():\n-    return 0\n'
    'diff --git a/src/my file.py b/src/my file.py\nindex 223ca50d99502c4cf15a026d366965225e573961'
    '..7884034b9ae869a6f4adbcbad1a3f7b0b9fb02a5 100644\n--- a/src/my file.py\t\n'
    '+++ b/src/my file.py\t\n@@ -1,2 +1,3 @@\n a = 1\n-b = 2\n+b = 3\n+c = 4\n'
    'diff --git a/src/old.py b/src/new.py\nsimilarity index 94%\nrename from src/old.py\n'
    'rename to src/new.py\nindex c4352f8b46de5cdb88d0cc96958316db42dd2398..'
    'be8344cad54e4faa9cfa5d607b8fef33b65113b6 100644\n--- a/src/old.py\n+++ b/src/new.py\n'
    '@@ -7,7 +7,7 @@ line 6\n line 7\n line 8\n line 9\n-line 10\n+line ten\n line 11\n'
    ' line 12\n line 13\n')
_GIT_FILES = ["img/logo.png", "run.sh", "src/gone.py", "src/my file.py", "src/new.py"]
_PR = {"number": 1, "head_sha": PINNED, "base_sha": "b" * 40}


@pytest.mark.parametrize("path,finding,ok", [
    ("src/my file.py", {"existing_code": "c = 4", "side": "RIGHT", "line": 3}, True),
    ("src/my file.py", {"existing_code": "b = 2", "side": "LEFT", "line": 2}, True),
    ("src/new.py", {"existing_code": "line ten", "side": "RIGHT", "line": 10}, True),
    ("src/new.py", {"existing_code": "line 10", "side": "LEFT", "line": 10}, True),
    ("src/gone.py", {"existing_code": "return 0", "side": "LEFT", "line": 2}, True),
    ("src/old.py", {"existing_code": "line ten", "side": "RIGHT", "line": 10}, False),
    ("src/new.py", {"existing_code": "line ten", "side": "RIGHT", "line": 11}, False),
], ids=["space-right", "space-left", "renamed-right", "renamed-left", "deleted-left",
        "renamed-by-its-old-path", "wrong-line"])
def test_traces_exist_in_diff_reads_the_factorys_git_diff(tmp_path, path, finding, ok):
    """A finding anchors in a renamed file by its new path, in a deleted file
    on its old side, and in a path with a space (git ends its ---/+++ path
    with a tab)."""
    ctx = make_ctx(tmp_path, diff=_GIT_DIFF, files=_GIT_FILES, pr=_PR)
    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps({"files": [{"path": path, "findings": [
        {"finding_id": "f1", "comment": "c", **finding}]}]}))
    r = _ctx_check(OCR_TRACES, ev, ctx)
    assert r["pass"] is ok, r["feedback"]


def test_a_check_with_no_snapshot_fails_not_passes(tmp_path):
    """pr.json names the MR with no base_sha: the factory could not compute
    the diff. An empty diff is then no evidence of anything."""
    ctx = make_ctx(tmp_path, pr={"number": 1, "head_sha": PINNED, "base_sha": ""})
    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps({"files": []}))
    r = _ctx_check(OCR_TRACES, ev, ctx)
    assert r["check"] == "traces-exist-in-diff" and r["pass"] is False
    assert "could not compute" in r["feedback"]


EXPAND_FILES = str(PROTOCOL / "expand/expand-files")


def test_expand_files_splits_the_factorys_git_diff(tmp_path):
    """One leg per file with a diff to review: the binary file and the
    mode-only change have none; a renamed file is its new path."""
    ctx = make_ctx(tmp_path, diff=_GIT_DIFF, files=_GIT_FILES, pr=_PR)
    r = subprocess.run(["python3", EXPAND_FILES], capture_output=True, text=True,
                       env=check_env(ctx))
    assert r.returncode == 0, r.stderr
    items = json.loads(r.stdout)["items"]
    assert [i["path"] for i in items] == ["src/gone.py", "src/my file.py", "src/new.py"]
    assert "+line ten" in items[2]["diff"]


@pytest.mark.parametrize("pr,code", [({"number": 1, "head_sha": PINNED, "base_sha": ""}, 1),
                                     ({"number": 1, "head_sha": PINNED, "base_sha": "b" * 40}, 0),
                                     ({}, 0)],
                         ids=["no-snapshot", "an-mr-with-no-change", "no-mr"])
def test_expand_files_fails_the_run_with_no_snapshot(tmp_path, pr, code):
    """An empty diff is no legs when the MR changes nothing or there is no MR;
    when the factory could not compute it, the expander fails the run."""
    ctx = make_ctx(tmp_path, pr=pr)
    r = subprocess.run(["python3", EXPAND_FILES], capture_output=True, text=True,
                       env=check_env(ctx))
    assert r.returncode == code, r.stderr
    if code == 0:
        assert json.loads(r.stdout) == {"items": []}


# ---------------------------------------------------------------------------
# The agents read the run's snapshot, never the MR's head now (#518 in
# golivax/software-factory): each agent's staging step, run as its job runs
# it, copies $SF_SUBJECT_DIR where the agent reads, while a `gh` on PATH
# answers for a head the author pushed since.
# ---------------------------------------------------------------------------

AGENTS = sorted((PROTOCOL / "workflows").glob("ocr-*-agent.md"))
SNAPSHOT_DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"


def _stage(md, tmp_path, base_sha="b" * 40):
    import yaml
    fm = yaml.safe_load(md.read_text().split("---", 2)[1])
    steps = [s for s in fm.get("pre-agent-steps", []) + fm.get("steps", [])
             if "run" in s and "/tmp/gh-aw/agent" in s["run"]]
    sub = tmp_path / "subject"
    sub.mkdir()
    (sub / "diff.patch").write_text(SNAPSHOT_DIFF if base_sha else "")
    (sub / "files.txt").write_text("a.py" if base_sha else "")
    (sub / "pr.json").write_text(json.dumps({"number": 1, "head_sha": "a" * 40, "base_sha": base_sha}))
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text("#!/bin/sh\nprintf 'diff --git a/pushed_later.py b/pushed_later.py\\n'\n")
    gh.chmod(0o755)
    env = {**os.environ, "SF_SUBJECT_DIR": str(sub), "PATH": f"{gh.parent}:{os.environ['PATH']}"}
    codes = [subprocess.run(["bash", "-eo", "pipefail", "-c",
                             s["run"].replace("/tmp/gh-aw", str(tmp_path / "gh-aw"))],
                            env=env, capture_output=True, text=True) for s in steps]
    return codes, tmp_path / "gh-aw" / "agent"


@pytest.mark.parametrize("md", AGENTS, ids=lambda p: p.stem)
def test_an_agent_is_handed_the_runs_commit(md, tmp_path):
    codes, agent = _stage(md, tmp_path)
    assert codes and all(r.returncode == 0 for r in codes), [r.stderr for r in codes]
    assert (agent / "diff.patch").read_text() == SNAPSHOT_DIFF
    assert json.loads((agent / "pr.json").read_text())["head_sha"] == "a" * 40
    prompt = md.read_text().split("---", 2)[2]
    assert "/tmp/gh-aw/agent/diff.patch" in prompt


@pytest.mark.parametrize("md", AGENTS, ids=lambda p: p.stem)
def test_an_agent_with_no_snapshot_never_reviews_an_empty_diff(md, tmp_path):
    codes, agent = _stage(md, tmp_path, base_sha="")
    assert codes and codes[-1].returncode != 0 and "no base_sha" in codes[-1].stderr
    assert not (agent / "diff.patch").exists()
