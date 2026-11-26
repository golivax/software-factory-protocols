#!/usr/bin/env python3
"""`prepare`: one group's review set-up, before its plan and rounds.

Upstream: the head of executeGroupSubtask (agent.go): the group's merged
review rules (resolveGroupSystemRule), whether it gets a plan
(Template.PlanRequired), its round count (--effort), the run's timestamp and
background, and the round-1 prompt-budget check (checkPromptBudget), which
stops a group whose first prompt would not fit.

Runs on the repository checked out at the run's commit: the rule.json layers
and the `.m` sniff read it. The group is this leg's item, inputs/group.json.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ocr import context as C  # noqa: E402
from ocr import render as T  # noqa: E402
from ocr import rules as R  # noqa: E402
from ocr import selection as S  # noqa: E402

EFFORT_ROUNDS = {"low": 1, "medium": 2, "high": 3}


def main():
    group = C.read_input("group") or {}
    sel = C.Selection(C.read_input("select"))
    inputs = C.protocol_inputs()
    repo = os.environ.get("GITHUB_WORKSPACE", "")
    diffs = C.by_paths(sel.kept, group.get("files") or [])
    if not diffs:
        raise C.Failure(f"group {group.get('id')!r} names no file of the selection")

    tpl = S.template()
    rule = R.resolve_group_rule(R.Resolver(repo, inputs.get("rule") or "", ref="HEAD"), diffs)
    total, max_file = S.diffs_churn(diffs)
    effort = str(inputs.get("effort") or "medium").lower()
    rounds = EFFORT_ROUNDS.get(effort, EFFORT_ROUNDS["medium"])
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    background = inputs.get("background") or ""
    language = inputs.get("language") or "English"

    first = T.main(date=date, rule=rule,
                   change_files=S.build_change_files_except_group(sel.kept, diffs),
                   diffs=S.build_concatenated_diffs(diffs), background=background,
                   plan_result="", confirmed="", language=language)
    prompt_tokens = sum(S.count_tokens(c) for _, c in first)
    over_budget = prompt_tokens > S.prompt_token_limit(tpl["MAX_TOKENS"])
    plan = S.plan_required(tpl, len(diffs), total, max_file) and not over_budget

    print(f"[ocr] group {group.get('key')}: {len(diffs)} file(s), {total} changed line(s), "
          f"plan {'yes' if plan else 'skipped'}, {rounds} round(s)")
    C.write_evidence({
        "key": S.file_group_key(diffs),
        "label": group.get("label") or "",
        "files": [d["new_path"] for d in diffs],
        "plan": plan,
        "rounds": rounds,
        "over_budget": over_budget,
        "prompt_tokens": prompt_tokens,
        "system_rule": rule,
        "date": date,
        "background": background,
        "language": language,
    })


if __name__ == "__main__":
    C.run(main)
