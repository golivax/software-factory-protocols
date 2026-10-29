import json
from pathlib import Path

PROTOCOL = Path(__file__).resolve().parents[1]   # this test's protocol
HOOK = PROTOCOL / "workflows/post-summary.py"


class _Done:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def run_hook(evidence_obj, issue, tmp_path, monkeypatch, gh):
    """post-summary.py's main() as its job runs it: implement's evidence in
    $SF_INPUTS_DIR, the issue in protocol_context, the verdict in
    $SF_EVIDENCE_OUT; `gh` faked by `gh(argv) -> (rc, stdout)`. Returns
    (evidence written, gh calls made)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("post_summary", HOOK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "evidence.json").write_text(json.dumps(evidence_obj))
    (tmp_path / "protocol_context.json").write_text(json.dumps({"pr": issue}))
    out = tmp_path / "out.json"
    monkeypatch.setenv("SF_INPUTS_DIR", str(tmp_path / "inputs"))
    monkeypatch.setenv("SF_CONTROL_DIR", str(tmp_path))
    monkeypatch.setenv("SF_EVIDENCE_OUT", str(out))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return _Done(*gh(argv))
    monkeypatch.setattr(m.subprocess, "run", fake_run)
    m.main()
    return json.loads(out.read_text()), calls


def _comments(calls):
    return [c for c in calls if c[:2] == ["gh", "api"] and c[2].endswith("/comments")]


def test_post_summary_links_the_pr_on_the_issue(tmp_path, monkeypatch):
    prs = [{"number": 3, "url": "https://forge/o/r/pull/3",
            "headRefName": "impl-feature-auto/issue-7-ab12"}]
    out, calls = run_hook({"summary": "did X", "pr_branch": "impl-feature-auto/issue-7"}, "7",
                          tmp_path, monkeypatch,
                          lambda argv: (0, json.dumps(prs)) if argv[1:3] == ["pr", "list"] else (0, ""))
    assert out["conclusion"] == "success" and "#3" in out["summary"], out
    (comment,) = _comments(calls)
    assert comment[2] == "repos/o/r/issues/7/comments" and "pull/3" in comment[-1], comment


def test_post_summary_a_pushed_branch_without_a_pr_is_a_success(tmp_path, monkeypatch):
    refs = [{"ref": "refs/heads/impl-feature-auto/issue-7-ab12"}]

    def gh(argv):
        if argv[1:3] == ["pr", "list"]:
            return 0, "[]"
        if "matching-refs" in argv[2]:
            return 0, json.dumps(refs)
        return 0, ""
    out, calls = run_hook({"pr_branch": "impl-feature-auto/issue-7"}, "7", tmp_path, monkeypatch, gh)
    assert out["conclusion"] == "success" and "review pending" in out["summary"], out
    assert len(_comments(calls)) == 1


def test_post_summary_nothing_found_is_a_failure(tmp_path, monkeypatch):
    out, calls = run_hook({"pr_branch": "impl-feature-auto/issue-7"}, "7", tmp_path, monkeypatch,
                          lambda argv: (0, "[]"))
    assert out["conclusion"] == "failure" and not _comments(calls), out


def test_post_summary_defensive_no_branch(tmp_path, monkeypatch):
    out, calls = run_hook({"summary": "did X"}, "7", tmp_path, monkeypatch,
                          lambda argv: (_ for _ in ()).throw(AssertionError(argv)))
    assert out["conclusion"] == "failure" and "pr" in out["summary"].lower(), out
    assert calls == []


# --- no-spec/plan => no-PR, now enforced WITHOUT an adapter hook -----------
#
# REPLACES test_conclude_design_{is_executable,blocking,clear}. conclude-design.py
# was a nine-line adapter that read BLOCKING and re-stated it as
# {"blocked": ...}. BLOCKING is gone from the ABI in 4.0.0: `lib.decide` folds a
# failed `on_fail: "block"` check into the node's exit code itself
# (`lib.block_exit`), so the adapter had nothing left to add and was deleted.
#
# The GUARANTEE those three tests existed to protect is unchanged, so it is
# pinned here at the level that now carries it — the node's own declarations —
# rather than at a hook that no longer exists. The engine's fold of a failed
# block check into the exit code is the engine suite's to test, and the
# end-to-end halt is a walk of this protocol in golivax/software-factory.

CONCLUDE = PROTOCOL / "scripts/conclude-design.py"
PROTOCOL_JSON = PROTOCOL / "protocol.json"


def _design_node():
    proto = json.loads(PROTOCOL_JSON.read_text())
    return next(s for s in proto["states"] if s["id"] == "design")


def test_conclude_design_adapter_is_gone():
    """The adapter file is deleted AND nothing references it — a leftover
    `conclude` key naming a missing hook would make the engine synthesize
    HOOK_FAILED_EXIT on every run."""
    assert not CONCLUDE.exists(), "conclude-design.py must be deleted"
    assert "conclude" not in _design_node(), \
        "the design node must declare no conclude hook"
    assert "conclude-design" not in PROTOCOL_JSON.read_text()


def test_design_still_declares_what_enforces_the_guarantee():
    """The two things that now carry 'no spec/plan => no PR' must both survive:
    the block-severity checks that DETECT it and the halt that STOPS on it."""
    node = _design_node()
    blocking_checks = {c["run"] for c in node["checks"] if c.get("on_fail") == "block"}
    assert blocking_checks == {"spec-present", "plan-present"}, blocking_checks
    assert node.get("on_blocked") == "halt"
