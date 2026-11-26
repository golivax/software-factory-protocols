"""How upstream's GitHub Action renders a review: the inline comment bodies and
the summary comment.

Ported from scripts/github-actions/post-review-comments.js (formatComment,
formatCommentMarkdown, buildBadge/buildBadgeImage, buildSummaryBody,
buildPreReviewSummaryBody, formatWarnings, fencedBlock), with the Action's
defaults: a sticky summary, no incremental mode, no severity or category
routing, batches of 50 inline comments.
"""
import re
import urllib.parse

SUMMARY_MARKER = "<!-- ocr-summary -->"
NO_LINE_REASON = "No line information available"
BATCH_SIZE = 50
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
SEVERITY_BADGE_COLOR = {"critical": "darkred", "high": "red", "medium": "orange", "low": "green"}
CATEGORY_BADGE_COLOR = "blue"
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def run_tags(run_id, attempt):
    tag = f"{run_id}-{attempt}"
    return tag, f"<!-- ocr-review-run:{tag} -->", f"<!-- ocr-summary-run:{tag} -->"


def safe_fence(text):
    ticks = max((len(m) for m in re.findall(r"`+", text or "")), default=0)
    return "`" * max(3, ticks + 1)


def fenced_block(content, language=""):
    text = str(content or "")
    fence = safe_fence(text)
    block = fence + language + "\n" + text
    if not text.endswith("\n"):
        block += "\n"
    return block + fence


def _sanitize(value):
    return _CONTROL.sub("", "" if value is None else str(value))


def build_badge(c):
    cat, sev = _sanitize(c.get("category")), _sanitize(c.get("severity"))
    if cat and sev:
        return f"[{cat} · {sev}]"
    return f"[{cat}]" if cat else f"[{sev}]" if sev else ""


def _shields(value):
    # encodeURIComponent keeps A-Z a-z 0-9 - _ . ! ~ * ' ( )
    return urllib.parse.quote(value.replace("-", "--").replace("_", "__"), safe="!*'()")


def build_badge_image(c):
    text = build_badge(c)
    if not text:
        return ""
    cat = _sanitize(c.get("category")).strip().lower()
    sev = _sanitize(c.get("severity")).strip().lower()
    color = SEVERITY_BADGE_COLOR.get(sev, CATEGORY_BADGE_COLOR)
    alt = text[1:-1].replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    label = f"{_shields(cat)}-{_shields(sev)}" if cat and sev else _shields(cat or sev)
    return f"![{alt}](https://img.shields.io/badge/{label}-{color})"


def format_comment(c, cid=None):
    body = f"<!-- {cid} -->\n" if cid else ""
    badge = build_badge_image(c)
    if badge:
        body += badge + "\n"
    body += c.get("content") or ""
    if c.get("suggestion_code") and c.get("existing_code"):
        body += "\n\n**Suggestion:**\n" + fenced_block(c["suggestion_code"], "suggestion")
    return body


def format_comment_markdown(c, error=None):
    md = ""
    badge = build_badge_image(c)
    if badge:
        md += badge + "\n"
    md += f"### 📄 `{c.get('path')}`"
    if c.get("start_line") and c.get("end_line"):
        md += f" (L{c['start_line']}-L{c['end_line']})"
    md += "\n\n"
    if error:
        md += f"⚠️ GitHub could not post this as an inline comment: {error}\n\n"
    md += c.get("content") or ""
    if c.get("suggestion_code") and c.get("existing_code"):
        md += "\n\n<details><summary>💡 Suggested Change</summary>\n\n"
        md += "**Before:**\n" + fenced_block(c["existing_code"]) + "\n\n"
        md += "**After:**\n" + fenced_block(c["suggestion_code"]) + "\n\n"
        md += "</details>"
    return md


def review_comment(c, body):
    """The createReview entry: RIGHT side; a range when the lines differ."""
    rc = {"path": c["path"], "body": body}
    start, end = c.get("start_line") or 0, c.get("end_line") or 0
    if start >= 1 and end >= 1 and start != end:
        rc.update(start_line=start, line=end, start_side="RIGHT", side="RIGHT")
    elif end >= 1:
        rc.update(line=end, side="RIGHT")
    elif start >= 1:
        rc.update(line=start, side="RIGHT")
    return rc


def has_line(c):
    return (c.get("start_line") or 0) >= 1 or (c.get("end_line") or 0) >= 1


def sort_deterministically(items):
    return sorted(items, key=lambda it: (it[0].get("path") or "", it[0].get("start_line") or 0,
                                         it[0].get("end_line") or 0))


def format_warning_entry(w):
    if isinstance(w, str):
        return w
    if not isinstance(w, dict):
        return str(w)
    prefix = " ".join(p for p in ((f"`{w['file']}`" if w.get("file") else ""),
                                  (f"(`{w['type']}`)" if w.get("type") else "")) if p)
    msg = str(w.get("message") or "")
    if prefix and msg:
        return f"{prefix}: {msg}"
    return msg or prefix


def format_warnings(warnings):
    if not warnings:
        return ""
    return "\n\n---\n\n⚠️ **Warnings:**" + "".join(f"\n- {format_warning_entry(w)}" for w in warnings)


def format_summary_comments(items):
    return "".join("\n\n---\n\n" + format_comment_markdown(c, reason) for c, reason in items)


def pre_review_summary(total, without_line, warnings):
    body = f"🔍 **OpenCodeReview** found **{total}** issue(s) in this PR."
    if total > 0:
        body += "\n- ⏳ _Posting review comments…_"
    if warnings:
        body += f"\n\n⚠️ {len(warnings)} warning(s) occurred during review."
    body += format_summary_comments(without_line)
    body += format_warnings(warnings)
    return body


def summary(total, inline, without_line, failed, warnings):
    body = f"🔍 **OpenCodeReview** found **{total}** issue(s) in this PR."
    if total > 0:
        body += f"\n- ✅ Successfully posted inline: {inline} comment(s)"
        if without_line:
            body += f"\n- 📝 In summary (no line info): {len(without_line)} comment(s)"
        if failed:
            body += f"\n- ❌ Failed to post inline: {len(failed)} comment(s)"
    if warnings:
        body += f"\n\n⚠️ {len(warnings)} warning(s) occurred during review."
    body += format_summary_comments(without_line)
    body += format_summary_comments(failed)
    body += format_warnings(warnings)
    return body


def no_comments(message, warnings):
    """The summary of a review with no findings; `message` is the result's
    (a range review always has one: its manifest's)."""
    block = format_warnings(warnings)
    icon = "⚠️" if block else "✅"
    return f"{SUMMARY_MARKER}\n{icon} **OpenCodeReview**: {message}{block}"
