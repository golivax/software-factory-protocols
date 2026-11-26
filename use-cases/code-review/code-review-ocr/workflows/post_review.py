#!/usr/bin/env python3
"""`post`: publish the review on the MR, as upstream's GitHub Action does.

Upstream: the CLI's output pass (emitRunResult: ResolveLineNumbers over every
comment) and scripts/github-actions/post-review-comments.js with the Action's
defaults: the summary is one sticky issue comment (found by its marker and
edited in place; created before the review so it sits above it), inline
comments go out as `COMMENT` reviews of at most 50, sorted by path and line,
pinned to the reviewed commit; a batch the forge refuses is retried comment by
comment; whatever has no line, or could not be posted, is rendered in the
summary. A review with no findings posts only the summary.

Reads every group's leg (inputs/groups.json, the `from_fork` rows of `review`),
the selection and the partition, and counts the run's coverage as upstream's
manifest does. A review whose files all failed, or that failed for anything but
a budget, is one `ocr review` exits nonzero on: the Action then posts nothing
and fails the job, and this node posts nothing and concludes `failure`.
Otherwise it posts and concludes `success`, findings or not. Every
agent-derived string reaches `gh` only on stdin.

Safe to retry, as upstream's poster: every inline comment carries an id made of
the run's tag (`select`'s `run`) and the finding, and an attempt skips the ids
the MR's review comments already carry (getPostedCommentIds); the summary is
edited in place.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ocr import context as C  # noqa: E402
from ocr import diffs as D  # noqa: E402
from ocr import publish as P  # noqa: E402


def gh(method, path, body=None, pr=None):
    """`gh api`; `pr` names the MR to gh2forge (X-SF-Pr-Iid), since on GitLab an
    issue and an MR can share a number. The body goes on stdin, never argv."""
    argv = ["gh", "api", "-X", method, path]
    if pr is not None:
        argv += ["-H", f"X-SF-Pr-Iid: {pr}"]
    if body is not None:
        argv += ["--input", "-"]
    r = subprocess.run(argv, input=json.dumps(body) if body is not None else None,
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or f"gh exited {r.returncode}").strip())
    out = r.stdout.strip()
    return json.loads(out) if out else None


class Forge:
    def __init__(self, repo, pr):
        self.repo, self.pr = repo, pr

    def find_summary(self):
        page = 1
        while True:
            comments = gh("GET", f"repos/{self.repo}/issues/{self.pr}/comments?per_page=100&page={page}",
                          pr=self.pr) or []
            for c in comments:
                if P.SUMMARY_MARKER in (c.get("body") or ""):
                    return c
            if len(comments) < 100:
                return None
            page += 1

    def upsert_summary(self, body, existing=None):
        """Edit the sticky summary in place, else post one. A summary the forge
        will not list or edit (a comment it cannot place answers 404) is posted
        anew rather than lost."""
        if existing is None:
            try:
                existing = self.find_summary()
            except RuntimeError as e:
                print(f"[ocr] could not list the MR's comments ({e}); posting a new summary")
        if existing and existing.get("id"):
            try:
                return gh("PATCH", f"repos/{self.repo}/issues/comments/{existing['id']}", {"body": body},
                          pr=self.pr)
            except RuntimeError as e:
                print(f"[ocr] could not edit summary {existing['id']} ({e}); posting a new one")
        return gh("POST", f"repos/{self.repo}/issues/{self.pr}/comments", {"body": body}, pr=self.pr)

    def review(self, commit, body, comments):
        return gh("POST", f"repos/{self.repo}/pulls/{self.pr}/reviews",
                  {"commit_id": commit, "body": body, "event": "COMMENT", "comments": comments}, pr=self.pr)

    def review_comment(self, commit, rc):
        return gh("POST", f"repos/{self.repo}/pulls/{self.pr}/comments", {**rc, "commit_id": commit}, pr=self.pr)

    def posted_ids(self):
        """The comment ids (`<!-- ocr-… -->`) the MR's review comments carry:
        getPostedCommentIds, what an earlier attempt already posted."""
        ids, page = set(), 1
        while True:
            got = gh("GET", f"repos/{self.repo}/pulls/{self.pr}/comments?per_page=100&page={page}",
                     pr=self.pr) or []
            for c in got:
                ids.update(COMMENT_ID_RE.findall(c.get("body") or ""))
            if len(got) < 100:
                return ids
            page += 1


COMMENT_ID_RE = re.compile(r"<!-- (ocr-[A-Za-z0-9-]+) -->")


def comment_id(run_tag, c):
    """A comment's id, the same on every attempt of this run's `post`."""
    key = json.dumps([c.get("path"), c.get("start_line"), c.get("end_line"), c.get("content")])
    return f"ocr-{run_tag}-{hashlib.sha256(key.encode()).hexdigest()[:16]}"


def gather(select, partition, rows):
    """Every group's comments and warnings, and the run's coverage as upstream's
    manifest counts it: the selected files, and the failed ones with their class
    (a group whose leg failed: `provider`, as an errored subtask; a group's own
    `failure`; a group past the fork's leg cap: `budget`)."""
    comments, warnings, failed = [], list(partition.get("warnings") or []), {}
    for w in warnings:
        if w.get("type") == "group_cap":
            failed[w["file"]] = "budget"
    files_of = {g["id"]: g["files"] for g in partition.get("groups") or []}
    for row in rows:
        ev = row.get("evidence") or {}
        if row.get("state") != "done" or not ev:
            for f in files_of.get(row.get("key"), []):
                failed[f] = "provider"
            warnings.append({"type": "subtask_error", "file": row.get("key") or "",
                             "message": "provider or subtask request failed"})
            continue
        comments += ev.get("comments") or []
        warnings += ev.get("warnings") or []
        if ev.get("failure"):
            for f in ev.get("files") or []:
                failed[f] = ev["failure"].get("class") or "unknown"
    selected = select.get("selected") or []
    failed = {f: c for f, c in failed.items() if f in selected}
    return comments, warnings, selected, failed


def terminal_state(selected, failed):
    """session.computeTerminal."""
    if not selected:
        return "skipped"
    if not failed:
        return "complete"
    return "failed" if len(failed) == len(selected) else "partial"


def manifest_message(state, findings, failed, selected):
    """output.go manifestMessage."""
    if state == "complete":
        return f"Review complete: {findings} finding(s) across {selected} selected item(s)."
    if state == "partial":
        return f"Review partially complete: {findings} finding(s); {failed} of {selected} selected item(s) failed."
    if state == "failed":
        return f"Review failed: {findings} finding(s); {failed} of {selected} selected item(s) failed."
    return "Review skipped: no items were selected."


def publish(forge, commit, run_tag, review_tag, summary_tag, comments, warnings):
    wrap = lambda content: f"{P.SUMMARY_MARKER}\n{summary_tag}\n{content}"  # noqa: E731
    without_line = [(c, P.NO_LINE_REASON) for c in comments if not P.has_line(c)]
    inline = [(c, comment_id(run_tag, c)) for c in comments if P.has_line(c)]
    inline = [(c, P.review_comment(c, P.format_comment(c, cid)), cid) for c, cid in inline]
    try:
        anchor = forge.upsert_summary(wrap(P.pre_review_summary(len(comments), without_line, warnings)))
    except RuntimeError as e:
        print(f"[ocr] could not anchor the summary ({e}); it is written after the review")
        anchor = None
    try:
        already = forge.posted_ids()
    except RuntimeError as e:
        print(f"[ocr] could not list the MR's review comments ({e}); posting every comment")
        already = set()

    posted, failed = 0, []
    batch = P.sort_deterministically(inline)
    for i in range(0, len(batch), P.BATCH_SIZE):
        chunk = batch[i:i + P.BATCH_SIZE]
        done = [item for item in chunk if item[2] in already]
        if done:
            # an earlier attempt of this run posted these: reconciled, not reposted
            print(f"[ocr] {len(done)} comment(s) of this run already on the MR")
            posted += len(done)
            chunk = [item for item in chunk if item[2] not in already]
            if not chunk:
                continue
        try:
            forge.review(commit, review_tag, [rc for _, rc, _ in chunk])
            posted += len(chunk)
            continue
        except RuntimeError as e:
            print(f"[ocr] review batch of {len(chunk)} refused: {e}; posting one by one")
        for c, rc, _ in chunk:
            try:
                forge.review_comment(commit, rc)
                posted += 1
            except RuntimeError as e:
                failed.append((c, str(e)))
    forge.upsert_summary(wrap(P.summary(len(comments), posted, without_line, failed, warnings)), anchor)
    return posted, failed


def main():
    select = C.read_input("select") or {}
    partition = C.read_input("partition") or {}
    rows = C.read_input("groups") or []
    pr = C.pr_json()
    ctx = C.protocol_context()
    number = pr.get("number") or ctx.get("pr")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not number or not repo:
        raise C.Failure("the run is about no MR: nothing to post on")
    forge = Forge(repo, number)
    run_tag, review_tag, summary_tag = P.run_tags(select.get("run") or "0", "1")

    comments, warnings, selected, failed = gather(select, partition, rows)
    state = terminal_state(selected, failed)
    message = manifest_message(state, len(comments), len(failed), len(selected))
    print(f"[ocr] {message}")
    if state == "failed" or (state == "partial" and any(c != "budget" for c in failed.values())):
        # reviewResultError: `ocr review` exits nonzero, and the Action fails the
        # job without posting anything.
        prefix = "review incomplete" if state == "partial" else "review failed"
        text = f"{prefix}: {len(failed)} of {len(selected)} selected item(s) failed"
        C.write_evidence({"conclusion": "failure", "summary": f"{text}; nothing posted. {message}",
                          "comments": len(comments)})
        return
    # warningsForOutput: with a manifest, a failed subtask is told by the coverage.
    warnings = [w for w in warnings if w.get("type") != "subtask_error"]

    sel = C.Selection(select)
    D.read_new_file_contents(sel.kept, os.environ.get("GITHUB_WORKSPACE", ""), ref="HEAD")
    comments = D.resolve_line_numbers(comments, sel.kept)

    if not comments:
        forge.upsert_summary(P.no_comments(message, warnings))
        C.write_evidence({"conclusion": "success", "summary": message, "comments": 0})
        return
    posted, failed_posts = publish(forge, pr.get("head_sha") or "", run_tag, review_tag, summary_tag,
                                   comments, warnings)
    summary = (f"{message} {posted} posted inline, "
               f"{sum(1 for c in comments if not P.has_line(c))} in the summary, {len(failed_posts)} failed to post.")
    print(f"[ocr] {summary}")
    C.write_evidence({"conclusion": "success", "summary": summary, "comments": len(comments)})


if __name__ == "__main__":
    C.run(main)
