#!/usr/bin/env python3
"""`partition`: the review groups, one fork leg each.

Upstream: groupDiffs (grouping.go). An LLM grouping's answer is parsed by
parseGroupingResponse and split by the token budget; a missing answer (the
grouping agent failed) falls back to one group per file, as upstream does on a
failed grouping call. Below the thresholds the groups are formed without the
LLM (groupWithoutLLM).

A fork has at most 256 legs; groups past the 256th are not reviewed and are
named in the warnings (upstream has no cap).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ocr import context as C  # noqa: E402
from ocr import selection as S  # noqa: E402

MAX_LEGS = 256


def main():
    select = C.read_input("select") or {}
    grouping = C.read_input("grouping")
    sel = C.Selection(select)
    diffs = sel.selected
    strategy = select.get("strategy")
    limit = S.prompt_token_limit(S.template()["MAX_TOKENS"])
    warnings = []

    if strategy == "none" or not diffs:
        groups = []
    elif strategy == "llm":
        if grouping is None or not isinstance(grouping.get("groups"), list):
            print("[ocr] LLM grouping failed, falling back to per-file dispatch")
            warnings.append({"type": "grouping_failed", "file": "",
                             "message": "LLM grouping failed; files reviewed one group per file"})
            groups = S.single_file_groups(diffs)
        else:
            groups = S.enforce_group_token_budget(
                S.parse_grouping_response(grouping["groups"], diffs), limit)
    else:
        groups = S.group_without_llm(diffs, strategy, limit)

    if len(groups) > MAX_LEGS:
        for g in groups[MAX_LEGS:]:
            for d in g["diffs"]:
                warnings.append({"type": "group_cap", "file": d["new_path"],
                                 "message": f"not reviewed: the review has more than {MAX_LEGS} groups"})
        groups = groups[:MAX_LEGS]

    items = [{"id": f"g{i + 1:03d}", "label": g["label"], "key": S.file_group_key(g["diffs"]),
              "files": [d["new_path"] for d in g["diffs"]]} for i, g in enumerate(groups)]
    for it in items:
        print(f"[ocr] group {it['id']} {it['label']!r}: {', '.join(it['files'])}")
    C.write_evidence({"groups": items, "warnings": warnings})


if __name__ == "__main__":
    C.run(main)
