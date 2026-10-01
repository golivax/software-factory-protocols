# code-review

The production review pipeline: `preflight` (six adherence legs + judges) → `preflight-verdict` → `overview` → `review` (five dimension legs) → `triage` → `fix` → `post-fix` (context ∥ mental-model update) → `mrp`. Opens one issue per finding, fixes and verifies each behind a honesty verdict.

**Engine floor:** `min_engine_version` 8.0.0 · **Protocol version:** 0.2.0

**Status.** Ported from the engine's GitHub-Actions era. Not yet re-verified on the deployed service and expected to need work (its units still reference the old in-repo `.github/agent-factory/...` paths); tracked as follow-up work in the engine repo.

## Triggers

- `/review` comment (`issue_comment`, command `start`)
- `/override` comment (`issue_comment`, command `override`)
- `/mm-answer` comment (`issue_comment`, command `answer`)

## Top-level states

| id | kind | workflow / script |
|---|---|---|
| `preflight` | fork | |
| `join-preflight` | join | |
| `preflight-verdict` | agent | `preflight-verdict-agent` |
| `overview` | agent | `overview-agent` |
| `review` | fork | |
| `join-review` | join | |
| `per-issue` | fork | |
| `join-per-issue` | join | |
| `honesty-verdict` | code | `aggregate-honesty` |
| `post-fix` | fork | |
| `join-post-fix` | join | |
| `mrp` | agent | `mrp-agent` |
| `emit-mrp` | code | `conclude-mrp` |

Nested legs (forks, sub-pipelines, dynamic fan-outs) are declared in `protocol.json`.

## Units

- `workflows/adherence-rollup-agent.md`
- `workflows/code-implements-plan-agent.md`
- `workflows/code-implements-plan-judge-agent.md`
- `workflows/consistency-rollup-agent.md`
- `workflows/context-agent.md`
- `workflows/docs-coherence-agent.md`
- `workflows/docs-updated-appropriately-judge-agent.md`
- `workflows/fix-agent.md`
- `workflows/fix-triage-agent.md`
- `workflows/honesty-cryptohash-agent.md`
- `workflows/honesty-fixverify-agent.md`
- `workflows/mm-compliance-agent.md`
- `workflows/mm-compliance-judge-agent.md`
- `workflows/mm-updater.md`
- `workflows/mrp-agent.md`
- `workflows/overview-agent.md`
- `workflows/plan-implements-spec-agent.md`
- `workflows/plan-implements-spec-judge-agent.md`
- `workflows/preflight-verdict-agent.md`
- `workflows/review-correctness-agent.md`
- `workflows/review-maintainability-agent.md`
- `workflows/review-performance-agent.md`
- `workflows/review-security-agent.md`
- `workflows/review-test-agent.md`
- `workflows/security-gather.yml`
- `workflows/security-judge-agent.md`
- `workflows/spec-solves-issue-agent.md`
- `workflows/spec-solves-issue-judge-agent.md`
- `workflows/tests-coherence-agent.md`
- `workflows/tests-updated-appropriately-judge-agent.md`

Agent units are gh-aw markdown **sources**; compile them with gh-aw **v0.89.0**
before use (see the top-level README):

```bash
gh aw compile --dir <path-to-this-protocol>/workflows
```

## Install

Copy this directory to `<your-repo>/.softwarefactory/protocols/code-review/`
and commit.
