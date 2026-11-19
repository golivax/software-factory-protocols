"""The reviewer reviews the run's commit, never the MR's head now (#518 in
golivax/software-factory): its staging step, run as its job runs it, copies
the snapshot ($SF_SUBJECT_DIR) to /tmp/gh-aw/agent/, where Step 2 of its
prompt reads the pull request, while a `gh` on PATH answers for a head the
author pushed since. A snapshot the factory could not compute fails the step.
"""
import json
import os
import subprocess
from pathlib import Path

import yaml

MD = Path(__file__).resolve().parents[1] / "workflows" / "grumpy-reviewer.md"
DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"


def _stage(tmp_path, base_sha="b" * 40):
    fm = yaml.safe_load(MD.read_text().split("---", 2)[1])
    steps = [s for s in fm.get("steps", []) if "run" in s]
    sub = tmp_path / "subject"
    sub.mkdir()
    (sub / "diff.patch").write_text(DIFF if base_sha else "")
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
    return codes, tmp_path / "gh-aw" / "agent", fm


def test_the_reviewer_is_handed_the_runs_commit(tmp_path):
    codes, agent, fm = _stage(tmp_path)
    assert codes and all(r.returncode == 0 for r in codes), [r.stderr for r in codes]
    assert (agent / "diff.patch").read_text() == DIFF
    assert (agent / "files.txt").read_text() == "a.py"
    assert json.loads((agent / "pr.json").read_text())["head_sha"] == "a" * 40
    # the prompt reads the staged pull request, and no tool reads the MR's head now
    assert "/tmp/gh-aw/agent/" in MD.read_text().split("---", 2)[2]
    assert "pull_requests" not in fm["tools"]["github"]["toolsets"]


def test_a_reviewer_with_no_snapshot_never_reviews_an_empty_diff(tmp_path):
    codes, agent, _ = _stage(tmp_path, base_sha="")
    assert codes and codes[-1].returncode != 0 and "no base_sha" in codes[-1].stderr
    assert not (agent / "diff.patch").exists()
