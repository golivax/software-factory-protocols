# recover-mental-model-interactive

The interactive twin of `recover-mental-model`: the socratic `answering` step is a human task on a dedicated issue (`/answer <id>: <value>`) instead of an agent; `phase2` resumes once every open question is answered.

**Engine floor:** `min_engine_version` 7.0.0 · **Protocol version:** 1.0.0

**Status.** Ported from the engine's GitHub-Actions era. Not yet re-verified on the deployed service and expected to need work (its units still reference the old in-repo `.github/agent-factory/...` paths); tracked as follow-up work in the engine repo.

## Triggers

- `/answer` comment (`issue_comment`, command `answer`)

## Top-level states

| id | kind | workflow / script |
|---|---|---|
| `recover` | fork | |
| `join` | join | |
| `combine` | code | `push-mental-model` |

Nested legs (forks, sub-pipelines, dynamic fan-outs) are declared in `protocol.json`.

## Units

- `workflows/mm-socratic-phase2-interactive-agent.md`
- `commons/workflows/mm-codeset-agent.md` (shared, at the library root; see the top-level README)
- `commons/workflows/mm-legion-agent.md` (shared, at the library root; see the top-level README)
- `commons/workflows/mm-socratic-phase1-agent.md` (shared, at the library root; see the top-level README)
- `commons/workflows/mm-ubiquitous-language-agent.md` (shared, at the library root; see the top-level README)

Agent units are gh-aw markdown **sources**; compile them with gh-aw **v0.89.0**
before use (see the top-level README):

```bash
gh aw compile --dir <path-to-this-protocol>/workflows
```

## Install

Copy this directory to `<your-repo>/.softwarefactory/protocols/recover-mental-model-interactive/`
(and `commons/` to `<your-repo>/.softwarefactory/protocols/commons/`) and commit.
