---
name: "MM Socratic Phase-1 Agent (protocol sub-state: recover/socratic/phase1)"
run-name: "MM Socratic Phase-1 Agent · cid:[${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}]"
on:
  workflow_dispatch:
strict: false
engine:
  id: claude
  model: claude-sonnet-4-6
  env:
    ANTHROPIC_BASE_URL: https://bmc-bz1.tail22da2e.ts.net
    ANTHROPIC_AUTH_TOKEN: ${{ secrets.ANTHROPIC_API_KEY }}
    # Every model call goes through AWF's api-proxy to the gateway above, and the
    # compiler (gh-aw >= v0.89) drops api.anthropic.com from the firewall allowlist
    # once a custom target is set. Claude Code still makes non-essential calls
    # (feature flags / update checks) straight to Anthropic; those get denied and
    # surface as a "Firewall blocked 1 domain" warning. Switch them off.
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1"
# INFRA PREREQUISITE: runs phase 1 of the socratic-code-theory-recovery skill
# (https://github.com/LLM-Coding/Semantic-Anchors) against the PR head. The runner
# must have the `claude` CLI with that skill installed + the ANTHROPIC_* secrets.
# See docs/STATUS.md.
permissions:
  contents: read
  pull-requests: read
tools:
  cli-proxy: true
  edit: true
  bash: [":*"]
pre-agent-steps:
  - name: Materialize task context
    env:
      CTX: ${{ github.event.inputs.aw_context }}
    run: |
      mkdir -p /tmp/gh-aw
      if [ -z "$CTX" ]; then CTX='{}'; fi
      printf '%s' "$CTX" > /tmp/gh-aw/task-context.json
      cat /tmp/gh-aw/task-context.json
  - name: Checkout target ref
    # The engine pins the commit under review and passes it as `aw_context.sha`;
    # `.ref` is only ever set for a branch-shaped run, so checking it out means
    # checking out nothing and letting actions/checkout fall back to the ambient
    # `github.sha` — which, off a real forge, is a synthetic the remote has never
    # heard of ("upload-pack: not our ref"). Take the sha, fall back to the ref.
    uses: actions/checkout@v5
    with:
      ref: ${{ fromJSON(github.event.inputs.aw_context || '{}').sha || fromJSON(github.event.inputs.aw_context || '{}').ref }}
      path: target
      persist-credentials: false
      fetch-depth: 0
  - name: Install socratic skill
    run: |
      # Install the socratic-code-theory-recovery skill into ~/.claude/skills from
      # the Semantic-Anchors repo (the claude CLI is set up by the compiled lock).
      set -uo pipefail
      tmp=$(mktemp -d)
      git clone --depth 1 https://github.com/LLM-Coding/Semantic-Anchors "$tmp" || \
        echo "[mm-socratic-1] skill clone failed" >&2
      mkdir -p "$HOME/.claude/skills"
      # The repo's skill/ holds one subdir per skill; copy the specific one so its
      # SKILL.md lands at ~/.claude/skills/socratic-code-theory-recovery/SKILL.md.
      src="$tmp/skill/socratic-code-theory-recovery"
      if [ -d "$src" ]; then
        rm -rf "$HOME/.claude/skills/socratic-code-theory-recovery"
        cp -r "$src" "$HOME/.claude/skills/socratic-code-theory-recovery"
        ls "$HOME/.claude/skills/socratic-code-theory-recovery"
      else
        echo "[mm-socratic-1] skill dir not found in repo — phase 1 will be unavailable" >&2
      fi
  - name: Run socratic phase 1 and stage output
    env:
      ANTHROPIC_BASE_URL: https://bmc-bz1.tail22da2e.ts.net
      ANTHROPIC_AUTH_TOKEN: ${{ secrets.ANTHROPIC_API_KEY }}
    run: |
      set -uo pipefail
      OUT=/tmp/gh-aw/out
      mkdir -p "$OUT"
      cd "$GITHUB_WORKSPACE/target"
      # Phase 1: build the Question Tree; surface OPEN leaves. The skill writes
      # QUESTION_TREE-*.adoc and OPEN_QUESTIONS-*.adoc into the repo root.
      claude -p "/socratic-code-theory-recovery work here and scope the entire repo. don't ask anything and give the output of phase 1" \
        --permission-mode bypassPermissions || \
        echo "[mm-socratic-1] phase 1 exited non-zero (packaging whatever exists)" >&2
      cp -a QUESTION_TREE-*.adoc OPEN_QUESTIONS-*.adoc "$OUT"/ 2>/dev/null || true
      python3 - "$OUT" > /tmp/gh-aw/evidence.json <<'PY'
      import json, os, sys
      root = sys.argv[1]
      files = []
      for dp, _, fns in os.walk(root):
          for fn in fns:
              ap = os.path.join(dp, fn)
              files.append({"path": os.path.relpath(ap, root),
                            "bytes": os.path.getsize(ap)})
      json.dump({"method": "socratic:phase1",
                 "run_id": os.environ.get("GITHUB_RUN_ID", ""),
                 "questions": [], "files": files}, sys.stdout)
      PY
      cat /tmp/gh-aw/evidence.json
post-steps:
  - name: Publish the tree to the engine's outputs dir
    # Declared `outputs:` (issue #68). The engine created $SF_OUTPUTS_DIR before
    # the run and collects it off the workspace after the reap, staging it for the
    # `combine` node as inputs/<leg>/ -- which is how the tree reaches the merge
    # hook now that it no longer downloads artifacts. A post-step, not part of the
    # method step, because the agent's verify-and-repair pass edits /tmp/gh-aw/out
    # and only what survives THAT is the leg's real product. A plain `run:` so it
    # reads the process env directly (act forwards SF_OUTPUTS_DIR as a container
    # --env; `${{ env.* }}` would not resolve it). Unset => a standalone harness
    # run with no engine to collect for: skip rather than fail.
    if: always()
    run: |
      set -uo pipefail
      if [ -z "${SF_OUTPUTS_DIR:-}" ]; then
        echo "[outputs] SF_OUTPUTS_DIR unset — nothing to publish" >&2
        exit 0
      fi
      mkdir -p "$SF_OUTPUTS_DIR"
      cp -a /tmp/gh-aw/out/. "$SF_OUTPUTS_DIR"/ 2>/dev/null || \
        echo "[outputs] nothing staged at /tmp/gh-aw/out" >&2
      find "$SF_OUTPUTS_DIR" -type f | head -50
  - name: Upload evidence artifact
    if: always()
    uses: actions/upload-artifact@v4
    with:
      name: evidence
      path: /tmp/gh-aw/evidence.json
      if-no-files-found: warn
  - name: Upload mm-tree-socratic-phase1 artifact
    if: always()
    uses: actions/upload-artifact@v4
    with:
      name: mm-tree-socratic-phase1
      path: /tmp/gh-aw/out
      if-no-files-found: warn
timeout-minutes: 30
---

# MM Socratic Phase-1 Agent — Question Tree & OPEN leaves

Phase 1 of the skill already ran in the setup steps and staged
`QUESTION_TREE-*.adoc` + `OPEN_QUESTIONS-*.adoc` into `/tmp/gh-aw/out`, and seeded
`/tmp/gh-aw/evidence.json` with a `run_id`, a `files` manifest, and an empty
`questions` array.

## Task context

Read `/tmp/gh-aw/task-context.json` (`pr`, `iteration`, `feedback`).

## Your job

1. Confirm `/tmp/gh-aw/evidence.json` is valid JSON with a non-empty `run_id`
   and a `files` array; confirm `/tmp/gh-aw/out` contains `QUESTION_TREE-*.adoc`
   and `OPEN_QUESTIONS-*.adoc` (what the `socratic-phase1-present` check requires).
   If the manifest doesn't reflect the files on disk, regenerate it (keep
   `run_id` = `GITHUB_RUN_ID`).
2. **Surface the OPEN leaves as questions.** Read the staged `OPEN_QUESTIONS-*.adoc`;
   for EACH `[OPEN]` leaf produce one `{ "id": <Q-ID>, "text": <question, with the
   role to ask in parentheses> }` (use the leaf's Q-ID, e.g. `Q1.4.1`; synthesize
   `q1`,`q2`,… in document order if a leaf has none). Write them into the
   `questions` array of `/tmp/gh-aw/evidence.json`, preserving `run_id` + `files`.
   There must be ≥1 (the `questions-present` check rejects an empty list).
3. Do NOT post comments or touch GitHub.

The `questions` array is consumed two ways depending on the protocol: the
**non-interactive** `answering` agent auto-answers them; the **interactive**
`answering` gate posts them on an issue for a human to answer. Either way phase 1
is identical — just surface the OPEN leaves accurately.
