"""The check context: the ground truth the engine hands a check BY NAME.

The engine runs every check as `<check> <evidence.json>` with `$CHECK_CTX`
pointing at a directory holding (engine >= 8.0.0):

    diff.patch         the MR diff, fetched by the trusted service
    files.txt          its changed files, one per line
    pr.json            {"number","title","body","head_sha"}, or {} when the run
                       is about no MR
    inputs/<as>.json   each input the node declares

There is no positional ground truth. `path()` is "" when no context was
handed (the check then reads nothing, exactly as for an empty diff).
"""
import json
import os


def path(name):
    ctx = os.environ.get("CHECK_CTX", "")
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
