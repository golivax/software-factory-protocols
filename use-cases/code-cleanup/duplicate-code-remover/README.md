# duplicate-code-remover

Detects duplicated code across the repository with a single agent and reports it as structured evidence for the checks to settle.

**Engine floor:** `min_engine_version` 13.0.0 · **Protocol version:** 0.1.0

**Status.** Ported from the engine's GitHub-Actions era. Not yet re-verified on the deployed service and expected to need work (its units still reference the old in-repo `.github/agent-factory/...` paths); tracked in golivax/software-factory#269 (re-verify the ported use-case protocols live on microVM-per-job).

## Triggers

- `schedule` → `start`
- `workflow_dispatch` → `start`

## Top-level states

| id | kind | workflow / script |
|---|---|---|
| `detect` | agent | `duplicate-code-remover-detect-agent` |
| `file-issues` | code | `file-issues` |

Nested legs (forks, sub-pipelines, dynamic fan-outs) are declared in `protocol.json`.

## Units

- `workflows/duplicate-code-remover-detect-agent.md`

Agent units are gh-aw markdown **sources**; compile them with gh-aw **v0.89.0**
before use (see the top-level README):

```bash
gh aw compile --dir <path-to-this-protocol>/workflows
```

## Install

Copy this directory to `<your-repo>/.softwarefactory/protocols/duplicate-code-remover/`
and commit.
