#!/usr/bin/env python3
"""Check: every proposed review comment anchors to a line the MR diff shows.

ABI (engine >= 9.0.0): anchors-in-diff <evidence.json>, ground truth in
$CHECK_CTX; prints one {"check","pass","feedback"} object and always exits 0.

The diff is `$CHECK_CTX/diff.patch`, fetched by the trusted service — never the
agent's word, and never fetched here: the check is pure. A RIGHT anchor must be
an added or context line of a hunk; LEFT, a removed or context line; a range
must stay inside one hunk.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _review  # noqa: E402

NAME = "anchors-in-diff"
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def emit(ok, feedback):
    print(json.dumps({"check": NAME, "pass": bool(ok), "feedback": feedback}))
    sys.exit(0)


def line_maps(patch):
    """{"RIGHT": {lineno: hunk}, "LEFT": {lineno: hunk}} for one file's patch."""
    maps, hunk, left, right = {"RIGHT": {}, "LEFT": {}}, -1, 0, 0
    for raw in patch.splitlines():
        m = HUNK_RE.match(raw)
        if m:
            hunk, left, right = hunk + 1, int(m.group(1)), int(m.group(2))
            continue
        if hunk < 0 or raw.startswith("\\"):
            continue
        if raw.startswith("+"):
            maps["RIGHT"][right] = hunk
            right += 1
        elif raw.startswith("-"):
            maps["LEFT"][left] = hunk
            left += 1
        else:
            maps["RIGHT"][right] = maps["LEFT"][left] = hunk
            left, right = left + 1, right + 1
    return maps


def diff_maps():
    ctx = os.environ.get("CHECK_CTX", "")
    if not ctx:
        raise OSError("no $CHECK_CTX (engine < 8.0.0?)")
    files, cur = {}, None
    for raw in open(os.path.join(ctx, "diff.patch")).read().splitlines(keepends=True):
        if raw.startswith("diff --git "):
            cur = raw.split(" b/", 1)[-1].strip()
            files[cur] = ""
        elif cur is not None:
            files[cur] += raw
    return {f: line_maps(p) for f, p in files.items()}


def main():
    try:
        ev = json.load(open(sys.argv[1]))
    except (OSError, ValueError, IndexError) as exc:
        emit(False, f"evidence unreadable/not JSON: {exc}")
    # the staged review comments (each type's fields: _review.form_errors)
    malformed = _review.form_errors(ev)
    if malformed:
        emit(False, "; ".join(malformed))
    findings = _review.comments(ev)
    try:
        maps = diff_maps()
    except OSError as exc:
        emit(False, f"no MR diff to check against: {exc}")
    if not maps:
        emit(False, "the MR diff is empty — nothing to anchor against")

    problems = []
    for i, f in enumerate(findings):
        path, line, side = f.get("path"), f.get("line"), f.get("side") or "RIGHT"
        side_map = (maps.get(path) or {}).get(side)
        if side_map is None:
            problems.append(f"comment {i}: {path!r} is not a file in the MR diff")
            continue
        if not isinstance(line, int) or line not in side_map:
            problems.append(f"comment {i}: {path}:{line} is not a {side}-side line of any hunk")
            continue
        start = f.get("start_line")
        if start is not None and not (isinstance(start, int) and start <= line
                                      and side_map.get(start) == side_map[line]):
            problems.append(f"comment {i}: {path}:{start}-{line} does not stay inside one hunk")
    if problems:
        emit(False, f"{len(problems)} of {len(findings)} anchors invalid: " + "; ".join(problems))
    emit(True, f"all {len(findings)} anchors are on diff lines ($CHECK_CTX/diff.patch, "
               f"{len(maps)} files)")


if __name__ == "__main__":
    main()
