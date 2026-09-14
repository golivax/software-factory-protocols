---
private: true
description: "demo summarize agent — echoes the code node's token and writes a one-sentence MR summary, via a custom evidence safe-output"
on:
  workflow_dispatch:
permissions:
  contents: read
engine:
  id: codex
  model: gpt-5.5
  env:
    # [HOST-VERIFY] your LLM gateway base URL (the agent lane's only external creds
    # beyond the forge proxy). ANTHROPIC/OPENAI token is supplied by run-under-act.sh
    # from OPENAI_KEY_FILE.
    OPENAI_BASE_URL: https://YOUR-LLM-GATEWAY/v1/
safe-outputs:
  # Evidence is a first-class gh-aw safe-output: declaring it exposes an MCP tool
  # `evidence` whose input schema is generated from `inputs`, shape/type-checks +
  # threat-scans the agent's call, then the `steps` job materializes the validated
  # item to evidence-out.json — which the SbxDispatcher reads off the bound
  # workspace and the engine settles with checks/summary-present.py.
  jobs:
    evidence:
      description: "Emit the demo summarize evidence for the orchestrator to settle."
      runs-on: ubuntu-latest
      permissions:
        contents: read
      inputs:
        saw_token:
          description: "CHECKABLE — the `token` received from the facts code node, echoed verbatim."
          type: string
          required: true
        summary:
          description: "JUDGMENT — a one-sentence summary of the MR; not settled by a check."
          type: string
          required: true
      output: "Evidence recorded."
      steps:
        - name: Materialize evidence JSON
          run: |
            set -euo pipefail
            jq -c '[.items[] | select(.type=="evidence")][0]
                   | {saw_token, summary}' \
              "$GH_AW_AGENT_OUTPUT" > "$GITHUB_WORKSPACE/evidence-out.json"
            cat "$GITHUB_WORKSPACE/evidence-out.json"
---

# Summarize agent

You are given the output of an upstream **code node** (`facts`) as your INPUT — a
JSON object with a `token` field you did NOT compute:

{{#runtime-import inputs/facts.json}}

## Task

1. Read the `token` from the facts above.
2. Write ONE short sentence summarizing this merge request (what it changes, at a
   glance). This is your judgment.
3. Emit your evidence by calling the **`evidence`** safe-output tool **exactly
   once**, with:
   - `saw_token`: the `token` value from the facts input, **verbatim** (string)
   - `summary`: your one-sentence summary (string)

`saw_token` is a factual claim a downstream check settles (it proves the input
round-tripped). `summary` is your judgment and is not checked. The `evidence` tool
call is your entire deliverable — do not open issues, comments, PRs, or labels, and
do not use any other output channel.
