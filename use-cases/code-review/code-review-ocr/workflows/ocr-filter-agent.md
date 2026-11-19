---
name: "OCR Filter Agent (protocol state: review.<file>.findings.<finding>)"
concurrency:
  group: "ocr-filter-${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}"
  cancel-in-progress: false
run-name: "OCR Filter Agent · cid:[${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}]"
on:
  workflow_dispatch:
strict: false
imports:
  - shared/agent.md   # the agent slot: see README.md
permissions:
  contents: read
  pull-requests: read
tools:
  bash: ["*"]
safe-outputs:
  # The agent's only output is its final answer (the evidence), NOT a gh-aw
  # safe-output — so gh-aw's default conclusion job files a spurious "No Safe
  # Outputs Generated" issue per leg. noop.report-as-issue:false suppresses it.
  noop:
    report-as-issue: false
  threat-detection: false
pre-agent-steps:
  - name: Stage the MR for the agent
    # The run's snapshot ($SF_SUBJECT_DIR): the diff, the changed files and pr.json of
    # the commit the run is pinned to, the bytes this node's checks read. The forge
    # (`gh pr diff`, the GitHub tools) answers for the MR's head at the moment, which a
    # push can have moved since the run started. A snapshot the factory could not
    # compute (pr.json names the MR, no base_sha) fails the step: an empty diff is not
    # an MR that changes nothing.
    run: |
      set -euo pipefail
      mkdir -p /tmp/gh-aw/agent
      python3 - "$SF_SUBJECT_DIR/pr.json" <<'PY'
      import json, sys
      pr = json.load(open(sys.argv[1]))
      if pr.get("number") and not pr.get("base_sha"):
          sys.exit(f"the factory could not compute MR {pr['number']}'s diff (pr.json names no base_sha)")
      PY
      cp "$SF_SUBJECT_DIR/diff.patch" "$SF_SUBJECT_DIR/files.txt" "$SF_SUBJECT_DIR/pr.json" /tmp/gh-aw/agent/
  - name: Materialize task context
    env:
      CTX: ${{ github.event.inputs.aw_context }}
    run: |
      mkdir -p /tmp/gh-aw
      if [ -z "$CTX" ]; then CTX='{}'; fi
      printf '%s' "$CTX" > /tmp/gh-aw/task-context.json
      cat /tmp/gh-aw/task-context.json
timeout-minutes: 10
---

# OCR Filter Agent — keep/drop one finding

You are the last-mile filter (OCR ReviewFilter) for ONE candidate finding
raised by the main-review phase. Decide whether it survives into the posted
review: drop it if it is hallucinated, a duplicate of something already
obviously covered, or too low-value to be worth a human's time; otherwise
keep it and make sure its anchor is still accurate.

## Task context

Read `/tmp/gh-aw/task-context.json`. `inputs.finding` is the candidate:
`{ "finding_id", "path", "existing_code", "side", "line"[, "start_line"],
"comment" }`.

## Your job

1. Read the PR diff, `/tmp/gh-aw/agent/diff.patch`: the diff of the commit
   under review (`head_sha` in `/tmp/gh-aw/agent/pr.json`), the one the checks
   verify your answer against. Do not fetch the PR yourself: its head may have
   moved since this run started.
   Locate the hunk(s) for `inputs.finding.path`.
2. Confirm `inputs.finding.existing_code` still sits at `side`/`line`
   (/`start_line`) in that hunk. If the surrounding diff shifted, relocate the
   anchor to wherever that exact snippet now sits (same side, same hunk); if
   it no longer appears at all, treat the finding as hallucinated and drop
   it.
3. Decide `keep`:
   - drop (`keep: false`) if: the snippet cannot be located in the diff
     (hallucinated), the finding restates something a competent reviewer
     would not bother commenting on, or it's a near-duplicate of a more
     specific concern about the same code.
   - keep (`keep: true`) otherwise.
4. Call `noop`, then give your final answer: it IS the evidence, ONE JSON object
   matching the evidence schema (the factory constrains it to that schema and
   hands it to the engine):

```json
{ "finding_id": "<inputs.finding.finding_id, verbatim>",
  "keep": true,
  "anchor": { "side": "RIGHT", "line": 42, "start_line": null },
  "reason": "short justification",
  "path": "<inputs.finding.path>",
  "existing_code": "<inputs.finding.existing_code (or the relocated snippet)>",
  "comment": "<inputs.finding.comment>" }
```

## Evidence rules (deterministic checks WILL verify these)

- `finding_id` MUST echo `inputs.finding.finding_id` verbatim.
- `keep` is a boolean. When `keep` is `true`, `anchor` is
  `{ "side": "RIGHT"|"LEFT", "line": <int>, "start_line": <int>|null }`, and it
  must resolve to the real `existing_code` snippet in the independently
  -fetched diff (same rules as the main-review phase: `+`/`-`/context lines
  advance RIGHT/LEFT/both from each hunk's `@@ -OLD +NEW @@` header). When
  `keep` is `false`, `anchor` is `null`.
- Also echo `path`, `existing_code`, and `comment` back — verbatim, or the
  relocated `existing_code` if you moved the anchor: the downstream
  reduce/post-review step needs them to render the review comment.
- `reason` is a short (one sentence) justification for the decision.
- Your only output is your final answer. Do not comment on the PR or
  post any other GitHub interaction; the engine publishes the eventual review
  for you.
