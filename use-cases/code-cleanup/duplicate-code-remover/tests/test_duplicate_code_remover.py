import json
import os
import stat
import subprocess
import pytest
from sf_protocol_testing import make_ctx, check_env
from pathlib import Path

PROTOCOL = Path(__file__).resolve().parents[1]   # this test's protocol

CHECKS = PROTOCOL / "checks"
WORKFLOWS = PROTOCOL / "workflows"
WELLFORMED = CHECKS / "evidence-wellformed.py"
ANCHORED = CHECKS / "anchored-to-real-code.py"
PARAMS = {"min_locations": 2, "max_patterns": 3, "severities": ["high", "medium", "low"]}


# ---------------------------------------------------------------------------
# Exec-bit regression (the class of bug: a check/publish hook committed
# without the executable bit is invisible to every test that shells out via
# `python3 <script>` — those bypass the runner's os.access(X_OK) gate
# entirely. The check round (check_round.py) execs the resolved path
# DIRECTLY (never `python3 <path>`), so a non-executable file becomes a
# silent "not executable" failing verdict / publish no-op in production.
# ---------------------------------------------------------------------------

FILE_ISSUES = WORKFLOWS / "file-issues.py"


def test_checks_are_executable():
    # file-issues is a dispatched code node now: its workflow runs it as
    # `python3 file-issues.py`, so only the checks need the exec bit.
    for p in (WELLFORMED, ANCHORED):
        assert os.access(p, os.X_OK), f"{p} is missing the executable bit (committed mode must be 100755)"


def test_run_checks_resolves_and_execs_detect_checks(tmp_path):
    """Drive the REAL check round, not `python3 <check>` directly, so a missing
    exec bit on either detect check would surface as the round's "not
    executable" verdict rather than being silently bypassed."""
    from sf_protocol_testing import check_round
    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps({"scanned": ["a.cpp"], "patterns": []}))
    out = check_round(PROTOCOL / "protocol.json", "detect", ev, make_ctx(tmp_path), tmp_path)
    results = {v["check"]: v for v in out["results"]}
    assert set(results) == {"evidence-wellformed", "anchored-to-real-code"}, results
    for name, v in results.items():
        assert v["pass"] is True, v
        assert "not executable" not in v["feedback"], v


def test_run_checks_exec_bit_guard_actually_guards(tmp_path):
    """Sanity-check the regression guard: strip +x from evidence-wellformed.py and
    confirm the check round surfaces the failure instead of silently succeeding. On
    a COPY of the package: chmod-ing the shared file raced every other test that
    runs detect's checks on another worker."""
    import shutil
    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps({"scanned": ["a.cpp"], "patterns": []}))
    ctx = make_ctx(tmp_path)
    pkg = tmp_path / "pkg"
    shutil.copytree(PROTOCOL, pkg, ignore=shutil.ignore_patterns("__pycache__"))
    check = pkg / "checks" / WELLFORMED.name
    check.chmod(check.stat().st_mode & ~stat.S_IXUSR & ~stat.S_IXGRP & ~stat.S_IXOTH)
    from sf_protocol_testing import check_round
    out = check_round(pkg / "protocol.json", "detect", ev, ctx, tmp_path)
    results = {v["check"]: v for v in out["results"]}
    assert results["evidence-wellformed"]["pass"] is False
    assert "not executable" in results["evidence-wellformed"]["feedback"]


def _write(p, obj):
    p.write_text(json.dumps(obj) if not isinstance(obj, str) else obj)
    return p


def _good_evidence():
    return {
        "scanned": ["src/a.cpp", "src/b.cpp"],
        "patterns": [{
            "id": "err-handling",
            "name": "Error handling pattern",
            "severity": "high",
            "rationale": "Identical try/catch block duplicated across two files.",
            "locations": [
                {"path": "src/a.cpp", "start_line": 10, "end_line": 12, "existing_code": "if (!ok) {\n  log(err);\n}"},
                {"path": "src/b.cpp", "start_line": 40, "end_line": 42, "existing_code": "if (!ok) {\n  log(err);\n}"},
            ],
        }],
    }


def _run(check, evidence, ctx, params):
    r = subprocess.run(["python3", str(check), str(evidence)], text=True, capture_output=True,
                       env=check_env(ctx, CHECK_PARAMS=json.dumps(params)))
    return json.loads(r.stdout)


@pytest.fixture
def empties(tmp_path):
    """An empty check context (no MR diff, no changed files)."""
    return make_ctx(tmp_path)


def test_wellformed_good_passes(tmp_path, empties):
    ev = _write(tmp_path / "ev.json", _good_evidence())
    out = _run(WELLFORMED, ev, empties, PARAMS)
    assert out["pass"] is True, out


def test_wellformed_none_found_passes(tmp_path, empties):
    ev = _write(tmp_path / "ev.json", {"scanned": ["src/a.cpp"], "patterns": []})
    out = _run(WELLFORMED, ev, empties, PARAMS)
    assert out["pass"] is True, out


def test_wellformed_empty_scanned_fails(tmp_path, empties):
    e = _good_evidence(); e["scanned"] = []
    ev = _write(tmp_path / "ev.json", e)
    out = _run(WELLFORMED, ev, empties, PARAMS)
    assert out["pass"] is False and "scanned" in out["feedback"], out


def test_wellformed_one_location_fails(tmp_path, empties):
    e = _good_evidence(); e["patterns"][0]["locations"] = e["patterns"][0]["locations"][:1]
    ev = _write(tmp_path / "ev.json", e)
    out = _run(WELLFORMED, ev, empties, PARAMS)
    assert out["pass"] is False and "location" in out["feedback"].lower(), out


def test_wellformed_bad_severity_fails(tmp_path, empties):
    e = _good_evidence(); e["patterns"][0]["severity"] = "critical"
    ev = _write(tmp_path / "ev.json", e)
    out = _run(WELLFORMED, ev, empties, PARAMS)
    assert out["pass"] is False and "severity" in out["feedback"].lower(), out


def test_wellformed_not_json_fails(tmp_path, empties):
    ev = _write(tmp_path / "ev.json", "not json {")
    out = _run(WELLFORMED, ev, empties, PARAMS)
    assert out["pass"] is False, out


def test_wellformed_unhashable_severity_no_crash(tmp_path, empties):
    e = _good_evidence(); e["patterns"][0]["severity"] = ["high"]
    ev = _write(tmp_path / "ev.json", e)
    env = dict(os.environ)
    env["CHECK_PARAMS"] = json.dumps(PARAMS)
    r = subprocess.run(
        ["python3", str(WELLFORMED), str(ev)],
        text=True, capture_output=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["pass"] is False, out


def test_wellformed_bad_check_params_no_crash(tmp_path, empties):
    ev = _write(tmp_path / "ev.json", _good_evidence())
    env = dict(os.environ)
    env["CHECK_PARAMS"] = json.dumps({"min_locations": "abc", "severities": 5})
    r = subprocess.run(
        ["python3", str(WELLFORMED), str(ev)],
        text=True, capture_output=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["pass"] is True, out


def test_wellformed_bool_line_rejected(tmp_path, empties):
    e = _good_evidence(); e["patterns"][0]["locations"][0]["start_line"] = True
    ev = _write(tmp_path / "ev.json", e)
    env = dict(os.environ)
    env["CHECK_PARAMS"] = json.dumps(PARAMS)
    r = subprocess.run(
        ["python3", str(WELLFORMED), str(ev)],
        text=True, capture_output=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["pass"] is False, out


def test_anchored_matches_real_file(tmp_path, empties):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.cpp").write_text("x\nif (!ok) {\n  log(err);\n}\ny\n")
    (tmp_path / "src" / "b.cpp").write_text("p\nq\nr\ns\nt\nif (!ok) {\n  log(err);\n}\n")
    ev = _write(tmp_path / "ev.json", {
        "scanned": ["src/a.cpp"],
        "patterns": [{
            "id": "eh", "name": "eh", "severity": "high", "rationale": "dup",
            "locations": [
                {"path": "src/a.cpp", "start_line": 2, "end_line": 4, "existing_code": "if (!ok) {\n  log(err);\n}"},
                {"path": "src/b.cpp", "start_line": 6, "end_line": 8, "existing_code": "if (!ok) {\n  log(err);\n}"},
            ],
        }],
    })
    import os
    env = dict(os.environ); env["SCAN_ROOT"] = str(tmp_path); env["CHECK_PARAMS"] = json.dumps(PARAMS)
    r = subprocess.run(["python3", str(ANCHORED), str(ev)],
                       text=True, capture_output=True, env=env)
    out = json.loads(r.stdout)
    assert out["pass"] is True, out


def test_anchored_mismatch_fails(tmp_path, empties):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.cpp").write_text("totally\ndifferent\ncontent\n")
    ev = _write(tmp_path / "ev.json", {
        "scanned": ["src/a.cpp"],
        "patterns": [{
            "id": "eh", "name": "eh", "severity": "high", "rationale": "dup",
            "locations": [
                {"path": "src/a.cpp", "start_line": 1, "end_line": 2, "existing_code": "if (!ok) {\n  log(err);\n}"},
                {"path": "src/a.cpp", "start_line": 2, "end_line": 3, "existing_code": "if (!ok) {\n  log(err);\n}"},
            ],
        }],
    })
    import os
    env = dict(os.environ); env["SCAN_ROOT"] = str(tmp_path); env["CHECK_PARAMS"] = json.dumps(PARAMS)
    r = subprocess.run(["python3", str(ANCHORED), str(ev)],
                       text=True, capture_output=True, env=env)
    out = json.loads(r.stdout)
    assert out["pass"] is False and "src/a.cpp" in out["feedback"], out


def test_anchored_missing_file_fails(tmp_path, empties):
    ev = _write(tmp_path / "ev.json", {
        "scanned": ["src/gone.cpp"],
        "patterns": [{
            "id": "eh", "name": "eh", "severity": "high", "rationale": "dup",
            "locations": [
                {"path": "src/gone.cpp", "start_line": 1, "end_line": 1, "existing_code": "x"},
                {"path": "src/gone.cpp", "start_line": 2, "end_line": 2, "existing_code": "y"},
            ],
        }],
    })
    import os
    env = dict(os.environ); env["SCAN_ROOT"] = str(tmp_path); env["CHECK_PARAMS"] = json.dumps(PARAMS)
    r = subprocess.run(["python3", str(ANCHORED), str(ev)],
                       text=True, capture_output=True, env=env)
    out = json.loads(r.stdout)
    assert out["pass"] is False and r.returncode == 0, (out, r.returncode)


def test_anchored_absolute_path_rejected(tmp_path, empties):
    ev = _write(tmp_path / "ev.json", {
        "scanned": ["/etc/hostname"],
        "patterns": [{
            "id": "eh", "name": "eh", "severity": "high", "rationale": "dup",
            "locations": [
                {"path": "/etc/hostname", "start_line": 1, "end_line": 1, "existing_code": "x"},
            ],
        }],
    })
    env = dict(os.environ); env["SCAN_ROOT"] = str(tmp_path); env["CHECK_PARAMS"] = json.dumps(PARAMS)
    r = subprocess.run(["python3", str(ANCHORED), str(ev)],
                       text=True, capture_output=True, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["pass"] is False and "escapes" in out["feedback"], out


def test_anchored_traversal_path_rejected(tmp_path, empties):
    outside = tmp_path.parent / f"{tmp_path.name}_outside.cpp"
    outside.write_text("if (!ok) {\n  log(err);\n}\n")
    try:
        ev = _write(tmp_path / "ev.json", {
            "scanned": ["../" + outside.name],
            "patterns": [{
                "id": "eh", "name": "eh", "severity": "high", "rationale": "dup",
                "locations": [
                    {"path": "../" + outside.name, "start_line": 1, "end_line": 3,
                     "existing_code": "if (!ok) {\n  log(err);\n}"},
                ],
            }],
        })
        env = dict(os.environ); env["SCAN_ROOT"] = str(tmp_path); env["CHECK_PARAMS"] = json.dumps(PARAMS)
        r = subprocess.run(["python3", str(ANCHORED), str(ev)],
                           text=True, capture_output=True, env=env)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["pass"] is False and "escapes" in out["feedback"], out
    finally:
        outside.unlink(missing_ok=True)


def test_anchored_crlf_and_trailing_ws_tolerated(tmp_path, empties):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.cpp").write_text("aaa\r\nif (!ok) {   \r\n  log(err);  \r\n}\r\nbbb\r\n")
    ev = _write(tmp_path / "ev.json", {
        "scanned": ["src/a.cpp"],
        "patterns": [{
            "id": "eh", "name": "eh", "severity": "high", "rationale": "dup",
            "locations": [
                {"path": "src/a.cpp", "start_line": 2, "end_line": 4, "existing_code": "if (!ok) {\n  log(err);\n}"},
            ],
        }],
    })
    env = dict(os.environ); env["SCAN_ROOT"] = str(tmp_path); env["CHECK_PARAMS"] = json.dumps(PARAMS)
    r = subprocess.run(["python3", str(ANCHORED), str(ev)],
                       text=True, capture_output=True, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["pass"] is True, out


def test_anchored_no_patterns_passes(tmp_path, empties):
    ev = _write(tmp_path / "ev.json", {"scanned": ["src/a.cpp"], "patterns": []})
    import os
    env = dict(os.environ); env["SCAN_ROOT"] = str(tmp_path); env["CHECK_PARAMS"] = json.dumps(PARAMS)
    r = subprocess.run(["python3", str(ANCHORED), str(ev)],
                       text=True, capture_output=True, env=env)
    out = json.loads(r.stdout)
    assert out["pass"] is True, out


def test_anchored_malformed_no_crash(tmp_path, empties):
    ev = _write(tmp_path / "ev.json", {"scanned": ["a.cpp"], "patterns": [5]})
    env = dict(os.environ); env["SCAN_ROOT"] = str(tmp_path); env["CHECK_PARAMS"] = json.dumps(PARAMS)
    r = subprocess.run(["python3", str(ANCHORED), str(ev)],
                       text=True, capture_output=True, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["check"] == "anchored-to-real-code"


def _import_file_issues():
    import importlib.util
    spec = importlib.util.spec_from_file_location("file_issues", FILE_ISSUES)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fingerprint_is_stable_and_order_independent(tmp_path):
    m = _import_file_issues()
    pat_a = {"locations": [
        {"path": "src/a.cpp", "existing_code": "if (!ok) {\n  log(err);\n}"},
        {"path": "src/b.cpp", "existing_code": "if (!ok) {\n log(err);\n}"},
    ]}
    pat_b = {"locations": list(reversed(pat_a["locations"]))}
    assert m.fingerprint(pat_a) == m.fingerprint(pat_b)
    assert m.fingerprint(pat_a).startswith("dup-fp:")


def test_comment_body_starts_with_trigger_prefix():
    m = _import_file_issues()
    assert m.comment_body().startswith("/impl-feature-auto")


def test_issue_body_embeds_fingerprint_marker():
    m = _import_file_issues()
    pat = {"id": "eh", "name": "Error handling", "severity": "high",
           "rationale": "dup", "locations": [
               {"path": "src/a.cpp", "start_line": 1, "end_line": 1, "existing_code": "x"},
               {"path": "src/b.cpp", "start_line": 2, "end_line": 2, "existing_code": "x"}]}
    fp = m.fingerprint(pat)
    body = m.issue_body(pat, fp)
    assert f"<!-- {fp} -->" in body
    assert "src/a.cpp" in body and "src/b.cpp" in body


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _one_pattern_evidence():
    return {
        "scanned": ["src/a.cpp"],
        "patterns": [{
            "id": "eh", "name": "Error handling", "severity": "high", "rationale": "dup",
            "locations": [
                {"path": "src/a.cpp", "start_line": 1, "end_line": 1, "existing_code": "x"},
                {"path": "src/b.cpp", "start_line": 2, "end_line": 2, "existing_code": "x"}]}]}


def _run_main(tmp_path, monkeypatch, m, evidence, fake_run, params=None):
    """file-issues.py's main() as its job runs it: detect's evidence in
    $SF_INPUTS_DIR, the node's params in protocol_context, the verdict written to
    $SF_EVIDENCE_OUT; `gh` (subprocess.run) faked."""
    inputs = tmp_path / "inputs"
    inputs.mkdir(exist_ok=True)
    (inputs / "evidence.json").write_text(json.dumps(evidence) if not isinstance(evidence, str)
                                          else evidence)
    ctl = tmp_path / "control"
    ctl.mkdir(exist_ok=True)
    (ctl / "protocol_context.json").write_text(json.dumps(
        {"cid": "c", "pr": "", "params": params} if params is not None else {"cid": "c", "pr": ""}))
    out = tmp_path / "evidence-out.json"
    monkeypatch.setenv("SF_INPUTS_DIR", str(inputs))
    monkeypatch.setenv("SF_CONTROL_DIR", str(ctl))
    monkeypatch.setenv("SF_EVIDENCE_OUT", str(out))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(m.subprocess, "run", fake_run)
    m.main()
    return json.loads(out.read_text())


def _no_io(cmd, **kwargs):
    raise AssertionError(f"no forge call expected, got {cmd}")


def test_main_no_patterns_is_success(tmp_path, monkeypatch):
    """A duplication-free scan is a SUCCESSFUL run (this is the protocol's last
    node, so its conclusion colours the run), and it touches nothing."""
    m = _import_file_issues()
    out = _run_main(tmp_path, monkeypatch, m, {"scanned": ["src/a.cpp"], "patterns": []}, _no_io)
    assert out["conclusion"] == "success", out
    assert "No duplication patterns" in out["summary"], out


def test_main_malformed_pattern_no_crash(tmp_path, monkeypatch):
    m = _import_file_issues()
    out = _run_main(tmp_path, monkeypatch, m, {"scanned": ["a.cpp"], "patterns": [5]}, _no_io)
    assert out["conclusion"] == "success", out     # not a dict -> no pattern to file


def test_file_issues_malformed_locations_no_crash(tmp_path, monkeypatch):
    """A dict pattern with a truthy non-list `locations` would raise inside
    fingerprint()/issue_body() — unreachable in production (the checks gate it)
    but the node must still state one verdict."""
    m = _import_file_issues()

    def fake_run(cmd, **kwargs):
        return _FakeCompleted(0, "[]" if "list" in cmd else "", "")

    out = _run_main(tmp_path, monkeypatch, m, {"scanned": ["a.cpp"], "patterns": [
        {"id": "x", "name": "x", "severity": "high", "rationale": "x", "locations": 5}]}, fake_run)
    assert out["conclusion"] == "failure" and out["summary"], out


def _run_main_nonlocal(monkeypatch, m, ev_path, fake_run, capsys, instance="pr-1"):
    return _run_main(ev_path.parent, monkeypatch, m, json.loads(ev_path.read_text()), fake_run)


def test_main_skips_deduped_pattern(tmp_path, monkeypatch, capsys):
    m = _import_file_issues()
    ev_data = _one_pattern_evidence()
    fp = m.fingerprint(ev_data["patterns"][0])
    fp_hex = fp.split(":", 1)[1]
    ev = tmp_path / "ev.json"; ev.write_text(json.dumps(ev_data))

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "list" in cmd:
            body = f"already filed <!-- dup-fp:{fp_hex} -->"
            return _FakeCompleted(0, json.dumps([{"body": body}]), "")
        if "create" in cmd:
            return _FakeCompleted(0, "https://github.com/o/r/issues/99", "")
        return _FakeCompleted(0, "", "")

    out = _run_main_nonlocal(monkeypatch, m, ev, fake_run, capsys)
    assert not any("issue" in c and "create" in c for c in calls), calls
    assert out["conclusion"] == "success", out
    assert "dedup" in out["summary"].lower(), out


def test_main_creates_and_comments_when_not_deduped(tmp_path, monkeypatch, capsys):
    m = _import_file_issues()
    ev_data = _one_pattern_evidence()
    ev = tmp_path / "ev.json"; ev.write_text(json.dumps(ev_data))

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "list" in cmd:
            return _FakeCompleted(0, "[]", "")
        if "create" in cmd:
            return _FakeCompleted(0, "https://github.com/o/r/issues/42\n", "")
        if "api" in cmd:
            return _FakeCompleted(0, "", "")
        return _FakeCompleted(0, "", "")

    out = _run_main_nonlocal(monkeypatch, m, ev, fake_run, capsys)
    create_calls = [c for c in calls if "issue" in c and "create" in c]
    comment_calls = [c for c in calls if "api" in c]
    assert len(create_calls) == 1, calls
    assert len(comment_calls) == 1, calls
    body_idx = comment_calls[0].index("-f") + 1
    body_arg = comment_calls[0][body_idx]
    assert body_arg.startswith("body=/impl-feature-auto"), body_arg
    assert out["conclusion"] == "success", out


def test_main_list_failure_fails_safe(tmp_path, monkeypatch, capsys):
    m = _import_file_issues()
    ev_data = _one_pattern_evidence()
    ev = tmp_path / "ev.json"; ev.write_text(json.dumps(ev_data))

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "list" in cmd:
            return _FakeCompleted(1, "", "gh: rate limited")
        return _FakeCompleted(0, "", "")

    out = _run_main_nonlocal(monkeypatch, m, ev, fake_run, capsys)
    assert not any("issue" in c and "create" in c for c in calls), calls
    # `failure`, not `neutral`: the run did NOT do its job, and as a `code`
    # node an explicit conclusion is the verdict that colours the aggregate.
    assert out["conclusion"] == "failure", out
    assert "dedup" in out["summary"].lower() or "skip" in out["summary"].lower(), out


def test_params_max_patterns_caps_the_issues_filed(tmp_path, monkeypatch):
    """The cap is the node's `params.max_patterns` (was the DUP_MAX_PATTERNS env
    opt-in); a bad value falls back to 3 instead of crashing."""
    m = _import_file_issues()
    ev = _one_pattern_evidence()
    second = json.loads(json.dumps(ev["patterns"][0]))
    second["locations"][0]["existing_code"] = "y"
    ev["patterns"].append(second)
    created = []

    def fake_run(cmd, **kwargs):
        if "list" in cmd:
            return _FakeCompleted(0, "[]", "")
        if "create" in cmd and "issue" in cmd:
            created.append(cmd)
            return _FakeCompleted(0, f"https://github.com/o/r/issues/{len(created)}\n", "")
        return _FakeCompleted(0, "", "")

    out = _run_main(tmp_path, monkeypatch, m, ev, fake_run, params={"max_patterns": 1})
    assert len(created) == 1 and out["conclusion"] == "success", (created, out)
    created.clear()
    out = _run_main(tmp_path, monkeypatch, m, ev, fake_run, params={"max_patterns": "abc"})
    assert len(created) == 2 and out["conclusion"] == "success", (created, out)


def test_create_issue_falls_back_without_labels(tmp_path, monkeypatch):
    """Backport regression: if `gh issue create --label` fails (labels absent on the
    target repo), _create_issue retries WITHOUT labels so the issue still lands."""
    m = _import_file_issues()
    calls = []

    class R:
        def __init__(self, rc, out=""): self.returncode = rc; self.stdout = out; self.stderr = "label not found"

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[:3] == ["gh", "issue", "create"]:
            # fail when --label present, succeed without it
            if "--label" in argv:
                return R(1)
            return R(0, "https://github.com/o/r/issues/77")
        return R(0)
    monkeypatch.setattr(m.subprocess, "run", fake_run)

    num = m._create_issue("o/r", "t", "b", ["code-quality", "automated-analysis"])
    assert num == "77", calls
    # two issue-create attempts: with labels (failed) then without (succeeded)
    issue_creates = [c for c in calls if c[:3] == ["gh", "issue", "create"]]
    assert len(issue_creates) == 2, calls
    assert "--label" in issue_creates[0] and "--label" not in issue_creates[1], calls
