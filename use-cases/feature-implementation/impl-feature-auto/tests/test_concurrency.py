"""The fixer agents are dispatched once PER ISSUE, so each carries a
per-dispatch (cid) concurrency group: gh-aw's default `gh-aw-<workflow>` group
would serialize the fixers across issues (issue-X waits on issue-Y)."""
from pathlib import Path

import yaml

PROTOCOL = Path(__file__).resolve().parents[1]   # this test's protocol


def _frontmatter(md):
    """The YAML frontmatter of a gh-aw unit source (`---` … `---`), parsed."""
    text = md.read_text()
    if not text.startswith("---"):
        return {}
    return yaml.safe_load(text[3:text.find("\n---", 3)]) or {}


def test_fixer_agents_have_per_cid_concurrency():
    for name in ("impl-feature-auto-design-agent", "impl-feature-auto-implement-agent"):
        src = PROTOCOL / "workflows" / f"{name}.md"
        assert src.is_file(), f"{name}: unit source not found"
        # the library carries sources only; gh-aw copies the top-level
        # `concurrency` block into the compiled lock verbatim
        group = (_frontmatter(src).get("concurrency") or {}).get("group")
        assert group is not None, f"{name}: no top-level concurrency group"
        assert "cid" in group and "aw_context" in group, (
            f"{name}: concurrency group '{group}' is not per-dispatch (cid) — the "
            "default gh-aw-<workflow> group serializes fixers across issues")
