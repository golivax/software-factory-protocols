#!/usr/bin/env python3
"""code-review-ocr per-file `reduce`: a dispatched code node (its own microVM).

Reads $SF_INPUTS_DIR/findings.json — the `from_fork` rows over this file's
per-finding `filter` legs, one row per finding, {leg_id, key, state, evidence} —
and keeps the findings whose filter verdict was keep: true, at the (possibly
relocated) anchor the filter evidence carries.

Writes {conclusion, summary, survivors} to $SF_EVIDENCE_OUT. The engine persists
that evidence as this file leg's output, so the top `merge` (post-review) reads
each file's `evidence.survivors` through its own `from_fork: review`.

filter.evidence.schema.json carries finding_id, keep, the anchor (null when
dropped) and the finding's path / existing_code / comment echoed back, so a kept
finding round-trips complete. No forge access.
"""
import json
import os


def survivors(rows):
    out = []
    for r in rows:
        ev = r.get("evidence") or {}
        if not isinstance(ev, dict) or ev.get("keep") is not True:
            continue
        a = ev.get("anchor") or {}
        s = {
            "finding_id": ev.get("finding_id"),
            "path": ev.get("path"),
            "existing_code": ev.get("existing_code") or "",
            "comment": ev.get("comment") or "",
            "side": a.get("side") or "RIGHT",
            "line": a.get("line"),
        }
        if a.get("start_line") is not None:
            s["start_line"] = a["start_line"]
        out.append(s)
    return out


def main():
    with open(os.path.join(os.environ["SF_INPUTS_DIR"], "findings.json")) as fh:
        kept = survivors(json.load(fh))
    with open(os.environ["SF_EVIDENCE_OUT"], "w") as fh:
        json.dump({"conclusion": "success", "summary": f"{len(kept)} finding(s) kept",
                   "survivors": kept}, fh)


if __name__ == "__main__":
    main()
