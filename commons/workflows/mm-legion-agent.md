---
name: "MM Legion Agent (protocol leg: recover/legion)"
run-name: "MM Legion Agent · cid:[${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}]"
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
# Custom Anthropic-compatible endpoint (public, Funnel-exposed). engine.env (not
# top-level env) is forwarded to the CLI subprocess by gh-aw.
#
# INFRA PREREQUISITE: this leg runs a real `/legion:map` against the PR head. The
# runner must have the `claude` CLI on PATH and the legion skill installed
# (https://github.com/9thLevelSoftware/legion), plus the ANTHROPIC_* secrets. The
# install step below is best-effort and environment-specific — adjust to your
# runner image. See docs/STATUS.md.
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
  - name: Install legion (native /legion:* commands)
    run: |
      # legion is an npm package that installs its Claude Code slash commands into
      # ~/.claude (Node + the claude CLI are already set up by the compiled lock).
      npx -y @9thlevelsoftware/legion@8.0.5 --claude || \
        echo "[mm-legion] legion install failed — /legion:map will be unavailable" >&2
  - name: Run legion:map and stage output
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
    run: |
      set -uo pipefail
      OUT=/tmp/gh-aw/out
      mkdir -p "$OUT"
      cd "$GITHUB_WORKSPACE/target"
      # The real method: /legion:map writes .planning/ into the repo root.
      claude -p "/legion:map" --permission-mode bypassPermissions || \
        echo "[mm-legion] legion:map exited non-zero (continuing to package whatever exists)" >&2
      if [ -d .planning ]; then
        cp -a .planning/. "$OUT"/
      fi
      # Build the evidence manifest (run_id + files) the engine's check + combine
      # hook consume. Form-only — the check verifies presence, not substance.
      python3 - "$OUT" > /tmp/gh-aw/evidence.json <<'PY'
      import json, os, sys
      root = sys.argv[1]
      files = []
      for dp, _, fns in os.walk(root):
          for fn in fns:
              ap = os.path.join(dp, fn)
              files.append({"path": os.path.relpath(ap, root),
                            "bytes": os.path.getsize(ap)})
      json.dump({"method": "legion:map",
                 "run_id": os.environ.get("GITHUB_RUN_ID", ""),
                 "files": files}, sys.stdout)
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
  - name: Upload mm-tree-legion artifact
    if: always()
    uses: actions/upload-artifact@v4
    with:
      name: mm-tree-legion
      path: /tmp/gh-aw/out
      if-no-files-found: warn
timeout-minutes: 45
---

# MM Legion Agent — legion:map mental model

The heavy lifting (running `/legion:map` against the PR head and staging
`.planning/` into `/tmp/gh-aw/out`) happens in the workflow setup steps, which
also write `/tmp/gh-aw/evidence.json` (a `run_id` + file manifest).

## Task context

Read `/tmp/gh-aw/task-context.json` (`pr`, `iteration`, `feedback`).

## Your job (verify-and-repair only)

1. Confirm `/tmp/gh-aw/evidence.json` exists and is valid JSON with a non-empty
   `run_id` and a `files` array.
2. Confirm the staged tree at `/tmp/gh-aw/out` contains the core legion-map
   artifacts: `CODEBASE.md`, `codebase/index.jsonl`, `codebase/symbols.json`,
   and `config/directory-mappings.yaml`. These are what the `legion-artifacts`
   check looks for in the manifest.
3. If the manifest is missing those entries but the files exist on disk,
   regenerate `/tmp/gh-aw/evidence.json` so its `files[].path` list reflects the
   actual contents of `/tmp/gh-aw/out` (paths relative to that dir). Keep
   `run_id` set to the `GITHUB_RUN_ID`.
4. Do NOT post comments or touch GitHub. The engine publishes after checks pass,
   and collects `/tmp/gh-aw/out` itself (this leg declares `outputs:`), handing
   it to the `combine` merge hook as `inputs/legion/`. The `mm-tree-legion`
   artifact is still uploaded, but only for a human to inspect — it is no longer
   how the tree travels.
