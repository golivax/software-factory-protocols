#!/usr/bin/env python3
"""Settle that `/hello` surveyed the checked-out repo AND greeted the MR.

Check ABI (the engine's): `<check> <evidence.json>`, ground truth in `$CHECK_CTX`
-> one JSON object `{"check","pass","feedback"}` on stdout, ALWAYS exit 0 (a
non-zero exit is reserved for a genuine runner error, not a failed claim).

The claims are self-contained and genuine — settled from the node's OWN evidence:
  * `ok:true`, `repo_files >= 1`, and a non-empty `sample` whose size is consistent
    with the count — proof the node actually read the checked-out tree (not a
    fabricated number with nothing behind it); and
  * `commented:true` — proof the greeting reached the MR through the forge API.
"""
import json
import sys


def emit(ok, feedback):
    print(json.dumps({"check": "repo-scanned", "pass": bool(ok), "feedback": feedback}))
    return 0


def main():
    try:
        with open(sys.argv[1]) as f:
            ev = json.load(f)
    except (OSError, ValueError, IndexError) as exc:
        return emit(False, f"no readable evidence: {exc}")
    if not isinstance(ev, dict) or ev.get("ok") is not True:
        return emit(False, "the survey did not report ok:true")
    n = ev.get("repo_files")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        return emit(False, f"repo_files is not a positive integer: {n!r}")
    sample = ev.get("sample")
    if not isinstance(sample, list) or not sample or not all(
            isinstance(p, str) and p.strip() for p in sample):
        return emit(False, "sample is not a non-empty list of paths")
    if n < len(sample):
        return emit(False, f"repo_files ({n}) is smaller than the sample it showed ({len(sample)})")
    if ev.get("commented") is not True:
        why = ev.get("comment_error") or ""
        return emit(False, f"the MR greeting was not posted (commented={ev.get('commented')!r}). {why}".strip())
    return emit(True, f"surveyed {n} files and greeted the MR (e.g. {', '.join(sample[:3])})")


if __name__ == "__main__":
    raise SystemExit(main())
