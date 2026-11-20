# toy

A **code** node (`compute`) produces records; an **agent** node (`assess`) claims the maximum and the `max-claim-correct` check settles it against ground truth.

**Engine floor:** `min_engine_version` 20.1.0 · **Protocol version:** 1.0.0

**Status.** Verified live on the deployed factory (GitLab); you must compile the agent first.

## Triggers

- `/toy` comment (`issue_comment`, command `start`)

## Top-level states

| id | kind | workflow / script |
|---|---|---|
| `compute` | code | `compute` |
| `assess` | agent | `assess-agent` |

Nested legs (forks, sub-pipelines, dynamic fan-outs) are declared in `protocol.json`.

## Units

- `workflows/assess-agent.md`
- `workflows/compute.yml`

## Agent slot

`assess-agent.md` imports `shared/agent.md`, this protocol's one agent slot (see the top-level
README, "Agent slots"). It needs no more than a small model; tested on codex with gpt-6-luna.

Agent units are gh-aw markdown **sources**. Fill the slot, add the profile's
`network.allowed` hosts to the `egress` of the agent nodes that run it, then compile
them with gh-aw **v0.89.0** before use (see the top-level README):

```bash
cp <your profile>.md <path-to-this-protocol>/workflows/shared/agent.md
gh aw compile --dir <path-to-this-protocol>/workflows
```

## Install

Copy this directory to `<your-repo>/.softwarefactory/protocols/toy/`
and commit.
