# grumpy

A deliberately grumpy reviewer, run the factory's way: **the agent proposes,
deterministic checks verify, a trusted step publishes.** Dispatched on a
merge-request comment.

**Engine floor:** `min_engine_version` 21.0.0 · **Protocol version:** 0.2.0

**Status.** Verified live on the deployed factory (GitLab); you must compile the agent first.

## How it works

1. **`review`** (agent): the `grumpy-reviewer.md` of gh-aw's agentics collection (githubnext/agentics), near-verbatim,
   with `safe-outputs: staged: true`. A step copies the run's snapshot
   (`$SF_SUBJECT_DIR`, the commit the run is pinned to) to `/tmp/gh-aw/agent/`, and the
   body's Step 2 points at it as the commit the review is about; the GitHub tools still
   read the MR, at its head of the moment. A pre-agent step checks the workspace out at
   that commit (the snapshot's `head_sha`) after gh-aw's checkout of the MR's head, and
   fails the job before the agent runs when it cannot. gh-aw still validates, sanitizes and
   threat-scans (its detection job) the review the agent proposes, but writes
   nothing to the forge. Its safe_outputs job, which runs only once detection
   passed and holds no forge write permission, hands the staged items, each
   projected onto the schema's fields (values verbatim, null where a type has
   none), to the engine as the node's evidence (`{sha, staged}`).
2. **The engine validates** that evidence against `review.evidence.schema.json`
   (in the structured-output subset, like every agent schema): only the two
   review item types (plus gh-aw's own reporting items) and their fields.
3. **Checks** (pure, over the evidence and the engine's ground truth in
   `$CHECK_CTX`); a failure iterates the agent with the feedback:
   - `review-coherent`: each item type's required fields and the workflow's
     maxes (5 comments, 1 verdict; `_review.form_errors`), the review is for the
     commit whose diff was checked, it says something, `REQUEST_CHANGES` gives a
     reason, no duplicate anchors;
   - `anchors-in-diff`: every comment sits on a line the MR diff shows.
4. **`publish`** (dispatched code, its own microVM): posts the checked review
   through gh2forge, pinned to the reviewed commit: on an MR that moved since, the
   forge shows it as outdated. It is the only forge write in the protocol.

## Triggers

- `/grumpy` comment (`issue_comment`, command `start`)

## Top-level states

| id | kind | workflow / script |
|---|---|---|
| `review` | agent | `grumpy-reviewer` |
| `publish` | code (dispatched) | `publish-review` |

## Units

- `workflows/grumpy-reviewer.md` (agent)
- `workflows/publish-review.yml` (code)
- `checks/review-coherent.py`, `checks/anchors-in-diff.py` (+ `checks/_review.py`, the shared reading of the staged items)

## Agent slot

`grumpy-reviewer.md` imports `shared/agent.md`, this protocol's one agent slot (see the top-level
README, "Agent slots"). It needs no more than a small model; tested on codex with gpt-6-luna.

Agent units are gh-aw markdown **sources**. Fill the slot, add the profile's
`network.allowed` hosts to the `egress` of the agent nodes that run it, then compile
them with gh-aw **v0.89.0** before use (see the top-level README):

```bash
cp <your profile>.md <path-to-this-protocol>/workflows/shared/agent.md
gh aw compile --dir <path-to-this-protocol>/workflows
```

## Install

Copy this directory to `<your-repo>/.softwarefactory/protocols/grumpy/`
and commit.
