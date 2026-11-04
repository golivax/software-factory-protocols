---
# An agent profile: the agent, model and LLM gateway that fill an agent slot
# (README.md, "Agent slots"). Copy it to <protocol>/workflows/shared/<slot>.md,
# replace the placeholders, then compile. Frontmatter only: gh-aw merges it into
# every unit that imports the slot. The gateway's key is not here: it comes from
# the deployment's agent secrets file (AGENT_SECRETS_FILE).
engine:
  id: codex                                   # the agent CLI (gh-aw engine id)
  model: <model>                              # a model the gateway serves
  env:
    OPENAI_BASE_URL: https://<gateway host>/v1/   # ANTHROPIC_BASE_URL for claude
network:
  allowed:
    - <gateway host>                          # the agent's firewall lets it through
---
