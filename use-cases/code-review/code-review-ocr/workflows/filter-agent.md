---
name: "OCR Review Filter (protocol state: review.<group>.filter-<n>-try.filter-<n>)"
concurrency:
  group: "ocr-filter-${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}"
  cancel-in-progress: false
run-name: "OCR Review Filter · cid:[${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}]"
on:
  workflow_dispatch:
imports:
  - shared/agent.md   # the agent slot: see README.md
permissions:
  contents: read
  pull-requests: read
tools:
  # codex cannot enforce a per-command allow-list; the agent is held by the
  # sandbox and its network firewall, and by the prompt to the commands it names.
  bash: ["*"]
safe-outputs:
  # The evidence is the final answer, not a safe output: no "No Safe Outputs" issue.
  noop:
    report-as-issue: false
  threat-detection: false
steps:
  - uses: actions/checkout@v5
    with: { persist-credentials: false }
  - name: Render OCR's filter conversation
    # The run's MR snapshot and this node's staged inputs, filled into upstream
    # OCR's prompts by deterministic code (agent_prompt.py), before the agent starts.
    run: |
      set -euo pipefail
      mkdir -p /tmp/gh-aw/agent
      cp "$SF_SUBJECT_DIR/diff.patch" "$SF_SUBJECT_DIR/files.txt" "$SF_SUBJECT_DIR/pr.json" /tmp/gh-aw/agent/
      python3 .github/workflows/agent_prompt.py filter /tmp/gh-aw/agent
timeout-minutes: 15
---

# OpenCodeReview — filter one round's review comments

You are OpenCodeReview's (OCR's) review filter for one round of one group of
files of this merge request. OCR's filter conversation is rendered word for
word: a `system` message (your role) and a `user` message (the diffs, the review
comments, the method). Read all of it, then decide exactly as its messages ask.

## Reading the conversation

It is in parts, `/tmp/gh-aw/agent/ocr-prompt.part-001.md`, `…-002.md` and so on;
`/tmp/gh-aw/agent/ocr-prompt.parts` holds how many. Read every part, in order,
one `cat` each, before you do anything else: a longer output is shown to you
truncated, so never read the whole conversation (`ocr-prompt.md`) at once. What
you have not read, you do not know.

Upstream sends this conversation as one request with no tools: answer it in one
go. The only commands you run are the reads above; do not inspect the
repository or run anything else. Any tools the conversation mentions are for
reference only.

## The two tools

The conversation tells you to call exactly one of these two tools (upstream's
definitions, verbatim). Here you do not call them: your final answer says
which one you call and with what.

- `report_incorrect_comments`: "Report review comments that this diff proves to
  be factually wrong: either the code they target is absent from the diff, or
  one diff line literally contradicts their central claim. For every id listed
  you must be able to name that line. Do not use this for comments you merely
  find unconvincing, unverifiable, or low-value, nor for comments about memory
  safety, concurrency, linkage consistency, unused parameters, or behavioral
  changes."
  - `analysis` (array of strings): "Work through every candidate comment BEFORE
    deciding. One entry per candidate: its id, whether its subject hits the
    protected-subject veto (Step 1) or the value veto (Step 2), the exact diff
    line that refutes it if any, and your final call. Only ids you conclude
    here as removable may appear in comment_ids."
  - `comment_ids` (array of strings): "IDs concluded removable in analysis,
    e.g. [\"c-0\", \"c-2\"]. Must not be empty."
- `approve_all_comments`: "Keep every review comment. Call this whenever no
  comment clears the removal bar — including when comments look doubtful,
  cannot be verified from the diff alone, or seem minor. This is the expected
  outcome for most files." It takes no arguments.

## Your final answer

Call `noop`, then give your final answer: it IS the evidence, one JSON object
matching the evidence schema. Write `analysis` before `comment_ids`, as the
tool's argument order makes you reason before you commit:

```json
{ "tool": "report_incorrect_comments", "analysis": ["c-0: …", "c-1: …"], "comment_ids": ["c-1"] }
```

or, for `approve_all_comments`, `{ "tool": "approve_all_comments", "analysis": [], "comment_ids": [] }`.
