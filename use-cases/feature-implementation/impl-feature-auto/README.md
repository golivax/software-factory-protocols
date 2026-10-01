# impl-feature-auto

Implements a feature from an issue end to end: `design` (spec + ledger + plan, iterated until the ledger checks pass) → `implement` (TDD + open a PR) → `post-summary` (comment the PR link on the issue).

**Engine floor:** `min_engine_version` 8.0.0 · **Protocol version:** 0.1.0

**Status.** Ported from the engine's GitHub-Actions era. Not yet re-verified on the deployed service and expected to need work (its units still reference the old in-repo `.github/agent-factory/...` paths); tracked as follow-up work in the engine repo.

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

Agent units are gh-aw markdown **sources**; compile them with gh-aw **v0.89.0**
before use (see the top-level README):

```bash
gh aw compile --dir <path-to-this-protocol>/workflows
```

## Install

Copy this directory to `<your-repo>/.softwarefactory/protocols/impl-feature-auto/`
and commit.
