"""The review in grumpy's evidence, read from gh-aw's staged items.

Shared by the checks (not a check itself). The engine has already validated the
evidence against review.evidence.schema.json: every item has the same fields
(null where its type has none), its type is one the workflow allows, and `side`
/ `event` are in their enums. `form_errors` settles what that schema cannot say:
each type's required fields and the workflow's maxes. The checks call it before
reading the review.
"""
import re

MAX_COMMENTS = 5        # the workflow's `create-pull-request-review-comment: max: 5`
MAX_VERDICTS = 1        # the workflow's `submit-pull-request-review: max: 1`
MAX_BODY = 65536
LINE_RE = re.compile(r"^[1-9][0-9]*$")
COMMENT, VERDICT = "create_pull_request_review_comment", "submit_pull_request_review"


def _is_line(v):
    return (isinstance(v, int) and not isinstance(v, bool) and v >= 1) or \
        (isinstance(v, str) and bool(LINE_RE.match(v)))


def form_errors(ev):
    """Why the staged review is malformed, one message per problem ([] if not)."""
    errors, staged = [], ev.get("staged") or []
    comments = [it for it in staged if it.get("type") == COMMENT]
    verdicts = [it for it in staged if it.get("type") == VERDICT]
    if len(comments) > MAX_COMMENTS:
        errors.append(f"{len(comments)} review comments (max {MAX_COMMENTS})")
    if len(verdicts) > MAX_VERDICTS:
        errors.append(f"{len(verdicts)} review submissions (max {MAX_VERDICTS})")
    for i, it in enumerate(comments):
        if not isinstance(it.get("path"), str) or not it["path"]:
            errors.append(f"comment {i}: no path")
        if not _is_line(it.get("line")):
            errors.append(f"comment {i}: line {it.get('line')!r} is not a line number")
        if it.get("start_line") is not None and not _is_line(it["start_line"]):
            errors.append(f"comment {i}: start_line {it['start_line']!r} is not a line number")
        if not isinstance(it.get("body"), str) or not it["body"] or len(it["body"]) > MAX_BODY:
            errors.append(f"comment {i}: body empty or longer than {MAX_BODY}")
    for it in verdicts:
        if it.get("event") is None:
            errors.append("the review submission has no event")
        if isinstance(it.get("body"), str) and len(it["body"]) > MAX_BODY:
            errors.append(f"the review submission's body is longer than {MAX_BODY}")
    return errors


def as_int(v):
    return int(v) if isinstance(v, str) and v.isdigit() else v


def comments(ev):
    """The staged review comments, each {path, line, side, start_line?, body}."""
    out = []
    for it in ev.get("staged") or []:
        if it.get("type") != COMMENT:
            continue
        c = {"path": it["path"], "line": as_int(it["line"]),
             "side": it.get("side") or "RIGHT", "body": it["body"]}
        if it.get("start_line"):
            c["start_line"] = as_int(it["start_line"])
        out.append(c)
    return out


def verdict(ev):
    """The staged review submission {event, body}; COMMENT with no body if none."""
    for it in ev.get("staged") or []:
        if it.get("type") == VERDICT:
            return {"event": it["event"], "body": it.get("body") or ""}
    return {"event": "COMMENT", "body": ""}
