# grumpy

A single gh-aw agent (a deliberately grumpy reviewer) dispatched on a merge-request comment — the smallest possible agent-lane protocol.

**Engine floor:** `min_engine_version` 7.1.0 · **Protocol version:** 0.1.0

**Status.** Verified live on the deployed factory (GitLab); you must compile the agent first.

## Triggers

- `/grumpy` comment (`issue_comment`, command `start`)

## Top-level states

| id | kind | workflow / script |
|---|---|---|
| `review` | agent | `grumpy-reviewer` |

Nested legs (forks, sub-pipelines, dynamic fan-outs) are declared in `protocol.json`.

## Units

- `workflows/grumpy-reviewer.md`

Agent units are gh-aw markdown **sources**; compile them with gh-aw **v0.89.0**
before use (see the top-level README):

```bash
gh aw compile --dir <path-to-this-protocol>/workflows
```

## Install

Copy this directory to `<your-repo>/.softwarefactory/protocols/grumpy/`
and commit.
