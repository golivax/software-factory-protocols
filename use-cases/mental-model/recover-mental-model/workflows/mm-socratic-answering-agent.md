---
name: "MM Socratic Answering Agent (protocol sub-state: recover/socratic/answering)"
run-name: "MM Socratic Answering Agent · cid:[${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}]"
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
# INFRA PREREQUISITE: runs the AUTOMATED answering step of socratic-code-theory-
# recovery — it researches (code + web) and fills the OPEN leaves of phase 1, with
# NO human input. Restores phase 1's tree from the mm-tree-socratic-phase1 artifact
# (needs actions:read), runs `claude` to answer, and uploads the answered tree.
# See docs/STATUS.md.
permissions:
  contents: read
  pull-requests: read
  actions: read
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
      set -uo pipefail
      tmp=$(mktemp -d)
      git clone --depth 1 https://github.com/LLM-Coding/Semantic-Anchors "$tmp" || \
        echo "[mm-socratic-ans] skill clone failed" >&2
      mkdir -p "$HOME/.claude/skills"
      src="$tmp/skill/socratic-code-theory-recovery"
      if [ -d "$src" ]; then
        rm -rf "$HOME/.claude/skills/socratic-code-theory-recovery"
        cp -r "$src" "$HOME/.claude/skills/socratic-code-theory-recovery"
      else
        echo "[mm-socratic-ans] skill dir not found in repo — answering will be unavailable" >&2
      fi
  - name: Restore phase-1 tree and answer the OPEN leaves
    env:
      ANTHROPIC_BASE_URL: https://bmc-bz1.tail22da2e.ts.net
      ANTHROPIC_AUTH_TOKEN: ${{ secrets.ANTHROPIC_API_KEY }}
      # `claude -p --permission-mode bypassPermissions` refuses to run as root
      # unless it is told it is in a sandbox, and every step here runs as root
      # inside the act job container. Without this the CLI exits immediately,
      # the leg stages an empty tree, and the form-only artifacts check passes
      # anyway -- a green leg that did no work. The refusal guards a developer
      # machine; this is a disposable container inside a disposable microVM,
      # which is exactly the case the escape hatch exists for.
      IS_SANDBOX: "1"
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      REPO: ${{ github.repository }}
    run: |
      set -uo pipefail
      OUT=/tmp/gh-aw/out
      mkdir -p "$OUT"
      cd "$GITHUB_WORKSPACE/target"
      # Restore phase 1's QUESTION_TREE/OPEN_QUESTIONS. phase1 declares
      # `outputs: true` and this leg declares `inputs: [{from: phase1, as: tree}]`,
      # so the ENGINE already staged that tree at $GITHUB_WORKSPACE/inputs/tree/
      # (issue #68) -- no artifact download. The old `gh run download` path cannot
      # work off GitHub anyway: act's artifact server is per-run and in-VM, and
      # gh2gl fronts a forge that has no Actions artifacts at all.
      if [ -d "$GITHUB_WORKSPACE/inputs/tree" ]; then
        cp -a "$GITHUB_WORKSPACE/inputs/tree/." . 2>/dev/null || true
      else
        echo "[mm-socratic-ans] no staged phase-1 tree at inputs/tree" >&2
      fi
      # The AUTOMATED answering pass: research + fill the OPEN_QUESTIONS in place.
      claude -p "we used socratic code-theory recovery and it created open questions in OPEN_QUESTIONS*.adoc. Do the best you can, reading code and the web as needed, to answer the questions in place. If you can't answer one, defer it. Do not ask anything." \
        --permission-mode bypassPermissions || \
        echo "[mm-socratic-ans] answering exited non-zero (packaging whatever exists)" >&2
      # Stage the answered tree (QUESTION_TREE + the now-answered OPEN_QUESTIONS).
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
      json.dump({"method": "socratic:answering",
                 "run_id": os.environ.get("GITHUB_RUN_ID", ""),
                 "files": files}, sys.stdout)
      PY
      cat /tmp/gh-aw/evidence.json
post-steps:
  - name: Publish evidence where the engine reads it
    # The engine reads a dispatched node's evidence from
    # $GITHUB_WORKSPACE/evidence-out.json (conductor._read_evidence), absent =>
    # {}. `act` runs --bind from the node workspace, so GITHUB_WORKSPACE IS that
    # workspace -- writing the file here is what hands the verdict back.
    #
    # Uploading `evidence` as an Actions artifact does NOT: act's artifact server
    # is per-run and in-VM, and the forge behind gh2gl has no Actions artifacts
    # at all. Without this every leg landed evidence {} and its form-only check
    # failed -- and a `questions_from` gate read no questions, because
    # advance.py sources them from the producing node's evidence too.
    #
    # A post-step, for the same reason the outputs publish is one: the agent's
    # verify-and-repair pass rewrites /tmp/gh-aw/evidence.json, and only what
    # survives THAT is the node's real verdict.
    if: always()
    run: |
      set -uo pipefail
      if [ -s /tmp/gh-aw/evidence.json ]; then
        cp /tmp/gh-aw/evidence.json "$GITHUB_WORKSPACE/evidence-out.json"
        echo "[evidence] published $(wc -c < "$GITHUB_WORKSPACE/evidence-out.json") bytes"
      else
        echo "[evidence] /tmp/gh-aw/evidence.json missing or empty" >&2
      fi
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
  - name: Upload mm-tree-socratic-answering artifact
    if: always()
    uses: actions/upload-artifact@v4
    with:
      name: mm-tree-socratic-answering
      path: /tmp/gh-aw/out
      if-no-files-found: warn
timeout-minutes: 45
---

# MM Socratic Answering Agent — auto-answer the OPEN leaves

The automated answering pass already ran in the setup steps: it restored phase 1's
Question Tree, answered the OPEN leaves in `OPEN_QUESTIONS-*.adoc` (code + web
research, no human input), staged the answered tree into `/tmp/gh-aw/out`, and
seeded `/tmp/gh-aw/evidence.json`.

## Task context

Read `/tmp/gh-aw/task-context.json`:
- `pr`, `iteration`, `feedback`
- `inputs.tree`: phase-1 evidence `{run_id, files}` — its `run_id` named the
  artifact that was restored.

## Your job (verify-and-repair only)

1. Confirm `/tmp/gh-aw/evidence.json` is valid JSON with a non-empty `run_id`
   and a `files` array.
2. Read the staged `OPEN_QUESTIONS-*.adoc` in `/tmp/gh-aw/out`. Ensure every OPEN
   leaf now has an answer or an explicit `(deferred)` marker — never leave a
   `_(write here)_` blank. If any remain, answer them from the code/diff (cite
   `file:line`) or mark them deferred, and re-save the file.
3. If the manifest does not reflect the files on disk, regenerate
   `/tmp/gh-aw/evidence.json` from the real contents of `/tmp/gh-aw/out`,
   keeping `run_id` = `GITHUB_RUN_ID`.
4. Do NOT post comments or touch GitHub. Phase 2 downloads your
   `mm-tree-socratic-answering` artifact by `run_id` and synthesizes the docs.
