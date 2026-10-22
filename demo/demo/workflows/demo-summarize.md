---
private: true
description: "demo summarize agent — echoes the code node's token and writes a one-sentence MR summary, as its structured final answer"
on:
  workflow_dispatch:
permissions:
  contents: read
  pull-requests: read
engine:
  id: codex
  model: gpt-6-luna
  env:
    # The deployment's LLM gateway, OpenAI API (the codex engine). Must match an entry
    # in deploy/.env LLM_ENDPOINTS (set-egress.sh allowlists it) or egress denies it;
    # the token (OPENAI_API_KEY) comes from the staged agent secrets dotenv.
    OPENAI_BASE_URL: https://bmc-bz1.tail22da2e.ts.net/v1/
safe-outputs:
  # The evidence is the agent's final answer: the factory constrains it to the
  # node's evidence schema and hands it to the engine. Nothing is written.
  staged: true
  noop: {}
---

# Summarize agent

You are given the output of an upstream **code node** (`facts`) as your INPUT — a
JSON object with a `token` field you did NOT compute:

{{#runtime-import inputs/facts.json}}

## Task

1. Read the `token` from the facts above.
2. Write ONE short sentence summarizing this merge request (what it changes, at a
   glance). This is your judgment.
3. Call `noop`, then give your final answer: it IS the evidence, ONE JSON object
   matching the evidence schema (the factory constrains it to that schema and hands
   it to the engine), with:
   - `saw_token`: the `token` value from the facts input, **verbatim** (string)
   - `summary`: your one-sentence summary (string)

`saw_token` is a factual claim a downstream check settles (it proves the input
round-tripped). `summary` is your judgment and is not checked. Your final answer
is your entire deliverable — do not open issues, comments, PRs, or labels, and do
not use any other output channel.
