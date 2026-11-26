"""The review agent's context tools answer as upstream's do.

The oracle ran upstream's tool providers (a range review: the new side at the
head, the old side at the base) on a git repository gen_cases.py builds with
fixed dates; this test builds the same repository, so the same commit ids, and
runs ocr_tools.py, from a folder holding what the agent's step stages beside
it, on every call.
"""
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

PKG = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = PKG / "tests" / "golden"
TOOLS = PKG / "workflows" / "ocr_tools.py"
CASES = json.loads((GOLDEN / "cases.json").read_text())["tools"]
WANT = json.loads((GOLDEN / "upstream_tool.json").read_text())["tools"]


def _gen_cases():
    sys.path.insert(0, str(PKG / "workflows"))
    spec = importlib.util.spec_from_file_location("gen_cases", GOLDEN / "oracle" / "gen_cases.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    """(repo, folder of the staged tools)."""
    repo = tmp_path_factory.mktemp("repo")
    _, base, head = _gen_cases().build_repo(str(repo))
    assert (base, head) == (CASES["base"], CASES["head"]), "the oracle's repository did not rebuild identically"
    agent = tmp_path_factory.mktemp("agent")
    shutil.copy(TOOLS, agent / "ocr_tools.py")
    (agent / "pr.json").write_text(json.dumps({"number": 1, "head_sha": head, "base_sha": base}))
    (agent / "ocr-diffmap.json").write_text(json.dumps(CASES["diffmap"]))
    return repo, agent


def call(staged, tool, args, fresh=True):
    repo, agent = staged
    if fresh:
        (agent / "ocr-tool-streaks.json").unlink(missing_ok=True)
    r = subprocess.run([sys.executable, str(agent / "ocr_tools.py"), tool, json.dumps(args)],
                       cwd=repo, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.mark.parametrize("i", range(len(CASES["calls"])))
def test_tool_answer(staged, i):
    c = CASES["calls"][i]
    got = call(staged, c["tool"], c["args"])
    want = WANT[i]
    if want.startswith("Error executing tool"):
        want += "\n"          # the CLI prints the failure as a line
    assert got == want


def test_consecutive_failures_escalate_then_reset(staged):
    bad = {"file_path": "nope.go"}
    first = call(staged, "file_read", bad)
    second = call(staged, "file_read", bad, fresh=False)
    third = call(staged, "file_read", bad, fresh=False)
    assert first.startswith("Error executing tool file_read:")
    assert "This is the second consecutive failure calling file_read" in second
    assert third.startswith("file_read has failed repeatedly for this task and has been skipped")
    call(staged, "file_read", {"file_path": "svc/handler.go"}, fresh=False)
    assert call(staged, "file_read", bad, fresh=False) == first
