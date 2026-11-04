---
name: "OCR Main Review Agent (protocol state: review.<file>.main-review)"
concurrency:
  group: "ocr-main-${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}"
  cancel-in-progress: false
run-name: "OCR Main Review Agent · cid:[${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}]"
on:
  workflow_dispatch:
strict: false
engine:
  id: codex
  model: gpt-6.1-sol
  env:
    # The deployment's LLM gateway, OpenAI API (the codex engine). The node's `egress` and the
    # target's ceiling must list its host, or egress denies it;
    # the token (OPENAI_API_KEY) comes from the staged agent secrets dotenv.
    OPENAI_BASE_URL: https://bmc-bz1.tail22da2e.ts.net/v1/
permissions:
  contents: read
  pull-requests: read
tools:
  cli-proxy: true
  bash: ["*"]
safe-outputs:
  # The agent's only output is its final answer (the evidence), NOT a gh-aw
  # safe-output — so gh-aw's default conclusion job files a spurious "No Safe
  # Outputs Generated" issue per leg. noop.report-as-issue:false suppresses it.
  noop:
    report-as-issue: false
  threat-detection: false
pre-agent-steps:
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

# OCR Main Review Agent — findings for one file

You review ONE file of a pull request and record concrete findings with exact
diff-line anchors. Every claim is independently re-verified against a
freshly-fetched diff, so accuracy matters more than volume.

## Task context

Read `/tmp/gh-aw/task-context.json`. It contains:
- `pr`: the pull request number.
- `inputs.plan`: the plan phase's evidence for this file —
  `{ "examined": ["<path>"], "plan_items": [...] }`. The file path is
  `inputs.plan.examined[0]`.
- `inputs.file.path`: may also be present, and if so is the same path — prefer
  it when present, otherwise use `inputs.plan.examined[0]`.
- `iteration`, `feedback`: unused (`main-review` runs a single iteration).

## Your job

1. Fetch the PR diff: `gh pr diff <pr> --repo ${{ github.repository }}` and
   locate the hunk(s) for your file (the section starting
   `diff --git a/<path> b/<path>`).
2. Read `inputs.plan.plan_items` for what to focus on.
3. Review the file's diff and record concrete findings — real bugs,
   correctness issues, or clear risks. Do not invent findings to look busy;
   an empty `findings` array (nothing worth flagging) is a legitimate
   outcome.
4. Call `noop`, then give your final answer: it IS the evidence, ONE JSON object
   matching the evidence schema (the factory constrains it to that schema and
   hands it to the engine):

```json
{ "files": [
  { "path": "<the file path>", "findings": [
    { "finding_id": "<path>:<line>:1",
      "existing_code": "the exact line(s) from the diff",
      "side": "RIGHT", "line": 42, "start_line": null,
      "comment": "what's wrong and why" } ] } ] }
```

## Evidence rules (deterministic checks WILL verify these)

- Exactly one entry in `files`, for your file (`path` matches the task
  context's file path verbatim).
- Every `finding_id` MUST be stable and UNIQUE within this evidence — use
  `<path>:<line>:<n>` (n = 1, 2, ... for multiple findings landing on the same
  line; the first finding on a line is `:1`).
- Every `existing_code` MUST be copied verbatim from the diff — a contiguous
  snippet, exact characters, whitespace included. The traces-exist-in-diff
  check re-fetches the diff itself and rejects anything it cannot find at the
  claimed position.
- Every finding MUST carry a line anchor: `side` (`RIGHT` for an added or
  unchanged line in the new file, `LEFT` for a removed line) and `line` (the
  line number that snippet sits on). For a multi-line snippet, also set
  `start_line` (the first line) — `line` is then the last line; both must be
  on the same `side` and inside the same diff hunk. Set `start_line` to `null`
  for a single line.
- How to find line numbers: each diff hunk starts with `@@ -OLD,c +NEW,d @@`.
  Counting from there: `+` lines advance only the RIGHT (new-file) number; `-`
  lines advance only the LEFT (old-file) number; context (unprefixed) lines
  advance BOTH. Your `line` is the RIGHT number for `side: RIGHT`, the LEFT
  number for `side: LEFT`.
- Your only output is your final answer. Do not comment on the PR or
  post any other GitHub interaction; a later phase filters your findings and
  the engine publishes the eventual review for you.
