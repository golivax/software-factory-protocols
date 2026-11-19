---
name: "OCR Plan Agent (protocol state: review.<file>.plan)"
concurrency:
  group: "ocr-plan-${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}"
  cancel-in-progress: false
run-name: "OCR Plan Agent · cid:[${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}]"
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

# OCR Plan Agent — per-file review scoping

You are the first phase of a per-file code review sub-pipeline (OCR-style:
plan → main-review → per-finding filter). Your only job is to scope what the
next phase should look at — do NOT record findings or verdicts here.

## Task context

Read `/tmp/gh-aw/task-context.json`. It contains:
- `pr`: the pull request number.
- `inputs.file.path`: the file this leg is scoped to. This is the ONLY thing
  you need to identify your file — the diff itself is NOT inlined (only
  `path` rides the dispatch matrix); it is staged for you (below).
- `iteration`, `feedback`: unused (`plan` runs a single iteration).

## Your job

1. Read the PR diff, `/tmp/gh-aw/agent/diff.patch`: the diff of the commit
   under review (`head_sha` in `/tmp/gh-aw/agent/pr.json`), the one the checks
   verify your answer against. Do not fetch the PR yourself: its head may have
   moved since this run started.
2. Find the hunk(s) for `inputs.file.path` (the section starting
   `diff --git a/<path> b/<path>`) and read it.
3. Call `noop`, then give your final answer: it IS the evidence, ONE JSON object
   matching the evidence schema (the factory constrains it to that schema and
   hands it to the engine):

```json
{ "examined": ["<inputs.file.path value, verbatim>"],
  "plan_items": ["short note on what to look at in the next phase", "..."] }
```

## Evidence rules

- `examined` MUST be exactly a one-element array containing `inputs.file.path`
  verbatim — that is what proves you looked at the right file.
- `plan_items` is a short list (1-5 items) of concrete, natural-language
  scoping notes for the main-review phase (risk areas, functions touched,
  things worth double-checking). Do not fabricate findings or issue verdicts
  here — that is the next phase's job.
- Your only output is your final answer. Do not comment on the PR or
  post any other GitHub interaction; the engine publishes the eventual review
  for you once every phase's evidence passes checks.
