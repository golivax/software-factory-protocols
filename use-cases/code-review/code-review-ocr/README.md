# code-review-ocr

A review that fans out dynamically per changed file: `plan` decides the per-file legs, `filter` prunes them, `main-review` runs one leg per file and the results are joined.

**Engine floor:** `min_engine_version` 14.0.0 · **Protocol version:** unversioned

**Status.** Ported from the engine's GitHub-Actions era. Not yet re-verified on the deployed service and expected to need work (its units still reference the old in-repo `.github/agent-factory/...` paths); tracked in golivax/software-factory#269 (re-verify the ported use-case protocols live on microVM-per-job).

## Triggers

- `/ocr-review` comment (`issue_comment`, command `start`)

## Top-level states

| id | kind | workflow / script |
|---|---|---|
| `review` | fork | |
| `join-review` | join | |
| `merge` | code | `post-review` |

Nested legs (forks, sub-pipelines, dynamic fan-outs) are declared in `protocol.json`.

## Units

- `workflows/ocr-filter-agent.md`
- `workflows/ocr-main-agent.md`
- `workflows/ocr-plan-agent.md`

## Agent slot

All three agents (`ocr-plan-agent.md`, `ocr-main-agent.md`, `ocr-filter-agent.md`) import `shared/agent.md`, this protocol's one agent slot (see the top-level
README, "Agent slots"). It needs a strong coding model; tested on codex with gpt-6.1-sol.

Agent units are gh-aw markdown **sources**. Fill the slot, add the profile's
`network.allowed` hosts to the `egress` of the agent nodes that run it, then compile
them with gh-aw **v0.89.0** before use (see the top-level README):

```bash
cp <your profile>.md <path-to-this-protocol>/workflows/shared/agent.md
gh aw compile --dir <path-to-this-protocol>/workflows
```

## Install

Copy this directory to `<your-repo>/.softwarefactory/protocols/code-review-ocr/`
and commit.
