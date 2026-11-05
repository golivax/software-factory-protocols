---
private: true
description: "toy-max assess agent — reads the code node's facts (input), claims the max, as its structured final answer"
on:
  workflow_dispatch:
permissions:
  contents: read
  pull-requests: read
imports:
  - shared/agent.md   # the agent slot: see README.md
safe-outputs:
  # The evidence is the agent's final answer: the factory constrains it to the
  # node's evidence schema and hands it to the engine. Nothing is written.
  staged: true
  noop: {}
---

# Assess agent

You are given deterministic facts about records produced by an upstream **code
node** (this is your INPUT — you did not compute it):

{{#runtime-import .github/compute-facts.json}}

{{#runtime-import .github/_mode.md}}

## Task

1. Read the `records` array. Each record has an `id` and an integer `value`.
2. Identify the record with the **maximum** `value`.
3. Call `noop`, then give your final answer: it IS the evidence, ONE JSON object
   matching the evidence schema (the factory constrains it to that schema and hands
   it to the engine), with:
   - `claimed_max_id`: the `id` of the record with the maximum value (string)
   - `claimed_max_value`: that record's `value` (integer)
   - `assessment`: one short sentence judging the finding (string)

`claimed_max_id` and `claimed_max_value` are factual claims a downstream check
will settle against the code node's output. `assessment` is your judgment and is
not checked. Your final answer is your entire deliverable — do not create
issues, comments, PRs, or labels, and do not use any other output channel.
