---
private: true
description: "handover — a colleague drafts release-notes material and stops mid-task, leaving the draft in the working tree uncommitted"
on:
  workflow_dispatch:
permissions:
  contents: read
engine:
  id: codex
  model: gpt-5.5
  env:
    # The deployment's OpenAI-compatible gateway (the agent lane's only external
    # creds beyond the forge proxy). Must match an entry in deploy/.env
    # LLM_ENDPOINTS or the sandbox's fail-closed egress denies it.
    OPENAI_BASE_URL: https://YOUR-LLM-GATEWAY/v1/
safe-outputs:
  jobs:
    evidence:
      description: "Hand the unfinished work to the next step."
      runs-on: ubuntu-latest
      permissions:
        contents: read
      inputs:
        files_json:
          description: "CHECKABLE — a JSON array of {path, content}, one entry per file left behind."
          type: string
          required: true
        summary:
          description: "JUDGMENT — where the work got to and what is left to do."
          type: string
          required: true
      output: "Handover recorded."
      steps:
        - name: Materialize evidence JSON
          run: |
            set -euo pipefail
            jq -c '[.items[] | select(.type=="evidence")][0]
                   | {files: (.files_json | fromjson), summary}' \
              "$GH_AW_AGENT_OUTPUT" > "$GITHUB_WORKSPACE/evidence-out.json"
            cat "$GITHUB_WORKSPACE/evidence-out.json"
timeout-minutes: 15
---

# Release-notes draft

You are drafting material for the next release and you will not finish today. Do
the part you can, leave your working draft in the tree for whoever picks it up,
and hand over cleanly.

## Steps

1. Write your plan first, exactly as the framework instructs. Declare one
   `run_command` step per shell command you expect to run, each with a **literal**
   `argv`, then `compute`, then `publish` to the `evidence` channel.

2. Look at what has changed recently, so the draft has real material in it:

   ```
   git log --oneline -20
   ```

3. Create a `.notes/` directory and write **exactly two** files into it:

   - `.notes/outline.md` — a short outline for the release notes, with a heading
     and three or four bullets drawn from what you saw in step 2.
   - `.notes/open-questions.md` — three questions you would need answered before
     the notes could be finished.

   Keep both short, under about fifteen lines each. Do **not** commit them and do
   **not** add them to git. They are work in progress, and leaving them uncommitted
   in the tree is the point of the handover.

4. Confirm they are there and untracked:

   ```
   git status --porcelain --untracked-files=all
   ```

5. Report by calling the **`evidence`** safe-output tool exactly once, with:
   - `files_json`: a JSON array string with one object per file, each
     `{"path": "...", "content": "..."}`, carrying the file's **exact** contents.
     The next steps rebuild these files from this array and compare them byte for
     byte, so the content you report must match the file you wrote exactly.
   - `summary`: one or two sentences on where you got to and what is left to do
