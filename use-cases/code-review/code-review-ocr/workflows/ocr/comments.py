"""Review comments as upstream's code_comment tool files them.

Ported from internal/tool/code_comment.go (ParseCommentsWithPath and its
normalizers) and the comment branch of internal/reviewtask/tools.go
(executeToolCall: resolve, re-file across files, then re-locate by LLM).
A comment is upstream's model.LlmComment as a dict: path, content,
existing_code, suggestion_code, category, severity, start_line, end_line.
"""
import posixpath

from . import diffs as D

CATEGORIES = ("bug", "security", "performance", "maintainability", "test", "style",
              "documentation", "other")
SEVERITIES = ("critical", "high", "medium", "low")


def normalize_path(p):
    if not p:
        return ""
    p = posixpath.normpath(p.replace("\\", "/"))
    if p.startswith("//"):          # path.Clean keeps one leading slash, normpath two
        p = "/" + p.lstrip("/")
    if p == ".":
        return ""
    return p.removeprefix("/")


def parse(raw_comments, default_path):
    """ParseCommentsWithPath: drop entries with no content or path."""
    out = []
    for obj in raw_comments or []:
        if not isinstance(obj, dict):
            continue
        cm = {"content": obj.get("content") or "",
              "existing_code": obj.get("existing_code") or "",
              "suggestion_code": obj.get("suggestion_code") or "",
              "category": "", "severity": "",
              "path": normalize_path(obj.get("path") or "") or normalize_path(default_path),
              "start_line": 0, "end_line": 0}
        if isinstance(obj.get("category"), str):
            c = obj["category"].lower()
            cm["category"] = c if c in CATEGORIES else "other"
        if isinstance(obj.get("severity"), str):
            s = obj["severity"].lower()
            cm["severity"] = s if s in SEVERITIES else "low"
        if not cm["path"] or not cm["content"]:
            continue
        out.append(cm)
    return out


def place(cm, selection):
    """The synchronous part of filing one comment: resolve it in its own
    file's diff, else re-file it to the one other file whose diff holds its
    code. Returns (needs_llm_relocation, warning or None)."""
    d = selection.find(cm["path"])
    located = d is not None and D.resolve_comment(cm, d)
    warning = None
    if not located:
        origin = cm["path"]
        to = D.relocate_across_files(cm, selection.kept)
        if to:
            located = True
            warning = {"type": "comment_refiled", "file": to,
                       "message": f"comment filed against {origin} describes code in {to}; re-filed"}
    return (d is not None and not located), warning
