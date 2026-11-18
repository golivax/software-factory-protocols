# impl-feature-auto

Implements a feature from an issue end to end: `design` (spec + ledger + plan, iterated until the ledger checks pass) → `implement` (TDD + open a PR) → `post-summary` (comment the PR link on the issue).

**Engine floor:** `min_engine_version` 18.0.0 · **Protocol version:** 0.1.0

**Status.** Ported from the engine's GitHub-Actions era. Not yet re-verified on the deployed service and expected to need work (its units still reference the old in-repo `.github/agent-factory/...` paths); tracked in golivax/software-factory#269 (re-verify the ported use-case protocols live on microVM-per-job).

## Triggers

- `/impl-feature-auto` comment (`issue_comment`, command `start`, target `issue`)

## Top-level states

| id | kind | workflow / script |
|---|---|---|
| `design` | agent | `impl-feature-auto-design-agent` |
| `implement` | agent | `impl-feature-auto-implement-agent` |
| `post-summary` | code | `post-summary` |

Nested legs (forks, sub-pipelines, dynamic fan-outs) are declared in `protocol.json`.

## Units

- `workflows/impl-feature-auto-design-agent.md`
- `workflows/impl-feature-auto-implement-agent.md`
- `workflows/shared/skill-preamble.md`

## Agent slot

Both agents import `shared/agent.md`, this protocol's one agent slot (see the top-level
README, "Agent slots"). It needs a strong coding model; tested on codex with gpt-6.1-sol.
It also needs the **codex** agent, and the profile's `engine:` must carry
`args: ["-c", "features.multi_agent=true"]`: both agents stage the superpowers skills
into `.agents/skills`, where codex reads them, and the implement agent's
`subagent-driven-development` dispatches subagents through codex's `spawn_agent`,
which only multi-agent mode provides (golivax/software-factory#435).

Agent units are gh-aw markdown **sources**. Fill the slot, add the profile's
`network.allowed` hosts to the `egress` of the agent nodes that run it, then compile
them with gh-aw **v0.89.0** before use (see the top-level README):

```bash
cp <your profile>.md <path-to-this-protocol>/workflows/shared/agent.md
gh aw compile --dir <path-to-this-protocol>/workflows
```

## Install

Copy this directory to `<your-repo>/.softwarefactory/protocols/impl-feature-auto/`
and commit.
