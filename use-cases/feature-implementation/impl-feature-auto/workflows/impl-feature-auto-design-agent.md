---
name: "Impl-Feature-Auto Design Agent (protocol state: design)"
run-name: "Impl-Feature-Auto Design · cid:[${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}]"
on:
  workflow_dispatch:
concurrency:
  # Per-dispatch (cid) group so fixer instances triggered on DIFFERENT issues run
  # in PARALLEL. gh-aw's default `gh-aw-${{ github.workflow }}` serializes every run
  # of this one workflow, which made issue-X's design wait on issue-Y's. cid is
  # unique per orchestrator dispatch, so each issue's design gets its own group.
  group: "impl-feature-auto-design-${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}"
  cancel-in-progress: false
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
  edit: true
  bash: [":*"]
safe-outputs:
  # The design agent produces NO GitHub writes — its only output is its final
  # answer (the evidence) plus the spec + plan artifact (post-steps). But gh-aw auto-injects a default `create-issue` (a per-run
  # status issue) whenever an agent declares no real safe-output. Declaring one
  # real output suppresses that auto-injection; the agent's prompt forbids it from
  # emitting a comment, so this capability stays unused (no status issue, no comment).
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
  - name: Stage superpowers skills (pinned release tag)
    run: |
      set -euo pipefail
      SP_VERSION="v6.0.3"; DEST="$GITHUB_WORKSPACE/.agents/skills"
      mkdir -p "$DEST"
      curl -fsSL "https://github.com/obra/superpowers/archive/refs/tags/${SP_VERSION}.tar.gz" -o /tmp/sp.tgz
      tar -xzf /tmp/sp.tgz --strip-components=2 -C "$DEST" "superpowers-${SP_VERSION#v}/skills"
      ls "$DEST" | head
  - name: Prefetch the issue
    env:
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      ISSUE: ${{ fromJSON(github.event.inputs.aw_context || '{}').pr }}
      REPO: ${{ github.repository }}
    run: |
      set -euo pipefail
      gh issue view "$ISSUE" --repo "$REPO" \
        --json number,title,body,labels,author,url > /tmp/gh-aw/agent/issue.json
      cat /tmp/gh-aw/agent/issue.json
post-steps:
  - name: Bundle the spec + plan
    if: always()
    run: |
      set -uo pipefail
      OUT=/tmp/gh-aw/evidence
      mkdir -p "$OUT"
      # The agent wrote them under target/ at the paths the prompt names (§2, §3);
      # copy the newest of each in by fixed name.
      SPEC=$(ls -t "$GITHUB_WORKSPACE"/target/docs/superpowers/specs/*-design.md 2>/dev/null | head -1)
      PLAN=$(ls -t "$GITHUB_WORKSPACE"/target/docs/superpowers/plans/*.md 2>/dev/null | head -1)
      [ -n "$SPEC" ] && cp "$SPEC" "$OUT/spec.md" || true
      [ -n "$PLAN" ] && cp "$PLAN" "$OUT/plan.md" || true
      ls -la "$OUT"
  - name: Upload the spec + plan artifact
    if: always()
    uses: actions/upload-artifact@v4
    with:
      name: evidence
      path: /tmp/gh-aw/evidence
      if-no-files-found: warn
timeout-minutes: 30
---

{{#runtime-import .github/workflows/shared/skill-preamble.md}}

# Design Agent — Phase 0 only (spec + Accountability Ledger + plan). NO CODE, NO PR.

Working directory: `target/` (the analyzed codebase, checked out at the default branch).

## 1. Read the request
Read `/tmp/gh-aw/agent/issue.json` (issue title and description). Read
`/tmp/gh-aw/task-context.json` (`pr` = issue number, `iteration`, `feedback`).
On iteration > 1, fold the `feedback` (failed ledger/spec/plan checks) into this pass.

## 2. Phase 0 — write the spec
Write a spec to `target/docs/superpowers/specs/<YYYY-MM-DD>-<topic>-design.md` with
EXACTLY these sections (the `spec-present` check requires all five headings):
`## Summary`, `## Scope`, `## Behavior / acceptance criteria`,
`## Accountability Ledger`, `## READ THESE FIRST`.

Fill gaps yourself (this is autonomous). For every gap you fill, add a ledger entry.
The **Accountability Ledger** records each gap: category (DECISION | ASSUMPTION |
UNKNOWN | DEFERRED | DEVIATION), what / why / what-I-did, confidence (high|medium|low),
**blast radius** (level low|medium|high + WHY), **reversibility** (level
reversible|costly|irreversible + WHY), and a revisit-if condition. An ASSUMPTION
that asserts a fact about the code MUST be verified against the codebase and marked
verified. **READ THESE FIRST** lists the ledger ids risk-sorted (low-confidence ×
high/irreversible first).

## 3. Produce the plan
Use the `$writing-plans` skill on the spec to write a plan to
`target/docs/superpowers/plans/<YYYY-MM-DD>-<topic>.md`.

## 4. Give your evidence — then STOP (do not implement)
Call `noop`, then give your final answer: it IS the evidence, ONE JSON object matching
the evidence schema (the factory constrains it to that schema and hands it to the engine):
`{"spec_path","plan_path","summary","run_id","ledger":[…],"read_these_first":[…]}`
- `spec_path`/`plan_path`: the repo-relative paths under `target/` you just wrote
  (e.g. `docs/superpowers/specs/…-design.md`).
- `summary`: one line on the design, or `null`.
- `run_id`: the value of the `GITHUB_RUN_ID` environment variable.
- `ledger`: the SAME ledger as structured data — one object per gap, fields exactly
  as in §2 (`id` like "L1", `category`, `what`, `why`, `what_i_did`, `confidence`,
  `blast_radius:{level,why}`, `reversibility:{level,why}`, `revisit_if`, and
  `verified`: `true` on any ASSUMPTION asserting a code fact, otherwise `null`).
  Every ledger `id` MUST also appear in the spec's Ledger section (a check
  cross-references ids); the spec prose may paraphrase each item's `what` — it need
  not be verbatim.
- `read_these_first`: ledger ids, risk-descending.
Do NOT write code, do NOT open a PR, do NOT comment on GitHub.
