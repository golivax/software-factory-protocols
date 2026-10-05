---
private: true
description: "toy-max assess agent — reads the code node's facts (input), claims the max, emits evidence via a custom safe-output"
on:
  workflow_dispatch:
permissions:
  contents: read
  pull-requests: read
engine:
  id: codex
  model: gpt-5.5
  env:
    OPENAI_BASE_URL: https://arcyleung-ubuntu.tailb940e6.ts.net/v1/
safe-outputs:
  # Evidence is a FIRST-CLASS custom safe-output (a gh-aw "safe-job"), not a
  # noop message the orchestrator scrapes from the log. Declaring it here:
  #   1. exposes an MCP tool named `evidence` to the agent, whose input schema
  #      is generated from `inputs` below (strict: additionalProperties=false);
  #   2. makes gh-aw shape-validate + type-check + threat-scan (sanitizeContent)
  #      the agent's call before it lands in the aggregated agent_output.json;
  #   3. runs the `steps` job which reads that validated item from
  #      $GH_AW_AGENT_OUTPUT and materializes it to a file the orchestrator reads.
  # NOTE: gh-aw has no `integer` input type — `claimed_max_value` is `number`
  # (jq preserves 47 as an integer; the orchestrator coerces whole floats).
  jobs:
    evidence:
      description: "Emit the toy-max assessment evidence for the orchestrator to settle."
      runs-on: ubuntu-latest
      permissions:
        contents: read
      inputs:
        claimed_max_id:
          description: "CHECKABLE claim — id of the record the agent says holds the max value."
          type: string
          required: true
        claimed_max_value:
          description: "CHECKABLE claim — the max value the agent read."
          type: number
          required: true
        assessment:
          description: "JUDGMENT — the agent's one-sentence opinion; not settled by a check."
          type: string
          required: true
      output: "Evidence recorded."
      steps:
        - name: Materialize evidence JSON
          run: |
            set -euo pipefail
            jq -c '[.items[] | select(.type=="evidence")][0]
                   | {claimed_max_id, claimed_max_value, assessment}' \
              "$GH_AW_AGENT_OUTPUT" > "$GITHUB_WORKSPACE/evidence-out.json"
            echo "GH_AW_EVIDENCE=$(cat "$GITHUB_WORKSPACE/evidence-out.json")"
            cat "$GITHUB_WORKSPACE/evidence-out.json"
---

# Assess agent

You are given deterministic facts about records produced by an upstream **code
node** (this is your INPUT — you did not compute it):

{{#runtime-import .github/compute-facts.json}}

{{#runtime-import .github/_mode.md}}

## Task

1. Read the `records` array. Each record has an `id` and an integer `value`.
2. Identify the record with the **maximum** `value`.
3. Emit your evidence by calling the **`evidence`** safe-output tool **exactly
   once**, with these arguments:
   - `claimed_max_id`: the `id` of the record with the maximum value (string)
   - `claimed_max_value`: that record's `value` (number)
   - `assessment`: one short sentence judging the finding (string)

`claimed_max_id` and `claimed_max_value` are factual claims a downstream check
will settle against the code node's output. `assessment` is your judgment and is
not checked. The `evidence` tool call is your entire deliverable — do not create
issues, comments, PRs, or labels, and do not use any other output channel.
