#!/usr/bin/env python3
"""`collect`: the group's result, the last step of its leg.

Reads the last round that ran (inputs/round-1.json .. round-3.json; a round the
group never reached has no input) and hands on its comments, its warnings and,
when its files failed review, the `failure` and its class: the leg's evidence,
which `post` reads for every group. A group stopped by the round-1 prompt-budget
check (prepare's `over_budget`) has no round: its files fail with the `budget`
class and it warns `token_threshold_exceeded`, as upstream's checkPromptBudget.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ocr import context as C  # noqa: E402
from ocr import selection as S  # noqa: E402


def main():
    prepare = C.read_input("prepare") or {}
    last = None
    for n in (1, 2, 3):
        doc = C.read_input(f"round-{n}")
        if doc is not None:
            last = doc
    warnings, comments, failure = [], [], None
    if last is not None:
        warnings, comments = last.get("warnings") or [], last.get("comments") or []
        failure = last.get("failure")
    elif prepare.get("over_budget"):
        limit = S.template()["MAX_TOKENS"]
        warnings.append({"type": "token_threshold_exceeded", "file": prepare.get("key") or "",
                         "message": f"prompt tokens ({prepare.get('prompt_tokens')}) exceed 80% of "
                                    f"max_tokens({limit}) [round 1]"})
        failure = {"class": "budget", "reason": "prompt exceeded the configured token budget"}
    print(f"[ocr] group {prepare.get('key')}: {len(comments)} comment(s)"
          + (f"; failed ({failure['class']})" if failure else ""))
    C.write_evidence({"key": prepare.get("key") or "", "label": prepare.get("label") or "",
                      "files": prepare.get("files") or [], "failure": failure,
                      "comments": comments, "warnings": warnings})


if __name__ == "__main__":
    C.run(main)
