"""Write code-review-ocr's agent workflow sources (gh-aw markdown): five units
that share their frontmatter and their step. Edit this, then

    python3 tests/generate/gen_agents.py workflows

tests/test_generated.py fails when the units and this disagree."""
import os
import sys

OUT = sys.argv[1]


def frontmatter(name, title, state, task, timeout):
    depth = ""
    return f"""---
name: "{title} (protocol state: {state})"
concurrency:
  group: "ocr-{name}-${{{{ fromJSON(github.event.inputs.aw_context || '{{}}').cid }}}}"
  cancel-in-progress: false
run-name: "{title} · cid:[${{{{ fromJSON(github.event.inputs.aw_context || '{{}}').cid }}}}]"
on:
  workflow_dispatch:
imports:
  - shared/agent.md   # the agent slot: see README.md
permissions:
  contents: read
  pull-requests: read
tools:
  # codex cannot enforce a per-command allow-list; the agent is held by the
  # sandbox and its network firewall, and by the prompt to the commands it names.
  bash: ["*"]
safe-outputs:
  # The evidence is the final answer, not a safe output: no "No Safe Outputs" issue.
  noop:
    report-as-issue: false
  threat-detection: false
steps:
  - uses: actions/checkout@v5
    with: {{ persist-credentials: false{depth} }}
  - name: Render OCR's {task} conversation
    # The run's MR snapshot and this node's staged inputs, filled into upstream
    # OCR's prompts by deterministic code (agent_prompt.py), before the agent starts.
    run: |
      set -euo pipefail
      mkdir -p /tmp/gh-aw/agent
      cp "$SF_SUBJECT_DIR/diff.patch" "$SF_SUBJECT_DIR/files.txt" "$SF_SUBJECT_DIR/pr.json" /tmp/gh-aw/agent/
      python3 .github/workflows/agent_prompt.py {task} /tmp/gh-aw/agent
timeout-minutes: {timeout}
---
"""


READ = """\
## Reading the conversation

It is in parts, `/tmp/gh-aw/agent/ocr-prompt.part-001.md`, `…-002.md` and so on;
`/tmp/gh-aw/agent/ocr-prompt.parts` holds how many. Read every part, in order,
one `cat` each, before you do anything else: a longer output is shown to you
truncated, so never read the whole conversation (`ocr-prompt.md`) at once. What
you have not read, you do not know."""

SINGLE_SHOT = """\
Upstream sends this conversation as one request with no tools: answer it in one
go. The only commands you run are the reads above; do not inspect the
repository or run anything else. Any tools the conversation mentions are for
reference only."""

AGENTS = {
    "grouping-agent": ("grouping", "OCR Grouping", "grouping-try.grouping", 10, f"""
# OpenCodeReview — group the changed files

You are OpenCodeReview's (OCR's) file-grouping step for this merge request.
OCR's grouping conversation is rendered word for word: a `system` message and a
`user` message. Read all of it, then answer it exactly as its messages ask.

{READ}

{SINGLE_SHOT}

## Your final answer

Call `noop`, then give your final answer: it IS the evidence, one JSON object
matching the evidence schema. Its `groups` is the JSON array the conversation
asks for, unchanged:

```json
{{ "groups": [ {{ "label": "short theme description", "files": [0, 1] }} ] }}
```
"""),
    "plan-agent": ("plan", "OCR Plan", "review.<group>.plan-try.plan", 15, f"""
# OpenCodeReview — plan one group's review

You are OpenCodeReview's (OCR's) review-planning step for one group of files of
this merge request. OCR's planning conversation is rendered word for word: a
`system` message (your role, the output format and the analysis rules) and a
`user` message (the changes, the checklist, the task). Read all of it, then
answer it exactly as its messages ask.

{READ}

{SINGLE_SHOT}

## Your final answer

Call `noop`, then give your final answer: it IS the evidence, one JSON object
matching the evidence schema. Its `plan` is the plain-text plan the system
message specifies (`Summary:` line, `Issues`, the numbered items), unchanged:

```json
{{ "plan": "Summary: …\\n\\nIssues\\n\\n1. [high] …" }}
```
"""),
    "review-agent": ("review", "OCR Review", "review.<group>.review-<n>", 40, f"""
# OpenCodeReview — review one group of files

You are OpenCodeReview's (OCR's) review agent for one review round of one group
of files of this merge request. OCR's conversation for this round is rendered
word for word: a `system` message (your role, your capabilities, the focus
rules, the reply limit) and a `user` message (the other changed files, the files
to review with their diffs, the review checklist, and the review plan or the
findings earlier rounds confirmed). Read all of it, then do the review its
messages ask for, as OCR's agent does.

{READ}

## Your tools

OCR's agent works through six tools, each defined in `/tmp/gh-aw/agent/ocr-tool-<name>.json`
(upstream's definitions, verbatim): `task_done`, `code_comment`, `code_search`,
`file_read`, `file_read_diff`, `file_find`. Read the six files. Here they map as
follows:

- **Context tools** — `code_search`, `file_read`, `file_read_diff`,
  `file_find`: run them from the repository root as

  ```bash
  python3 /tmp/gh-aw/agent/ocr_tools.py <tool> '<the tool's arguments as one JSON object>'
  ```

  for example
  `python3 /tmp/gh-aw/agent/ocr_tools.py file_read '{{"file_path": "src/a.go", "start_line": 10, "end_line": 60}}'`.
  Their arguments, as the definitions name them: `code_search` (`search_text`,
  `file_patterns`, `case_sensitive`, `use_perl_regexp`, `side`), `file_read`
  (`file_path`, `start_line`, `end_line`, `side`), `file_read_diff` (`path_array`),
  `file_find` (`query_name`, `case_sensitive`, `side`).
  They return what OCR's tools return, read at the commit under review. These
  four are your only way to gather context: do not run other commands, and
  never build, test or change anything.
- **`code_comment`** — do not run anything: every comment you would file with
  it goes into the `comments` list of your final answer, with the fields the
  tool definition gives (`path`, `content`, `existing_code`, `suggestion_code`
  or `null`, `category`, `severity`). Copy `existing_code` from the diff exactly
  as the definition requires: the comment is placed by matching it.
- **`task_done`** — when the review is complete, call `noop` and give your
  final answer, with `state` set as `task_done` would: `DONE`, or `FAILED` when
  the task cannot be completed with the tools available.

## Your final answer

It IS the evidence, one JSON object matching the evidence schema:

```json
{{ "state": "DONE",
  "comments": [
    {{ "path": "src/a.go", "content": "what is wrong and why", "existing_code": "the line(s) from the diff",
      "suggestion_code": null, "category": "bug", "severity": "high" }} ] }}
```

An empty `comments` list is a legitimate answer when the files carry no issue
worth reporting.
"""),
    "filter-agent": ("filter", "OCR Review Filter", "review.<group>.filter-<n>-try.filter-<n>", 15, f"""
# OpenCodeReview — filter one round's review comments

You are OpenCodeReview's (OCR's) review filter for one round of one group of
files of this merge request. OCR's filter conversation is rendered word for
word: a `system` message (your role) and a `user` message (the diffs, the review
comments, the method). Read all of it, then decide exactly as its messages ask.

{READ}

{SINGLE_SHOT}

## The two tools

The conversation tells you to call exactly one of these two tools (upstream's
definitions, verbatim). Here you do not call them: your final answer says
which one you call and with what.

- `report_incorrect_comments`: "Report review comments that this diff proves to
  be factually wrong: either the code they target is absent from the diff, or
  one diff line literally contradicts their central claim. For every id listed
  you must be able to name that line. Do not use this for comments you merely
  find unconvincing, unverifiable, or low-value, nor for comments about memory
  safety, concurrency, linkage consistency, unused parameters, or behavioral
  changes."
  - `analysis` (array of strings): "Work through every candidate comment BEFORE
    deciding. One entry per candidate: its id, whether its subject hits the
    protected-subject veto (Step 1) or the value veto (Step 2), the exact diff
    line that refutes it if any, and your final call. Only ids you conclude
    here as removable may appear in comment_ids."
  - `comment_ids` (array of strings): "IDs concluded removable in analysis,
    e.g. [\\"c-0\\", \\"c-2\\"]. Must not be empty."
- `approve_all_comments`: "Keep every review comment. Call this whenever no
  comment clears the removal bar — including when comments look doubtful,
  cannot be verified from the diff alone, or seem minor. This is the expected
  outcome for most files." It takes no arguments.

## Your final answer

Call `noop`, then give your final answer: it IS the evidence, one JSON object
matching the evidence schema. Write `analysis` before `comment_ids`, as the
tool's argument order makes you reason before you commit:

```json
{{ "tool": "report_incorrect_comments", "analysis": ["c-0: …", "c-1: …"], "comment_ids": ["c-1"] }}
```

or, for `approve_all_comments`, `{{ "tool": "approve_all_comments", "analysis": [], "comment_ids": [] }}`.
"""),
    "relocate-agent": ("relocate", "OCR Re-location", "review.<group>.relocate-<n>.<comment>", 10, f"""
# OpenCodeReview — re-locate one review comment

You are OpenCodeReview's (OCR's) code-location step for one review comment
whose quoted code could not be found in its file's diff. OCR's re-location
conversation is rendered word for word: a `system` message and a `user` message
(the diff, the snippet that failed to match, the comment). Read all of it, then
answer exactly as its messages ask.

{READ}

{SINGLE_SHOT}

## Your final answer

Call `noop`, then give your final answer: it IS the evidence, one JSON object
matching the evidence schema. Its `response` is your whole reply to the
conversation, unchanged: only the fenced code block it asks for.

```json
{{ "response": "```\\nthe line(s), verbatim from the diff\\n```" }}
```
"""),
}

for name, (task, title, state, timeout, body) in AGENTS.items():
    with open(os.path.join(OUT, f"{name}.md"), "w") as fh:
        fh.write(frontmatter(task, title, state, task, timeout) + body)
print(sorted(AGENTS))
