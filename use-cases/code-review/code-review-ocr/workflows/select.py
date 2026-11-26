#!/usr/bin/env python3
"""`select`: which changed files OCR reviews, and how they will be grouped.

Upstream: Agent.Run's diff load (diff/git.go GetDiffSet: the root .gitignore and
the provider's directory list), selectFiles (selection.go), then the grouping
decision groupDiffs makes before any LLM call (grouping.go, Template.GroupingPlan).

Runs on the repository checked out at the run's commit (`checkout`), which holds
the root .gitignore and the rule.json layers. Evidence: the paths of each set,
the exclusions with upstream's reasons, the grouping strategy and, for an LLM
grouping, the file list the grouping prompt shows.
"""
import os
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ocr import context as C  # noqa: E402
from ocr import diffs as D  # noqa: E402
from ocr import rules as R  # noqa: E402
from ocr import selection as S  # noqa: E402


def main():
    repo = os.environ.get("GITHUB_WORKSPACE", "")
    inputs = C.protocol_inputs()
    parsed = C.all_parsed_diffs()
    # LoadGitignoreAtRef: the root .gitignore as the reviewed commit holds it
    r = subprocess.run(["git", "show", "HEAD:.gitignore"], cwd=repo or None, capture_output=True)
    gitignore = r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
    included, provider_excluded = D.partition_diffs(parsed, D.parse_gitignore(gitignore))

    resolver = R.Resolver(repo, inputs.get("rule") or "", ref="HEAD")
    tpl = S.template()
    decisions = S.select_files(included, resolver.file_filter(), tpl["MAX_TOKENS"])
    kept = [d for d, reason in decisions if reason in ("", "deleted")]
    selected = [d for d, reason in decisions if reason == ""]

    excluded = [{"path": D.effective_path(d), "reason": "provider_directory"} for d in provider_excluded]
    excluded += [{"path": D.effective_path(d), "reason": reason}
                 for d, reason in decisions if reason not in ("", "deleted")]
    warnings = []
    too_large = sum(1 for _, reason in decisions if reason == "too_large")

    if not selected:
        strategy = "none"
        message = (f"{too_large} file(s) exceeded the token size limit; nothing left to review."
                   if too_large else "No supported files changed.")
    else:
        total, _ = S.diffs_churn(selected)
        strategy = "per_file" if len(selected) <= 1 else S.grouping_plan(tpl, len(selected), total)
        message = f"{len(parsed)} file(s) changed, reviewing {len(selected)}"
    print(f"[ocr] {message}")
    for e in excluded:
        print(f"[ocr]   excluded {e['path']}: {e['reason']}")

    C.write_evidence({
        # this run's tag for the forge writes `post` makes (no code node sees a
        # run id): a retried `post` finds what it already posted by it
        "run": uuid.uuid4().hex[:12],
        "strategy": strategy,
        "message": message,
        "changed": len(parsed),
        "included": [D.effective_path(d) for d in included],
        "kept": [D.effective_path(d) for d in kept],
        "selected": [D.effective_path(d) for d in selected],
        "excluded": excluded,
        "file_list": S.build_file_list(selected) if strategy == "llm" else "",
        "warnings": warnings,
    })


if __name__ == "__main__":
    C.run(main)
