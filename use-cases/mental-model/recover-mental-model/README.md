# recover-mental-model

Recovers a codebase's mental model with four parallel methods (`legion` ∥ `codeset` ∥ `ubiquitous-language` ∥ a `socratic` sub-pipeline) → `join` → a `combine` code node that pushes the result to an orphan `_mental_model` branch. Fully automated; started via the `manual` trigger against a ref.

**Engine floor:** `min_engine_version` 7.1.0 · **Protocol version:** 1.0.0

**Status.** Runs on the deployed service. The legs' file trees travel on the engine's `outputs:` transport (issue #68) — declared `outputs: true`, collected by the engine, handed to `combine` as `inputs/<leg>/` — not in Actions artifacts, which no non-GitHub forge has. Verified end to end against a GitLab deployment.

## Triggers

- `manual` (command `start`, against a ref)

## Top-level states

| id | kind | workflow / script |
|---|---|---|
| `recover` | fork | |
| `join` | join | |
| `combine` | code | `push-mental-model` |

Nested legs (forks, sub-pipelines, dynamic fan-outs) are declared in `protocol.json`.

## Units

- `workflows/mm-socratic-answering-agent.md`
- `workflows/mm-socratic-phase2-agent.md`
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

Copy this directory to `<your-repo>/.softwarefactory/protocols/recover-mental-model/`
(and `commons/` to `<your-repo>/.softwarefactory/protocols/commons/`) and commit.
