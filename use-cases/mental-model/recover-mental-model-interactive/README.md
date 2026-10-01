# recover-mental-model-interactive

The interactive twin of `recover-mental-model`: the socratic `answering` step is a human task on a dedicated issue (`/answer <id>: <value>`) instead of an agent; `phase2` resumes once every open question is answered.

**Engine floor:** `min_engine_version` 8.0.0 · **Protocol version:** 1.0.0

**Status.** Runs on the deployed service. The legs' file trees travel on the engine's `outputs:` transport (issue #68) — declared `outputs: true`, collected by the engine, handed to `combine` as `inputs/<leg>/` — not in Actions artifacts, which no non-GitHub forge has.

## Triggers

- `manual` (command `start`, against a ref) — starts the run
- `/answer` comment (`issue_comment`, command `answer`) — resumes it at the human gate

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
