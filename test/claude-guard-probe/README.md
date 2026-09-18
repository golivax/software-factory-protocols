# claude-guard-probe

**A diagnostic, not a demo.** It exists to answer one open question about engine coverage.

## The question

Every refusal the framework has recorded came from the **codex** engine. On **claude** the
hook has been installed many times and has never adjudicated a single call — `verify.py`
reporting `guard=unenforced`, `calls=0`, *"no liveness record: the hook never ran for this
agent, so the run proves nothing about the guard"*.

This protocol is [`cedar-denied-demo`](../cedar-denied-demo)'s task on the claude engine,
so the engine is the only variable.

| Trigger | `/claude-guard` |
|---|---|
| guard `denied`, one incident | the hook fires on claude — coverage confirmed |
| guard `unenforced`, `calls=0` | the hook does not fire — a real gap to fix |

Either answer is worth having, and one run gives it.

## Status: unanswered

In the deployment it was written for, **every** Claude model on **both** configured LLM
endpoints returns 429 — credentials cooling down, or account rate limit — across haiku,
sonnet and opus alike. The CLI exhausts its retries and exits before the agent issues any
tool call, so the guard has nothing to intercept and the probe measures nothing.

That failure is not the guard's doing: claude runs in that deployment were already failing
this way *before* the guard was ever installed, and the claude CLI accepts every flag the
lock transform gives it, spawning cleanly each attempt before the model call fails.

Point it at an endpoint with Claude capacity and it settles the question.

## States

One `agent` node, `probe`, `max_iterations` 1. The check `probe-ran` is advisory by
design: the deliverable is the guard's own record, not the agent's account of it. Asking
the agent whether the guard fired would be asking the suspect for the verdict.

## Units

* `workflows/claude-guard-probe-agent.md` — engine `claude`; set its `ANTHROPIC_BASE_URL`
  to a gateway that has Claude capacity.

## Install

```sh
gh aw compile --dir claude-guard-probe/workflows
```
