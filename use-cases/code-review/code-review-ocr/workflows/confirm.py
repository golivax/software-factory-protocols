#!/usr/bin/env python3
"""`confirm-<n>`: what round <n> confirmed, and whether round <n+1> runs.

Upstream: the end of a round in executeGroupSubtask (agent.go). The review
filter's answer removes the candidates it reports (parseFilterToolCalls: ids
`c-<index>`, out-of-range ones ignored; `approve_all_comments`, or no answer
because the filter agent failed, removes none). The surviving candidates are
the round's newly confirmed findings, shown to the next round. Another round
runs only when this one confirmed something new, the group holds fewer than 30
confirmed findings, rounds remain, and the next round's prompt fits the budget
(checkPromptBudget; it warns `token_threshold_exceeded` when it does not).

A round whose main task failed (no answer, or task_done FAILED) ends the group.
In round 1 that fails the group's files (`failure`, which `post` counts as
upstream's manifest counts a failed item); a later round keeps every comment
already filed and warns `review_round_failed`. The node's `params.round` is its
round number.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ocr import context as C  # noqa: E402
from ocr import render as T  # noqa: E402
from ocr import selection as S  # noqa: E402

ID_RE = re.compile(r"c-([+-]?\d+)")


def removed_candidates(filter_answer, total):
    if not filter_answer or filter_answer.get("tool") != "report_incorrect_comments":
        return set()
    out = set()
    for cid in filter_answer.get("comment_ids") or []:
        m = ID_RE.match(cid) if isinstance(cid, str) else None
        if m and 0 <= int(m.group(1)) < total:
            out.add(int(m.group(1)))
    return out


def next_round_tokens(prepare, confirmed):
    """The estimated size of the next round's prompt: no plan, the confirmed findings."""
    sel = C.Selection(C.read_input("select"))
    diffs = C.by_paths(sel.kept, prepare.get("files") or [])
    msgs = T.main(date=prepare.get("date") or "", rule=prepare.get("system_rule") or "",
                  change_files=S.build_change_files_except_group(sel.kept, diffs),
                  diffs=S.build_concatenated_diffs(diffs), background=prepare.get("background") or "",
                  plan_result="", confirmed=T.confirmed_block(confirmed),
                  language=prepare.get("language") or "English")
    return sum(S.count_tokens(c) for _, c in msgs)


def main():
    rnd = int((C.protocol_context().get("params") or {}).get("round") or 1)
    settle = C.read_input("settle") or {}
    prepare = C.read_input("prepare") or {}
    previous = C.read_input("previous") or {"confirmed": [], "comments": [], "warnings": [],
                                             "completed": False}
    warnings = list(previous.get("warnings") or []) + list(settle.get("warnings") or [])

    earlier = previous.get("comments") or []
    comments = settle.get("comments") or []
    if not settle.get("ran") or settle.get("state") != "DONE":
        # The round's main task failed: its agent did not answer, or ended with
        # task_done FAILED (RunMainTask's "task failed" error). Round 1 fails the
        # group's files; a later round keeps every comment already filed, this
        # round's unfiltered (the filter runs only after a completed loop).
        why = "the review agent failed" if not settle.get("ran") else "task failed: task_done reported FAILED"
        doc = {"round": rnd, "continue": False, "confirmed": previous.get("confirmed") or [],
               "comments": earlier + comments, "warnings": warnings}
        if rnd == 1:
            doc["failure"] = {"class": "provider", "reason": why}
        else:
            doc["warnings"] = warnings + [{"type": "review_round_failed", "file": prepare.get("key") or "",
                                           "message": f"round {rnd}: {why}"}]
        C.write_evidence(doc)
        return

    candidates = settle.get("candidates") or []
    removed = {candidates[k] for k in removed_candidates(C.read_input("filter"), len(candidates))}
    newly = [comments[i] for i in candidates if i not in removed]
    confirmed = (previous.get("confirmed") or []) + newly
    kept = [cm for i, cm in enumerate(comments) if i not in removed]
    rounds = int(prepare.get("rounds") or 1)
    more = bool(newly) and len(confirmed) < T.CONFIRMED_CAP and rnd < rounds
    if removed:
        print(f"[ocr] review filter removed {len(removed)} comment(s)")
    if not newly and rnd < rounds:
        print(f"[ocr] round {rnd}/{rounds} added no new findings; stopping early")
    if more:
        tokens = next_round_tokens(prepare, confirmed)
        limit = S.template()["MAX_TOKENS"]
        if tokens > S.prompt_token_limit(limit):
            # checkPromptBudget before round n+1: the group stops, as it is.
            more = False
            warnings.append({"type": "token_threshold_exceeded", "file": prepare.get("key") or "",
                             "message": f"prompt tokens ({tokens}) exceed 80% of max_tokens({limit}) "
                                        f"[round {rnd + 1}]"})
    C.write_evidence({"round": rnd, "continue": more, "confirmed": confirmed, "comments": earlier + kept,
                      "warnings": warnings})


if __name__ == "__main__":
    C.run(main)
