---
# An agent profile: the agent and model endpoint that fill an agent slot
# (README.md, "Agent slots"). It names no model: the lock reads the model from
# the GH_AW_MODEL_AGENT_<ENGINE> / GH_AW_DEFAULT_MODEL_<ENGINE> variables, which
# the factory sets for each run, and the threat-detection block below reads the
# detection model the same way. Copy it to <protocol>/workflows/shared/<slot>.md,
# replace the placeholders, then compile. Frontmatter only: gh-aw merges it into
# every unit that imports the slot. Add every `network.allowed` host to the
# `egress` of each agent node that runs such a unit: the registry refuses the
# protocol otherwise. The endpoint's key is not here: the lock reads it as a
# secret (OPENAI_API_KEY for codex, ANTHROPIC_API_KEY for claude), whose value
# the factory picks for each run.
engine:
  id: codex                                   # the agent CLI (gh-aw engine id)
  env:
    OPENAI_BASE_URL: https://<endpoint host>/v1/   # ANTHROPIC_BASE_URL for claude
network:
  allowed:
    - <endpoint host>                         # the agent's firewall lets it through
safe-outputs:
  threat-detection:                           # without it gh-aw detects on a fixed alias
    engine:
      id: codex                               # the same agent CLI as above
      model: ${{ vars.GH_AW_MODEL_DETECTION_CODEX || vars.GH_AW_DEFAULT_MODEL_CODEX }}
---
