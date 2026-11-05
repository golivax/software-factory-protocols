---
# An agent profile: the agent, model and model endpoint that fill an agent slot
# (README.md, "Agent slots"). Copy it to <protocol>/workflows/shared/<slot>.md,
# replace the placeholders, then compile. Frontmatter only: gh-aw merges it into
# every unit that imports the slot. Add every `network.allowed` host to the
# `egress` of each agent node that runs such a unit: the registry refuses the
# protocol otherwise. The endpoint's key is not here: it comes from the
# deployment's agent secrets file (AGENT_SECRETS_FILE).
engine:
  id: codex                                   # the agent CLI (gh-aw engine id)
  model: <model>                              # a model the endpoint serves
  env:
    OPENAI_BASE_URL: https://<endpoint host>/v1/   # ANTHROPIC_BASE_URL for claude
network:
  allowed:
    - <endpoint host>                         # the agent's firewall lets it through
---
