"""Which changed files are reviewed, and how they are grouped.

Ported from internal/agent/{selection,grouping}.go, internal/config/allowlist
and internal/config/template (the thresholds, read from the vendored
task_template.json). Diffs are diffs.py dicts.
"""
import json
import math
import os

from . import globs

UPSTREAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upstream")
MAX_FILES_PER_GROUP = 10
SMALL_CHANGE_SET_LABEL = "small change set"
TOKEN_WARNING_THRESHOLD = 0.8          # llmloop.tokenWarningThreshold


def _upstream_json(*parts):
    with open(os.path.join(UPSTREAM, *parts), encoding="utf-8") as fh:
        return json.load(fh)


def template():
    """The scalars of task_template.json: thresholds, rounds, token limits."""
    return {k: v for k, v in _upstream_json("task_template.json").items()
            if not isinstance(v, dict)}


SUPPORTED_EXTS = frozenset(e.lower() for e in _upstream_json("allowlist", "supported_file_types.json"))
EXCLUDE_PATTERNS = [p.lower() for p in _upstream_json("allowlist", "default_exclude_patterns.json")]
SECRET_PATTERNS = [p.lower() for p in _upstream_json("allowlist", "default_secret_patterns.json")]


def count_tokens(text):
    """Upstream counts cl100k_base tokens with tiktoken; a code node has no
    tokenizer, so this estimates four bytes a token."""
    return math.ceil(len(text.encode("utf-8")) / 4)


def prompt_token_limit(max_tokens):
    return int(max_tokens * TOKEN_WARNING_THRESHOLD)


def is_secret_path(path):
    lower = path.lower()
    base = lower.rsplit("/", 1)[-1]
    if base not in (".env.example", ".env.sample", ".env.template") and \
            (base == ".env" or base.startswith(".env.")):
        return True
    return any(globs.match(p, lower) for p in SECRET_PATTERNS)


def is_allowed_ext(ext):
    return ext.lower() in SUPPORTED_EXTS


def is_excluded_path(path):
    lower = path.lower()
    return any(globs.match(p, lower) for p in EXCLUDE_PATTERNS)


def ext_from_path(path):
    base = path.rsplit("/", 1)[-1]
    dot = base.rfind(".")
    return "" if dot <= 0 else base[dot:].lower()


def _filter_hit(patterns, path):
    lower = path.lower()
    return any(globs.match(p, lower) for p in patterns)


def why_excluded(d, file_filter):
    """whyExcluded: the static gates, in upstream's order."""
    from .diffs import effective_path
    if d["is_binary"]:
        return "binary"
    path = effective_path(d)
    if is_secret_path(d["old_path"]) or is_secret_path(d["new_path"]):
        return "secret_exclude"
    if file_filter and _filter_hit(file_filter["exclude"], path):
        return "user_exclude"
    if file_filter and file_filter["include"] and _filter_hit(file_filter["include"], path):
        return ""
    ext = ext_from_path(path)
    if ext and not is_allowed_ext(ext):
        return "unsupported_ext"
    if is_excluded_path(path):
        return "default_path"
    return ""


def select_files(diffs, file_filter, max_tokens):
    """selectFiles: one decision per diff, `reason` "" when selected."""
    limit = prompt_token_limit(max_tokens)
    out = []
    for d in diffs:
        reason = why_excluded(d, file_filter)
        if not reason:
            if d["is_deleted"]:
                reason = "deleted"
            elif limit > 0 and count_tokens(d["diff"]) > limit:
                reason = "too_large"
        out.append((d, reason))
    return out


def diffs_churn(diffs):
    changed = [d["insertions"] + d["deletions"] for d in diffs]
    return sum(changed), max(changed, default=0)


def grouping_plan(tpl, file_count, total_changed):
    """Template.GroupingPlan -> "llm" | "bundle_all" | "per_file"."""
    min_files = tpl.get("GROUPING_MIN_FILES", 0)
    bundle = tpl.get("GROUPING_BUNDLE_LINE_THRESHOLD", 0)
    if min_files <= 0 or file_count >= min_files:
        return "llm"
    if bundle > 0 and total_changed < bundle:
        return "bundle_all"
    return "per_file"


def plan_required(tpl, file_count, total_changed, max_file_changed):
    line = tpl.get("PLAN_MODE_LINE_THRESHOLD", 0)
    group = tpl.get("PLAN_MODE_GROUP_LINE_THRESHOLD", 0)
    if line <= 0:
        return True
    if max_file_changed >= line:
        return True
    return file_count >= 2 and group > 0 and total_changed >= group


def format_diff_entry(d):
    from .diffs import effective_path
    status = ("ADDED" if d["is_new"] else "DELETED" if d["is_deleted"]
              else "RENAMED" if d["is_renamed"] else "MODIFIED")
    return f"{status}   {effective_path(d)} (+{d['insertions']}/-{d['deletions']})"


def build_file_list(diffs):
    return "".join(f"[{i}] {format_diff_entry(d)}\n" for i, d in enumerate(diffs))


def strip_code_fences(content):
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        if len(lines) >= 2:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines)
    return content


# -- groups: {"label": str, "diffs": [diff, ...]} -------------------------------

def single_file_groups(diffs):
    return [{"label": d["new_path"], "diffs": [d]} for d in diffs]


def enforce_max_files_per_group(groups):
    out = []
    for g in groups:
        if len(g["diffs"]) <= MAX_FILES_PER_GROUP:
            out.append(g)
            continue
        for i in range(0, len(g["diffs"]), MAX_FILES_PER_GROUP):
            out.append({"label": g["label"], "diffs": g["diffs"][i:i + MAX_FILES_PER_GROUP]})
    return out


def enforce_group_token_budget(groups, token_limit):
    if token_limit <= 0:
        return groups
    out = []
    for g in groups:
        if sum(count_tokens(d["diff"]) for d in g["diffs"]) <= token_limit:
            out.append(g)
            continue
        for d in g["diffs"]:
            out.append({"label": f"{g['label']} (split: {d['new_path']})", "diffs": [d]})
    return out


def parse_grouping_response(groups_answer, diffs):
    """parseGroupingResponse over the grouping agent's answer: its groups list
    ([{label, files: [index]}]). Unknown and repeated indices are skipped; a
    file no group names gets a group of its own; groups are capped at ten."""
    seen = [False] * len(diffs)
    groups = []
    for g in groups_answer:
        picked = []
        for idx in g.get("files") or []:
            if not isinstance(idx, int) or isinstance(idx, bool) or idx < 0 or idx >= len(diffs):
                continue
            if seen[idx]:
                continue
            seen[idx] = True
            picked.append(diffs[idx])
        if picked:
            groups.append({"label": str(g.get("label") or ""), "diffs": picked})
    for i, d in enumerate(diffs):
        if not seen[i]:
            groups.append({"label": d["new_path"], "diffs": [d]})
    return enforce_max_files_per_group(groups)


def group_without_llm(diffs, strategy, token_limit):
    groups = single_file_groups(diffs)
    if strategy == "bundle_all":
        groups = enforce_max_files_per_group([{"label": SMALL_CHANGE_SET_LABEL, "diffs": diffs}])
        groups = enforce_group_token_budget(groups, token_limit)
    return groups


def file_group_key(diffs):
    if len(diffs) == 1:
        return diffs[0]["new_path"]
    return ",".join(sorted(d["new_path"] for d in diffs))


def build_concatenated_diffs(diffs):
    return "\n\n".join(f'<file path="{d["new_path"]}">\n{d["diff"]}\n</file>' for d in diffs)


def build_change_files_except_group(all_diffs, group_diffs):
    exclude = set()
    for d in group_diffs:
        exclude.update((d["new_path"], d["old_path"]))
    return "\n".join(format_diff_entry(d) for d in all_diffs
                     if not d["is_binary"] and d["new_path"] not in exclude
                     and d["old_path"] not in exclude)
