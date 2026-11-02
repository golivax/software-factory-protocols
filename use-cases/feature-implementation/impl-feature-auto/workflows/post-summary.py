#!/usr/bin/env python3
"""impl-feature-auto `post-summary`: a dispatched code node (its own microVM), the
protocol's last step. After implement's checks pass, it finds the PR gh-aw's
safe outputs opened (by `pr_branch` prefix) and comments a link on the
originating issue.

Reads implement's evidence at $SF_INPUTS_DIR/evidence.json; the issue is
protocol_context.pr. `gh` reaches the forge through gh2forge with this job's own
token (GH_HOST / GH_ENTERPRISE_TOKEN, set by the code lane), scoped by the
workflow's `permissions:`. Writes {conclusion, summary} to $SF_EVIDENCE_OUT:
`failure` when implement produced no branch, or no PR or branch can be found.
"""
import json
import os
import subprocess


def _gh_json(*args):
    r = subprocess.run(["gh", *args], text=True, capture_output=True)
    if r.returncode == 0 and r.stdout.strip():
        try:
            return json.loads(r.stdout)
        except ValueError:
            return None
    return None


def _comment(repo, issue, body):
    if str(issue).isdigit():
        subprocess.run(["gh", "api", f"repos/{repo}/issues/{issue}/comments", "-f", f"body={body}"],
                       text=True, capture_output=True)


def decide(ev, repo, issue):
    pr_branch = (ev.get("pr_branch") or "").strip()
    if not pr_branch:
        # the protocol's whole job is issue -> PR: no branch at all is an objection
        return "failure", "implement produced no pr_branch; no PR to link."
    summary = (ev.get("summary", "") or "").strip()
    note = f"\n\n{summary}" if summary else ""
    # gh-aw's safe outputs suffix the head branch ("-<hash>"): match by PREFIX
    prs = _gh_json("pr", "list", "--repo", repo, "--state", "all",
                   "--json", "number,url,headRefName", "--limit", "40") or []
    match = next((p for p in prs if str(p.get("headRefName", "")).startswith(pr_branch)), None)
    if match:
        _comment(repo, issue, f"🤖 **Feature implemented** — opened PR #{match.get('number')}: "
                              f"{match.get('url')}{note}")
        return "success", f"Linked PR #{match.get('number')} for issue {issue}."
    # A change touching protected paths is routed to a review issue, not an
    # auto-PR, and the branch may be pushed without one: that is a legitimate
    # outcome, not a failure.
    refs = _gh_json("api", f"repos/{repo}/git/matching-refs/heads/{pr_branch}") or []
    branch = next((r.get("ref", "").split("refs/heads/", 1)[-1] for r in refs if r.get("ref")), "")
    if branch:
        _comment(repo, issue, f"🤖 **Feature implemented** — pushed to branch `{branch}` and "
                              "opened for review (changes touching protected paths are routed "
                              f"to a review issue instead of an auto-PR).{note}")
        return "success", f"Implementation pushed to {branch} for issue {issue}; review pending."
    return "failure", f"No PR or branch found for {pr_branch}."


def main():
    try:
        with open(os.path.join(os.environ["SF_INPUTS_DIR"], "evidence.json")) as fh:
            ev = json.load(fh)
    except (OSError, ValueError):
        ev = {}
    with open(os.path.join(os.environ["SF_CONTROL_DIR"], "protocol_context.json")) as fh:
        issue = str(json.load(fh).get("pr", ""))
    conclusion, summary = decide(ev, os.environ.get("GITHUB_REPOSITORY", ""), issue)
    with open(os.environ["SF_EVIDENCE_OUT"], "w") as fh:
        json.dump({"conclusion": conclusion, "summary": summary}, fh)
    print(summary)


if __name__ == "__main__":
    main()
