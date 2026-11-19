#!/usr/bin/env python3
"""Check: the review is coherent and about the commit the checks saw.

Check ABI (engine >= 9.0.0): `review-coherent <evidence.json>` with ground truth
in `$CHECK_CTX`; prints one `{"check","pass","feedback"}` object and ALWAYS
exits 0. Pure: it reads the evidence and `$CHECK_CTX/pr.json`, nothing else.

The engine has already validated the evidence against its schema (item types,
every item's fields). This settles what a schema cannot:

  * each item type's required fields and the workflow's maxes
    (`_review.form_errors`);
  * the review was made for the commit the run is pinned to, whose diff the
    factory computed (`sha` == pr.json `head_sha`, and pr.json names the
    diff's `base_sha`): an anchor check against a different commit's diff
    proves nothing;
  * it says something: at least one comment or a verdict body;
  * REQUEST_CHANGES gives a reason (a comment or a verdict body);
  * no two comments sit on the same anchor.

It settles form, never the review's judgment.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _review  # noqa: E402

NAME = "review-coherent"


def emit(ok, feedback):
    print(json.dumps({"check": NAME, "pass": bool(ok), "feedback": feedback}))
    sys.exit(0)


def main():
    try:
        ev = json.load(open(sys.argv[1]))
    except (OSError, ValueError, IndexError) as exc:
        emit(False, f"evidence unreadable/not JSON: {exc}")
    try:
        pr = json.load(open(os.path.join(os.environ.get("CHECK_CTX", ""), "pr.json")))
    except (OSError, ValueError) as exc:
        emit(False, f"no $CHECK_CTX/pr.json to check against: {exc}")

    malformed = _review.form_errors(ev)
    if malformed:
        emit(False, "; ".join(malformed))
    head = pr.get("head_sha") or ""
    sha = ev.get("sha") or ""
    if not pr.get("base_sha"):
        emit(False, "pr.json has no base_sha: the factory could not compute the MR's diff")
    if sha != head:
        emit(False, f"the review is for {sha[:12] or '<no sha>'} but the run is pinned to "
                    f"{head[:12]}")

    comments = _review.comments(ev)
    verdict = _review.verdict(ev)
    vbody = verdict["body"].strip()
    if not comments and not vbody:
        emit(False, "empty review: no comments and no verdict body")
    if verdict["event"] == "REQUEST_CHANGES" and not (comments or vbody):
        emit(False, "REQUEST_CHANGES without a reason")

    seen, dupes = set(), []
    for i, c in enumerate(comments):
        anchor = (c["path"], c["side"], c.get("start_line"), c["line"])
        if anchor in seen:
            dupes.append(f"comment {i} repeats the anchor {c['path']}:{c['line']}")
        seen.add(anchor)
    if dupes:
        emit(False, "; ".join(dupes))
    emit(True, f"review for {head[:12]} (the checked diff): {len(comments)} comment(s), "
               f"verdict {verdict['event']}")


if __name__ == "__main__":
    main()
