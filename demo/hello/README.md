# hello

One dispatched **code** node (`survey`) and no LLM at all: proves the whole control plane (webhook → conductor → microVM → check → status → Postgres).

**Engine floor:** `min_engine_version` 9.0.0 · **Protocol version:** 0.2.0

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

Agent units are gh-aw markdown **sources**; compile them with gh-aw **v0.89.0**
before use (see the top-level README):

```bash
gh aw compile --dir <path-to-this-protocol>/workflows
```

## Install

Copy this directory to `<your-repo>/.softwarefactory/protocols/hello/`
and commit.
