#!/usr/bin/env python3
"""code-review-ocr top `merge`: a dispatched code node (its own microVM) that posts
ONE review on the MR.

Reads $SF_INPUTS_DIR/files.json — the `from_fork` rows over the `review` file
legs, one per file, whose `evidence` is that file's `reduce` result
{conclusion, summary, survivors}. Collects every file's survivors, de-duplicates
them across files by (path, side, line, existing_code), and posts them as inline
comments in one review: REQUEST_CHANGES when anything survived, else APPROVE
(retried once as COMMENT where the repo forbids self-approval).

The forge is reached through gh2forge ($GITHUB_API_URL) with this job's own token
(`pull-requests: write`); the MR is protocol_context.pr. Writes
{conclusion, summary, ...} to $SF_EVIDENCE_OUT: REQUEST_CHANGES is `failure` (an
objection: the run goes red and continues), APPROVE is `success`. A review that
cannot be posted at all exits nonzero (the node retries).
"""
import json
import os
import sys
import urllib.error
import urllib.request

REQ_BODY = ("\U0001f9fe OCR review — {n} issue(s) across {nfiles} file(s) survived "
            "per-finding filtering. See the inline comments.")
OK_BODY = ("\U0001f9fe OCR review: every candidate finding was filtered out; nothing "
           "survived across all files.")


def dedup(findings):
    seen, out = set(), []
    for f in findings:
        k = (f.get("path"), f.get("side"), f.get("line"), f.get("existing_code"))
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def comments(findings):
    out = []
    for f in findings:
        c = {"path": f.get("path"), "side": f.get("side", "RIGHT"), "line": f.get("line"),
             "body": f.get("comment", "")}
        if f.get("start_line"):
            c.update(start_line=f["start_line"], start_side=c["side"])
        out.append(c)
    return out


def _call(method, path, pr, body=None):
    req = urllib.request.Request(
        f"{os.environ['GITHUB_API_URL'].rstrip('/')}/{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Accept": "application/vnd.github+json", "Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}",
                 "X-SF-Pr-Iid": pr})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return json.loads(raw) if raw.strip() else {}


def main():
    with open(os.path.join(os.environ["SF_INPUTS_DIR"], "files.json")) as fh:
        rows = json.load(fh)
    with open(os.path.join(os.environ["SF_CONTROL_DIR"], "protocol_context.json")) as fh:
        ctx = json.load(fh)
    pr, sha = str(ctx.get("pr", "")), ctx.get("sha", "")
    findings = []
    for r in rows:
        if isinstance(r.get("evidence"), dict):
            findings += r["evidence"].get("survivors") or []
    inline = comments(dedup(findings))
    nfiles = len({c["path"] for c in inline})
    event = "REQUEST_CHANGES" if inline else "APPROVE"
    body = REQ_BODY.format(n=len(inline), nfiles=nfiles) if inline else OK_BODY
    repo = os.environ["GITHUB_REPOSITORY"]
    # the commit the run reviewed, never the MR's head now: on an MR that moved
    # since, the forge shows the review as outdated
    review = {"event": event, "body": body, "comments": inline, "commit_id": sha}
    try:
        posted = _call("POST", f"repos/{repo}/pulls/{pr}/reviews", pr, review)
    except urllib.error.HTTPError:
        if event != "APPROVE":
            raise
        sys.stderr.write("[post-review] APPROVE rejected; retrying as COMMENT\n")
        posted = _call("POST", f"repos/{repo}/pulls/{pr}/reviews", pr, {**review, "event": "COMMENT"})
    if inline:
        conclusion, summary = "failure", "OCR review requested changes — resolve the flagged findings."
    else:
        conclusion, summary = "success", "OCR review found nothing to flag after per-finding filtering."
    with open(os.environ["SF_EVIDENCE_OUT"], "w") as fh:
        json.dump({"conclusion": conclusion, "summary": summary, "event": event,
                   "comments": len(inline), "review_id": posted.get("id")}, fh)
    print(summary)


if __name__ == "__main__":
    main()
