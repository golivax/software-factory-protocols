"""Upstream OCR's prompts, filled in as upstream fills them.

Each task's messages come from the vendored task_template.json and prompts/
(read as upstream's resolveConversation reads them: trailing newlines
trimmed); placeholders are replaced in upstream's order (agent.go
buildMainTaskMessages / executeGroupPlanPhase / executeGroupReviewFilter,
grouping.go callGroupingLLM, diff/relocation.go BuildReLocationMessages).
A render returns [(role, content)].
"""
import json
import os
import re

UPSTREAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upstream")

PLAN_BLOCK_RE = re.compile(r"(?m)^### [^\n]*Review Plan[^\n]*\n\{\{plan_guidance\}\}\n\n?")
CONFIRMED_BLOCK_RE = re.compile(r"(?m)^### [^\n]*Confirmed Findings[^\n]*\n\{\{confirmed_comments\}\}\n\n?")
CONFIRMED_MAX_EXISTING_CODE = 200
CONFIRMED_MAX_CONTENT = 300
CONFIRMED_CAP = 30


def _template():
    with open(os.path.join(UPSTREAM, "task_template.json"), encoding="utf-8") as fh:
        return json.load(fh)


def template_task(task):
    return _template()[task]


def messages(task, language=None):
    """A task's (role, content) list; `language` appends upstream's
    ApplyLanguage directive to its system messages."""
    out = []
    for m in _template()[task]["messages"]:
        with open(os.path.join(UPSTREAM, "prompts", m["prompt_file"]), encoding="utf-8") as fh:
            content = fh.read().rstrip("\r\n")
        if language is not None and m["role"] == "system":
            content += "\n\nAlways respond in " + (language or "English") + "."
        out.append((m["role"], content))
    return out


SIDE_PARAMETER = {"type": "string", "enum": ["new", "old"],
                  "description": "The side of the current comparison to access. Defaults to new. "
                                 "Paths and line numbers belong to the selected side."}
SIDE_TOOLS = ("file_read", "file_find", "code_search")


def _with_comparison_side(d):
    """toolsconfig.WithComparisonSides: a review of a range (`--from/--to`, as
    upstream's CI runs it) lets these tools read either side of it."""
    d = json.loads(json.dumps(d))
    d["parameters"]["properties"]["side"] = dict(SIDE_PARAMETER)
    desc = d["description"].replace(
        "This tool can only read file content from the modified version (after changes) in git diff.",
        "This tool reads either side of the current comparison.").replace(
        "This tool searches in the current version of files.",
        "This tool searches in the selected side of the current comparison.")
    d["description"] = desc + ("\n\nOmit side or use side=new for the reviewed new version. Use side=old "
                               "for the frozen comparison base, not the current target branch tip. For "
                               "renamed files, use the path on the selected side; paths are not "
                               "automatically translated. An empty old tree contains no files.")
    return d


def tool_definitions():
    """The tool definitions a range review gives the model, by name."""
    with open(os.path.join(UPSTREAM, "toolsconfig", "tools.json"), encoding="utf-8") as fh:
        defs = {t["name"]: t["definition"] for t in json.load(fh)}
    return {n: _with_comparison_side(d) if n in SIDE_TOOLS else d for n, d in defs.items()}


def format_tool_defs(names):
    """formatToolDefs over the named tools, parameters in definition order."""
    if not names:
        return ""
    defs = tool_definitions()
    lines = ["### Available Tools (reference only — do not call)\n"]
    for name in names:
        d = defs[name]
        lines.append(f"- **{d['name']}**: {d['description']}\n")
        props = (d.get("parameters") or {}).get("properties") or {}
        if props:
            required = set((d.get("parameters") or {}).get("required") or [])
            lines.append("  Parameters:\n")
            for pname, meta in props.items():
                suffix = " (required)" if pname in required else ""
                lines.append(f"  - {pname}: {(meta or {}).get('description', '')}{suffix}\n")
    return "".join(lines)


def _sub(content, pairs):
    for key, value in pairs:
        content = content.replace(key, value)
    return content


def grouping(file_list):
    return [(r, _sub(c, [("{{file_list}}", file_list)])) for r, c in messages("GROUPING_TASK")]


def plan(*, date, rule, change_files, diffs, background, language):
    tools = format_tool_defs(_template()["PLAN_TASK"].get("tool_references") or [])
    return [(r, _sub(c, [("{{current_system_date_time}}", date), ("{{system_rule}}", rule),
                         ("{{change_files}}", change_files), ("{{diffs}}", diffs),
                         ("{{requirement_background}}", background),
                         ("{{plan_tools}}", tools)]))
            for r, c in messages("PLAN_TASK", language)]


def main(*, date, rule, change_files, diffs, background, plan_result, confirmed, language):
    out = []
    for role, c in messages("MAIN_TASK", language):
        c = _sub(c, [("{{current_system_date_time}}", date), ("{{system_rule}}", rule),
                     ("{{change_files}}", change_files), ("{{diffs}}", diffs),
                     ("{{requirement_background}}", background)])
        if plan_result == "":
            c = PLAN_BLOCK_RE.sub("", c)
        c = c.replace("{{plan_guidance}}", plan_result)
        if confirmed == "":
            c = CONFIRMED_BLOCK_RE.sub("", c)
        c = c.replace("{{confirmed_comments}}", confirmed)
        out.append((role, c))
    return out


def review_filter(*, group_key, diffs, comments_json):
    return [(r, _sub(c, [("{{path}}", group_key), ("{{diff}}", diffs),
                         ("{{comments}}", comments_json)]))
            for r, c in messages("REVIEW_FILTER_TASK")]


def relocation(*, diff, existing_code, content):
    return [(r, _sub(c, [("{diff}", diff), ("{existing_code}", existing_code),
                         ("{suggestion_content}", content)]))
            for r, c in messages("RE_LOCATION_TASK")]


def flatten_one_line(s):
    return s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()


def confirmed_block(comments):
    """buildConfirmedCommentsBlock."""
    if not comments:
        return ""
    parts = ["The following issues were already identified and confirmed in a prior review pass. "
             "Do not repeat them. "
             "Continue reviewing all files in <review_files> and report any other real issues you find.\n\n",
             "<confirmed_findings>\n"]
    for i, cm in enumerate(comments):
        parts.append(f"{i + 1}. {cm['path']}\n")
        if cm.get("existing_code"):
            code = flatten_one_line(cm["existing_code"])
            if len(code) > CONFIRMED_MAX_EXISTING_CODE:
                code = code[:CONFIRMED_MAX_EXISTING_CODE] + "..."
            parts.append(f"   code: {code}\n")
        content = flatten_one_line(cm.get("content") or "")
        if len(content) > CONFIRMED_MAX_CONTENT:
            content = content[:CONFIRMED_MAX_CONTENT] + "..."
        parts.append(f"   issue: {content}\n")
    parts.append("</confirmed_findings>")
    return "".join(parts)


def filter_comments_json(comments):
    """buildGroupFilterCommentsJSON: ids c-0, c-1, … in candidate order."""
    items = []
    for i, cm in enumerate(comments):
        item = {"id": f"c-{i}", "path": cm.get("path") or "", "content": cm.get("content") or ""}
        if cm.get("existing_code"):
            item["existing_code"] = cm["existing_code"]
        items.append(item)
    return go_json(items)


def go_json(value):
    """json.Marshal's bytes: compact, non-ASCII kept, and its HTML escaping of
    <, >, & and the two JavaScript line separators."""
    out = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    for ch, esc in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                    (" ", "\\u2028"), (" ", "\\u2029")):
        out = out.replace(ch, esc)
    return out


def to_markdown(msgs):
    """The rendered conversation as one document an agent reads."""
    return "\n\n".join(f"<message role=\"{role}\">\n{content}\n</message>" for role, content in msgs)
