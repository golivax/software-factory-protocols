---
name: "MM Ubiquitous-Language Agent (protocol leg: recover/ubiquitous-language)"
run-name: "MM Ubiquitous-Language Agent · cid:[${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}]"
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
# INFRA PREREQUISITE: this leg runs the domain-modeling skill against the PR head.
# The runner must have the `claude` CLI (set up by the compiled lock) + the
# ANTHROPIC_* secrets. The domain-modeling skill is installed from
# mattpocock/skills in a setup step. See docs/STATUS.md.
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
  - name: Install domain-modeling skill
    run: |
      # Install the domain-modeling skill into ~/.claude/skills from mattpocock/skills
      # (the claude CLI is set up by the compiled lock). The repo nests skills under
      # skills/<category>/<name>; copy the specific one so SKILL.md lands at
      # ~/.claude/skills/domain-modeling/SKILL.md.
      set -uo pipefail
      tmp=$(mktemp -d)
      git clone --depth 1 https://github.com/mattpocock/skills "$tmp" || \
        echo "[mm-ubiq] skill clone failed" >&2
      mkdir -p "$HOME/.claude/skills"
      src="$tmp/skills/engineering/domain-modeling"
      if [ -d "$src" ]; then
        rm -rf "$HOME/.claude/skills/domain-modeling"
        cp -r "$src" "$HOME/.claude/skills/domain-modeling"
      else
        echo "[mm-ubiq] skill dir not found in repo — /domain-modeling will be unavailable" >&2
      fi
  - name: Run domain-modeling and stage output
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
      # The real method: derive the domain glossary (CONTEXT.md) from code only.
      claude -p "/domain-modeling — Derive the domain glossary for this repo from the code only. Don't ask me any clarifying questions; when a term is ambiguous, pick the most defensible canonical name based on the code and note alternatives under _Avoid_. Generate CONTEXT.md only — do not create or offer any ADRs, and don't write a CONTEXT-MAP.md (treat this as a single context). If you hit a genuine ambiguity you can't resolve from code, make a reasonable choice and move on rather than stopping." \
        --permission-mode bypassPermissions || \
        echo "[mm-ubiq] domain-modeling exited non-zero (packaging whatever exists)" >&2
      cp -a CONTEXT.md "$OUT"/ 2>/dev/null || true
      python3 - "$OUT" > /tmp/gh-aw/evidence.json <<'PY'
      import json, os, sys
      root = sys.argv[1]
      files = []
      for dp, _, fns in os.walk(root):
          for fn in fns:
              ap = os.path.join(dp, fn)
              files.append({"path": os.path.relpath(ap, root),
                            "bytes": os.path.getsize(ap)})
      json.dump({"method": "domain-modeling",
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
  - name: Upload mm-tree-ubiquitous-language artifact
    if: always()
    uses: actions/upload-artifact@v4
    with:
      name: mm-tree-ubiquitous-language
      path: /tmp/gh-aw/out
      if-no-files-found: warn
timeout-minutes: 30
---

# MM Ubiquitous-Language Agent — domain glossary (CONTEXT.md)

The method (`/domain-modeling`) runs in the workflow setup steps and stages
`CONTEXT.md` (the code-derived domain glossary) into `/tmp/gh-aw/out`, plus writes
`/tmp/gh-aw/evidence.json` (a `run_id` + file manifest).

## Task context

Read `/tmp/gh-aw/task-context.json` (`pr`, `iteration`, `feedback`).

## Your job (verify-and-repair only)

1. Confirm `/tmp/gh-aw/evidence.json` is valid JSON with a non-empty `run_id`
   and a `files` array.
2. Confirm the staged tree at `/tmp/gh-aw/out` contains `CONTEXT.md` — what the
   `ubiquitous-language-present` check requires. If it is missing but a
   `CONTEXT.md` exists in the checked-out repo, copy it into `/tmp/gh-aw/out`.
3. Confirm `CONTEXT.md` is a glossary only (terms + definitions + `_Avoid_`
   alternatives) with no ADRs and no `CONTEXT-MAP.md`. If `/domain-modeling`
   produced extra files, remove them from `/tmp/gh-aw/out` so only `CONTEXT.md`
   ships.
4. If the manifest does not reflect the files on disk, regenerate
   `/tmp/gh-aw/evidence.json` from the real contents of `/tmp/gh-aw/out`,
   keeping `run_id` = `GITHUB_RUN_ID`.
5. Do NOT post comments or touch GitHub. The engine publishes after checks pass,
   and collects `/tmp/gh-aw/out` itself (this leg declares `outputs:`), handing it
   to the `combine` merge hook as `inputs/ubiquitous-language/`, which pushes it
   under `ubiquitous-language/`. The `mm-tree-ubiquitous-language` artifact is
   still uploaded, but only for a human to inspect — not as the transport.
