---
name: "OCR Grouping (protocol state: grouping-try.grouping)"
concurrency:
  group: "ocr-grouping-${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}"
  cancel-in-progress: false
run-name: "OCR Grouping · cid:[${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}]"
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
  - name: Render OCR's grouping conversation
    # The run's MR snapshot and this node's staged inputs, filled into upstream
    # OCR's prompts by deterministic code (agent_prompt.py), before the agent starts.
    run: |
      set -euo pipefail
      mkdir -p /tmp/gh-aw/agent
      cp "$SF_SUBJECT_DIR/diff.patch" "$SF_SUBJECT_DIR/files.txt" "$SF_SUBJECT_DIR/pr.json" /tmp/gh-aw/agent/
      python3 .github/workflows/agent_prompt.py grouping /tmp/gh-aw/agent
timeout-minutes: 10
---

# OpenCodeReview — group the changed files

You are OpenCodeReview's (OCR's) file-grouping step for this merge request.
OCR's grouping conversation is rendered word for word: a `system` message and a
`user` message. Read all of it, then answer it exactly as its messages ask.

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

## Your final answer

Call `noop`, then give your final answer: it IS the evidence, one JSON object
matching the evidence schema. Its `groups` is the JSON array the conversation
asks for, unchanged:

```json
{ "groups": [ { "label": "short theme description", "files": [0, 1] } ] }
```
