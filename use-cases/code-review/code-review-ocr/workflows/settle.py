#!/usr/bin/env python3
"""`settle-<n>`: round <n>'s comments after re-location, and the filter's candidates.

Upstream: the end of ReLocateComment (diff/relocation.go): the re-location
answer's first fenced code block replaces the comment's existing_code only when
the comment then resolves; otherwise the comment keeps its snippet and stays
unplaced (line 0, posted in the summary). A re-location leg that failed changes
nothing, as a failed call changes nothing upstream.

Then the REVIEW_FILTER_TASK's candidates (executeGroupReviewFilter): this
round's comments on the group's own files, file by file in the group's order.
A comment re-filed to a file outside the group is not a candidate and is never
filtered, as upstream. `no_filter` (upstream's --no-filter) skips the filter.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ocr import context as C  # noqa: E402
from ocr import diffs as D  # noqa: E402


def main():
    locate = C.read_input("locate") or {}
    prepare = C.read_input("prepare") or {}
    rows = C.read_input("relocations") or []
    sel = C.Selection(C.read_input("select"))
    D.read_new_file_contents(sel.kept, os.environ.get("GITHUB_WORKSPACE", ""), ref="HEAD")
    comments = [dict(c) for c in locate.get("comments") or []]

    by_id = {r["id"]: r for r in locate.get("relocations") or []}
    relocated = 0
    for row in rows:
        item = by_id.get(row.get("key"))
        ev = row.get("evidence") or {}
        if row.get("state") != "done" or item is None or not isinstance(ev.get("response"), str):
            continue
        code = D.extract_code_block(ev["response"])
        cm = comments[item["index"]]
        d = sel.find(cm["path"])
        if not code or d is None:
            continue
        original = cm["existing_code"]
        cm["existing_code"] = code
        if D.resolve_comment(cm, d):
            relocated += 1
        else:
            cm["existing_code"] = original

    candidates = [i for path in prepare.get("files") or []
                  for i, cm in enumerate(comments) if cm["path"] == path]
    run_filter = (bool(candidates) and locate.get("state") == "DONE"
                  and not C.protocol_inputs().get("no_filter"))
    print(f"[ocr] re-located {relocated} comment(s); {len(candidates)} filter candidate(s)")
    C.write_evidence({"ran": bool(locate.get("ran")), "state": locate.get("state") or "FAILED",
                      "comments": comments, "candidates": candidates, "filter": run_filter,
                      "warnings": locate.get("warnings") or []})


if __name__ == "__main__":
    C.run(main)
