<!-- Shared skill-invocation preamble, runtime-imported by the design & implement
agents via `{{#runtime-import .github/workflows/shared/skill-preamble.md}}`.
The agents run on the codex engine, which reads repository skills from
.agents/skills/ (every directory from the working directory up to the repo root);
the pre-agent steps stage the superpowers skills there. Adapted from superpowers' own
using-superpowers SKILL.md. This file has no `on:` field, so gh-aw treats it as a
shared component and does not compile it on its own. -->

You have superpowers. Skills live under `.agents/skills/` (staged as repository
skills, so they are BARE-NAMED — e.g. `writing-plans`, NOT `superpowers:writing-plans`;
the namespaced `superpowers:` form will NOT resolve here, so always drop that prefix).

<EXTREMELY-IMPORTANT>
If you think there is even a 1% chance a skill applies to what you are doing, you
ABSOLUTELY MUST use it. IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE.
YOU MUST USE IT. This is not negotiable, not optional, and you cannot rationalize your
way out of it.
</EXTREMELY-IMPORTANT>

**How to use a skill:** mention it by its bare name with a `$` — e.g. `$writing-plans`
or `$executing-plans`, never with a `superpowers:` prefix — and then follow the
skill's own instructions. Loading the skill is what gives you its real instructions;
do not work from memory of what the skill probably says.

These thoughts mean STOP — you are rationalizing:
- "The skill is overkill / this task is tiny" → Simple things become complex. Use it.
- "I know what that skill does" → Knowing the concept ≠ using the skill. Load it.
- "I'll just do it directly" → That is skipping the skill. Don't.
