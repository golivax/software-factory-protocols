# demo

The authoring template: one dispatched **code** node (`facts`) feeding one **agent** node (`summarize`) whose source you compile yourself. Each runs in its own disposable microVM (the agent node: one per gh-aw job).

**Engine floor:** `min_engine_version` 10.0.0 · **Protocol version:** 0.1.0

**Status.** Verified live on the deployed factory (GitLab); you must compile the agent first.

## Triggers

- `/demo` comment (`issue_comment`, command `start`)

## Top-level states

| id | kind | workflow / script |
|---|---|---|
| `facts` | code | `demo-facts` |
| `summarize` | agent | `demo-summarize` |

Nested legs (forks, sub-pipelines, dynamic fan-outs) are declared in `protocol.json`.

## Units

- `workflows/demo-facts.yml`
- `workflows/demo-summarize.md`

Agent units are gh-aw markdown **sources**; compile them with gh-aw **v0.89.0**
before use (see the top-level README):

```bash
gh aw compile --dir <path-to-this-protocol>/workflows
```

## Install

Copy this directory to `<your-repo>/.softwarefactory/protocols/demo/`
and commit.
