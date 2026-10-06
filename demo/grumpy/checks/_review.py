"""The review in grumpy's evidence, read from gh-aw's staged items.

Shared by the checks (not a check itself). The engine has already validated the
evidence against review.evidence.schema.json, so the types, required fields and
counts hold here; this only reads them.
"""


def as_int(v):
    return int(v) if isinstance(v, str) and v.isdigit() else v


def comments(ev):
    """The staged review comments, each {path, line, side, start_line?, body}."""
    out = []
    for it in ev.get("staged") or []:
        if it.get("type") != "create_pull_request_review_comment":
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
        if it.get("type") == "submit_pull_request_review":
            return {"event": it["event"], "body": it.get("body") or ""}
    return {"event": "COMMENT", "body": ""}
