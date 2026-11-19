# hello

One dispatched **code** node (`survey`) and no LLM at all: proves the whole control plane (webhook → conductor → microVM → check → status → Postgres).

**Engine floor:** `min_engine_version` 19.0.0 · **Protocol version:** 0.2.0

**Status.** Verified live on the deployed factory (GitLab).

## Triggers

- `/hello` comment (`issue_comment`, command `start`)

## Top-level states

| id | kind | workflow / script |
|---|---|---|
| `survey` | code | `survey` |

Nested legs (forks, sub-pipelines, dynamic fan-outs) are declared in `protocol.json`.

## Units

- `workflows/survey.yml`

`survey.yml` is a plain workflow (a dispatched `code` node): no agent, nothing to compile.

## Install

Copy this directory to `<your-repo>/.softwarefactory/protocols/hello/`
and commit.
