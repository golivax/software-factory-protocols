#!/usr/bin/env python3
"""`locate-<n>`: place round <n>'s comments on their lines.

Upstream: what executeToolCall does with each code_comment as the main loop
files it (reviewtask/tools.go): ParseCommentsWithPath, ResolveComment in the
comment's own diff (hunk lines, then the head's file content), RelocateAcrossFiles
when the code sits uniquely in another file's diff, and, when the comment's file
has a diff and none of that placed it, the RE_LOCATION_TASK LLM call. That call
is the `relocate-<n>` fork after this node: each comment this node could not
place is one of its legs.

Runs on the repository checked out at the run's commit (the head's file
content). The round's review answer is inputs/review.json; none (the round's
agent failed) is a round that did not run.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ocr import comments as M  # noqa: E402
from ocr import context as C  # noqa: E402
from ocr import diffs as D  # noqa: E402


def main():
    review = C.read_input("review")
    prepare = C.read_input("prepare") or {}
    sel = C.Selection(C.read_input("select"))
    D.read_new_file_contents(sel.kept, os.environ.get("GITHUB_WORKSPACE", ""), ref="HEAD")
    if review is None:
        C.write_evidence({"ran": False, "state": "FAILED", "comments": [],
                          "relocations": [], "warnings": []})
        return
    comments = M.parse(review.get("comments"), prepare.get("key") or "")
    relocations, warnings = [], []
    for i, cm in enumerate(comments):
        needs_llm, warning = M.place(cm, sel)
        if warning:
            warnings.append(warning)
        if needs_llm:
            relocations.append({"id": f"c{i:03d}", "index": i, "path": cm["path"],
                                "existing_code": cm["existing_code"], "content": cm["content"]})
    print(f"[ocr] {len(comments)} comment(s); {len(relocations)} need re-location")
    C.write_evidence({"ran": True, "state": review.get("state") or "DONE", "comments": comments,
                      "relocations": relocations, "warnings": warnings})


if __name__ == "__main__":
    C.run(main)
