"""The contract of impl-feature-auto's agent units, asserted on their sources
(`workflows/*.md`): the library carries no compiled locks, and gh-aw copies
`permissions` and `safe-outputs` into the lock verbatim."""
from pathlib import Path

import yaml

PROTOCOL = Path(__file__).resolve().parents[1]   # this test's protocol


def _unit(name):
    src = PROTOCOL / "workflows" / f"{name}.md"
    assert src.is_file(), f"{name}: unit source not found"
    return src


def _frontmatter(md):
    """The YAML frontmatter of a gh-aw unit source (`---` … `---`), parsed."""
    text = md.read_text()
    if not text.startswith("---"):
        return {}
    return yaml.safe_load(text[3:text.find("\n---", 3)]) or {}


def test_design_agent_is_readonly_and_bundles_spec():
    p = _unit("impl-feature-auto-design-agent")
    fm, t = _frontmatter(p), p.read_text()
    # The agent job (the one running the LLM) is read-only: design writes no
    # repo content. gh-aw's safe_outputs jobs carry their own write scopes, so
    # the invariant is on the agent's declaration.
    assert (fm.get("permissions") or {}).get("contents") == "read"
    outs = fm.get("safe-outputs") or {}
    assert "create-pull-request" not in outs        # design opens no PR
    # No per-run status issue: the default create-issue is suppressed by
    # declaring a real safe-output (add-comment, which the prompt forbids the
    # agent from emitting, so it stays inert).
    assert "create-issue" not in outs
    assert "add-comment" in outs
    assert "evidence" in t                          # uploads its evidence artifact
    assert ".agents/skills" in t                    # stages the skills codex reads


def test_implement_agent_opens_pr():
    # implement opens the PR through safe-outputs (gh-aw compiles the key to
    # `create_pull_request` in the lock; the source key is the hyphenated one).
    fm = _frontmatter(_unit("impl-feature-auto-implement-agent"))
    assert "create-pull-request" in (fm.get("safe-outputs") or {})
