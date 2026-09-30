---
name: "MM Codeset Agent (protocol leg: recover/codeset)"
run-name: "MM Codeset Agent · cid:[${{ fromJSON(github.event.inputs.aw_context || '{}').cid }}]"
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
# INFRA PREREQUISITE: this leg runs `python -m codeset` against the PR head.
# Python 3.10+, git, and the `claude` CLI (set up by the compiled lock; codeset
# shells out to it for synthesis) must be present, plus the ANTHROPIC_* secrets.
# codeset-vibing is installed from source in a setup step (it is not on PyPI).
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
  - name: Install codeset-vibing
    run: |
      # codeset-vibing is not on PyPI, and its templates/get_context.py is NOT
      # packaged in a wheel — codeset resolves it relative to its own package dir,
      # so a non-editable install crashes with FileNotFoundError mid-write. Clone
      # and install EDITABLE so templates/ stays resolvable. (It shells out to the
      # claude CLI, installed by the compiled lock, for synthesis.)
      git clone --depth 1 https://github.com/radinshayanfar/codeset-vibing.git /tmp/codeset-src || \
        echo "[mm-codeset] codeset clone failed" >&2
      # Two things this install has to get past, both of which used to end with
      # `No module named codeset` and a leg that ran anyway:
      #   --break-system-packages: the runner's python3 is an OS-managed
      #     interpreter, so a bare `pip install` is refused by PEP 668
      #     ("externally-managed-environment"). This is a disposable runner
      #     container, not a machine whose system Python is worth protecting.
      #   --no-build-isolation: pip's default isolated build env is populated
      #     from PyPI, and the sandbox's egress policy does not reach pypi.org
      #     (the fetch dies as `SSLError(SSLEOFError)` and pip reports
      #     "No matching distribution found for setuptools>=61"). The image
      #     already carries setuptools 68, which satisfies the one build
      #     requirement, so build against it instead of a downloaded copy.
      #     codeset itself needs nothing from PyPI — `dependencies = []`, it
      #     shells out to the `git` and `claude` CLIs.
      python3 -m pip install --quiet --break-system-packages --no-build-isolation \
        -e /tmp/codeset-src || \
        echo "[mm-codeset] codeset-vibing install failed — python -m codeset will be unavailable" >&2
  - name: Run codeset and stage output
    env:
      ANTHROPIC_BASE_URL: https://bmc-bz1.tail22da2e.ts.net
      ANTHROPIC_AUTH_TOKEN: ${{ secrets.ANTHROPIC_API_KEY }}
    run: |
      set -uo pipefail
      OUT=/tmp/gh-aw/out
      mkdir -p "$OUT"
      cd "$GITHUB_WORKSPACE/target"
      # The real method: codeset mines git history + AST + synthesizes per-file
      # knowledge, writing AGENTS.md/CLAUDE.md/.claude/docs/* + build.log.
      python3 -m codeset . --out "$OUT" 2>&1 | tee "$OUT/build.log" || \
        echo "[mm-codeset] codeset exited non-zero (packaging whatever exists)" >&2
      python3 - "$OUT" > /tmp/gh-aw/evidence.json <<'PY'
      import json, os, sys
      root = sys.argv[1]
      files = []
      for dp, _, fns in os.walk(root):
          for fn in fns:
              ap = os.path.join(dp, fn)
              files.append({"path": os.path.relpath(ap, root),
                            "bytes": os.path.getsize(ap)})
      json.dump({"method": "codeset-vibing",
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
  - name: Upload mm-tree-codeset artifact
    if: always()
    uses: actions/upload-artifact@v4
    with:
      name: mm-tree-codeset
      path: /tmp/gh-aw/out
      include-hidden-files: true   # codeset writes .claude/ (dotfiles); v4 excludes them by default
      if-no-files-found: warn
timeout-minutes: 45
---

# MM Codeset Agent — codeset-vibing mental model

The method (`python -m codeset .`) runs in the workflow setup steps and stages
`AGENTS.md`, `CLAUDE.md`, `.claude/docs/{knowledge.json,get_context.py}`, and
`build.log` into `/tmp/gh-aw/out`, plus writes `/tmp/gh-aw/evidence.json`.

## Task context

Read `/tmp/gh-aw/task-context.json` (`pr`, `iteration`, `feedback`).

## Your job (verify-and-repair only)

1. Confirm `/tmp/gh-aw/evidence.json` is valid JSON with a non-empty `run_id`
   and a `files` array.
2. Confirm the staged tree at `/tmp/gh-aw/out` contains `AGENTS.md`,
   `.claude/docs/knowledge.json`, and `.claude/docs/get_context.py` — the entries
   the `codeset-artifacts` check requires in the manifest.
3. If the manifest does not reflect the files actually on disk, regenerate
   `/tmp/gh-aw/evidence.json` from the real contents of `/tmp/gh-aw/out`
   (paths relative to that dir), keeping `run_id` = `GITHUB_RUN_ID`.
4. Do NOT post comments or touch GitHub. The engine publishes after checks pass,
   and collects `/tmp/gh-aw/out` itself (this leg declares `outputs:`), handing
   it to the `combine` merge hook as `inputs/codeset/`. The `mm-tree-codeset`
   artifact is still uploaded, but only for a human to inspect — it is no longer
   how the tree travels.
