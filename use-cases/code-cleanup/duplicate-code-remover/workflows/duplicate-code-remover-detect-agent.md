---
name: "Duplicate-Code-Remover Detect Agent (protocol state: detect)"
run-name: "Duplicate-Code-Remover Detect · cid:[${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}]"
on:
  workflow_dispatch:
strict: false
engine:
  id: codex
  model: gpt-6.1-sol
  env:
    # The deployment's LLM gateway, OpenAI API (the codex engine). Must match an entry
    # in deploy/.env LLM_ENDPOINTS (set-egress.sh allowlists it) or egress denies it;
    # the token (OPENAI_API_KEY) comes from the staged agent secrets dotenv.
    OPENAI_BASE_URL: https://bmc-bz1.tail22da2e.ts.net/v1/
permissions:
  contents: read
  issues: read
  pull-requests: read
tools:
  cli-proxy: true
  bash: [":*"]
mcp-servers:
  serena:
    container: "ghcr.io/github/serena-mcp-server:latest"
    args: ["--network", "host"]
    entrypoint: "serena"
    entrypointArgs:
      - "start-mcp-server"
      - "--context"
      - "codex"
      - "--project"
      - "${GITHUB_WORKSPACE}/target"
    mounts:
      - "${GITHUB_WORKSPACE}:${GITHUB_WORKSPACE}:rw"
safe-outputs:
  add-comment:
    max: 1
  noop:
    report-as-issue: false
  threat-detection: false
pre-agent-steps:
  - name: Materialize task context
    env:
      CTX: ${{ github.event.inputs.aw_context }}
    run: |
      mkdir -p /tmp/gh-aw/agent
      if [ -z "$CTX" ]; then CTX='{}'; fi
      printf '%s' "$CTX" > /tmp/gh-aw/task-context.json
      cat /tmp/gh-aw/task-context.json
  - name: Checkout target ref
    uses: actions/checkout@v5
    with:
      ref: ${{ fromJSON(github.event.inputs.aw_context || '{}').ref }}
      path: target
      persist-credentials: false
      fetch-depth: 0
timeout-minutes: 40
---

# Detect Agent — C++ duplicate-code scan (evidence only; NO issues, NO writes)

Working directory of the analyzed code: `target/` (checked out at the requested ref).

## 1. Read the task
Your ONLY output is your final answer: the evidence (step 5). Do NOT create issues or
comments. Read `/tmp/gh-aw/task-context.json` (`iteration`, `feedback`); on iteration > 1 fold
the `feedback` (failed checks) into this pass.

## 2. Activate Serena for C++
Call `activate_project` with path `${GITHUB_WORKSPACE}/target`. Serena is configured
for C/C++ via clangd. If Serena/clangd is unavailable, fall back to `search_for_pattern`
+ bash (`grep -rn`, `find target -name '*.cpp'`) — still give valid evidence.

## 3. Scope — BOUNDED (this is a large repo; do NOT scan it all)
Analyze ONLY C++ sources under `target/`:
- Include: `*.cpp`, `*.cc`, `*.cxx`, `*.hpp`, `*.hh`, `*.h`.
- Exclude: tests (`*_test.*`, `*Test.*`, files under `test/`, `tests/`, `__tests__/`),
  `third_party/`, generated code, and build dirs.
- **Bound the scan to ~40 source files at most.** Pick a focused, high-yield slice —
  files that share a naming/purpose family are the richest duplication source. Good
  starting points here: `src/datasystem/**` (e.g. `pybind_api/pybind_register_*.cpp`,
  `*_client.cpp`), and the client examples. Use `find target/src -name '*.cpp'` and
  `git -C target log --name-only -20` to pick candidates. Do NOT attempt to index or
  read the whole tree.

## TIME BUDGET — give your evidence promptly (hard requirement)
You have a limited wall-clock budget and MUST finish with your evidence as your final answer.
- **Prefer `search_for_pattern`** (fast, grep-like) and targeted `get_symbols_overview`
  on your bounded file set. AVOID `find_referencing_symbols` and whole-repo indexing —
  they are slow here (no compilation database) and not needed to find duplication.
- Stop as soon as you have **up to 3 solid patterns** (or have examined ~40 files with
  none) and give your evidence immediately. A prompt, correct, bounded result beats an
  exhaustive one — an incomplete run that never answers FAILS the check.

## 4. Detect duplication
Within your bounded slice, find true duplication with `search_for_pattern` +
`get_symbols_overview`: identical/near-identical functions across files, repeated logic
blocks (>10 lines or 3+ occurrences), copy-paste with minor edits (e.g. repeated struct
initializers / connection-config setup, near-identical client methods). Skip boilerplate,
getters/setters, and small (<5 line) snippets unless highly repetitive.

## 5. Give your evidence
Call `noop`, then give your final answer: it IS the evidence, ONE JSON object matching
the evidence schema (the factory constrains it to that schema and hands it to the engine):
- `scanned`: the files/symbols you actually examined (REQUIRED, non-empty, even if you
  find nothing).
- `patterns`: ≤3 most significant patterns. Each: `id` (stable slug), `name`,
  `severity` (high|medium|low), `rationale`, and `locations` (≥2), each with `path`
  (repo-relative, WITHOUT the `target/` prefix), `start_line`, `end_line`, and
  **verbatim** `existing_code` copied exactly from the file (the checks re-read the
  file and compare byte-for-byte, trailing-whitespace-insensitive — do not paraphrase).
- No duplication found → `patterns: []` with a non-empty `scanned`.

Paths in `existing_code` locations MUST be relative to `target/` (e.g. `src/a.cpp`,
not `target/src/a.cpp`) — the checks read them from the scanned-ref checkout root.
