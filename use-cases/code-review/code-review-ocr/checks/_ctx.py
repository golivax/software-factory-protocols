"""The check context: the ground truth the engine hands a check BY NAME.

The engine runs every check as `<check> <evidence.json>` with `$CHECK_CTX`
pointing at a directory holding (engine >= 8.0.0):

    diff.patch         the diff of the commit the run is pinned to, computed
                       by the factory with git (`git diff` format)
    files.txt          its changed files, one per line
    pr.json            {"number","title","body","head_sha","base_sha"}, or {}
                       when the run is about no MR
    inputs/<as>.json   each input the node declares

There is no positional ground truth. `path()` is "" when no context was
handed (the check then reads nothing, exactly as for an empty diff).

A run about an MR whose diff the factory could not compute (engine >=
19.0.0: pr.json names the MR, its `base_sha` is "") has empty files, which
are not an MR that changes nothing: reading either one then ends the check
with a failing verdict instead (`_no_snapshot`).
"""
import json
import os
import sys


def _no_snapshot():
    name = os.path.splitext(os.path.basename(sys.argv[0]))[0]
    print(json.dumps({"check": name, "pass": False,
                      "feedback": "the factory could not compute the MR's diff for this "
                                  "run (pr.json names no base_sha): nothing to check against"}))
    sys.exit(0)


def snapshot_missing():
    """The run is about an MR whose diff the factory could not compute."""
    meta = pr()
    return bool(meta.get("number")) and not meta.get("base_sha")


def path(name):
    ctx = os.environ.get("CHECK_CTX", "")
    if ctx and name in ("diff.patch", "files.txt") and snapshot_missing():
        _no_snapshot()
    return os.path.join(ctx, name) if ctx else ""


def read(name, default=""):
    p = path(name)
    try:
        with open(p) as fh:
            return fh.read()
    except OSError:
        return default


def pr():
    try:
        return json.loads(read("pr.json", "{}") or "{}")
    except ValueError:
        return {}
