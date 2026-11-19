"""The reviewer's workspace is the commit the review is about (#531 in
golivax/software-factory), not the MR's head when the job runs: the job's
own steps, run in the order the compiled job runs them (`steps:`, then gh-aw's
checkout of the MR's head, then `pre-agent-steps:`), against an MR the author
pushed to after the run started. The forge is a local repository the job's
`https://…github.com/<repo>.git` fetch is pointed at.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

MD = Path(__file__).resolve().parents[1] / "workflows" / "grumpy-reviewer.md"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


def _forge(tmp_path):
    """(origin, pinned, moved): the MR's commit the run is pinned to, and the
    one the author pushed after the run started, adding pushed_later.py."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    (origin / "a.py").write_text("x = 2\n")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "the MR")
    pinned = _git(origin, "rev-parse", "HEAD")
    (origin / "pushed_later.py").write_text("import os\n")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "pushed after the run started")
    _git(origin, "config", "uploadpack.allowAnySHA1InWant", "true")
    return origin, pinned, _git(origin, "rev-parse", "HEAD")


def _job(tmp_path, origin, head_sha, shallow=False, base_sha="b" * 40):
    """Run the job's steps; returns (workspace, the steps' results)."""
    fm = yaml.safe_load(MD.read_text().split("---", 2)[1])
    ws = tmp_path / "ws"
    # gh-aw's "Checkout PR branch": the MR's head of the moment
    _git(tmp_path, "clone", "-q", *(["--depth=1"] if shallow else []), origin.as_uri(), str(ws))
    sub = tmp_path / "subject"
    sub.mkdir()
    (sub / "diff.patch").write_text("diff --git a/a.py b/a.py\n" if base_sha else "")
    (sub / "files.txt").write_text("a.py" if base_sha else "")
    (sub / "pr.json").write_text(json.dumps({"number": 1, "head_sha": head_sha, "base_sha": base_sha}))
    env = {**os.environ, **GIT_ENV, "SF_SUBJECT_DIR": str(sub), "GH_TOKEN": "job-token", "REPO": "o/r",
           "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"url.{origin.as_uri()}.insteadOf",
           "GIT_CONFIG_VALUE_0": "https://x-access-token:job-token@github.com/o/r.git"}
    results = []
    for step in [s for s in (fm.get("steps") or []) + (fm.get("pre-agent-steps") or []) if "run" in s]:
        r = subprocess.run(["bash", "-eo", "pipefail", "-c",
                            step["run"].replace("/tmp/gh-aw", str(tmp_path / "gh-aw"))],
                           cwd=ws, env=env, capture_output=True, text=True)
        results.append((step["name"], r))
        if r.returncode:
            break
    return ws, results


@pytest.mark.parametrize("shallow", [False, True], ids=["pinned-in-history", "pinned-fetched"])
def test_a_moved_mr_leaves_the_workspace_at_the_runs_commit(tmp_path, shallow):
    origin, pinned, moved = _forge(tmp_path)
    ws, results = _job(tmp_path, origin, pinned, shallow=shallow)
    assert all(r.returncode == 0 for _, r in results), [(n, r.stderr) for n, r in results]
    assert _git(ws, "rev-parse", "HEAD") == pinned != moved
    assert (ws / "a.py").is_file() and not (ws / "pushed_later.py").exists()


def test_no_snapshot_fails_the_job_before_the_agent(tmp_path):
    origin, pinned, _ = _forge(tmp_path)
    _, results = _job(tmp_path, origin, pinned, base_sha="")
    assert results[-1][1].returncode != 0 and "no base_sha" in results[-1][1].stderr


@pytest.mark.parametrize("head_sha", ["", "0" * 40], ids=["no-head-sha", "unknown-commit"])
def test_a_commit_that_cannot_be_checked_out_fails_the_job(tmp_path, head_sha):
    origin, _, moved = _forge(tmp_path)
    ws, results = _job(tmp_path, origin, head_sha)
    name, r = results[-1]
    assert r.returncode != 0 and name == "Check out the commit the review is about", (name, r.stderr)
    assert _git(ws, "rev-parse", "HEAD") == moved              # untouched, and the agent never runs
