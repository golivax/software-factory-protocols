#!/usr/bin/env python3
"""duplicate-code-remover `file-issues`: a dispatched code node (its own
microVM). After detect's checks pass, it files one issue per duplication pattern
(dedup by a fingerprint marker in the body), then comments `/impl-feature-auto`
on each so the auto-fixer picks it up.

Reads detect's evidence at $SF_INPUTS_DIR/evidence.json and its cap from the
node's `params.max_patterns` (protocol_context.params, default 3). `gh` reaches
the forge through gh2gl with this job's own token (GH_HOST / GH_ENTERPRISE_TOKEN,
set by the code lane), scoped by `issues: write`. Writes {conclusion, summary} to
$SF_EVIDENCE_OUT.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

_SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
_WS = re.compile(r"\s+")


def _collapse(s):
    return _WS.sub(" ", s or "").strip()


def fingerprint(pattern):
    parts = sorted(
        f"{loc.get('path','')}::{_collapse(loc.get('existing_code',''))}"
        for loc in (pattern.get("locations", []) or [])
        if isinstance(loc, dict)
    )
    h = hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()
    return f"dup-fp:{h}"


def comment_body():
    return ("/impl-feature-auto\n\n"
            "_Filed by duplicate-code-remover. Please remove this duplication "
            "(extract the shared logic; keep behaviour identical)._")


def issue_title(pattern):
    return f"[duplicate-code] {pattern.get('name','duplication')}"


def issue_body(pattern, fp):
    lines = [f"# 🔍 Duplicate code: {pattern.get('name','')}", ""]
    lines.append(f"**Severity:** {pattern.get('severity','?')}")
    lines.append("")
    lines.append(pattern.get("rationale", ""))
    lines.append("")
    lines.append("## Locations")
    for loc in pattern.get("locations", []) or []:
        if not isinstance(loc, dict):
            continue
        lines.append(f"- `{loc.get('path')}` (lines {loc.get('start_line')}–{loc.get('end_line')})")
        lines.append("")
        lines.append("  ```cpp")
        for cl in (loc.get("existing_code", "") or "").split("\n"):
            lines.append("  " + cl)
        lines.append("  ```")
    lines.append("")
    lines.append("## Requested change")
    lines.append("Extract the duplicated logic into a single shared definition and "
                 "update all call sites. Preserve behaviour; add/keep tests.")
    lines.append("")
    lines.append(f"<!-- {fp} -->")
    return "\n".join(lines)


def _existing_fingerprints(repo):
    """Open issues whose body carries a dup-fp marker -> set of markers (dedupe).

    Returns None if the query itself FAILED (non-zero exit or unparsable JSON) so
    the caller can fail safe instead of silently treating a transient failure as
    "no duplicates exist" (which would re-file already-filed issues on the daily
    cron). Returns a set (possibly empty) when the query succeeded.
    """
    r = subprocess.run(
        ["gh", "issue", "list", "--repo", repo, "--state", "open",
         "--search", "dup-fp in:body", "--json", "body", "--limit", "100"],
        text=True, capture_output=True,
    )
    if r.returncode != 0:
        sys.stderr.write(f"[file-issues] list failed: {(r.stderr or '').strip()}\n")
        return None
    found = set()
    if r.stdout.strip():
        try:
            for it in json.loads(r.stdout):
                for m in re.findall(r"dup-fp:[0-9a-f]{40}", it.get("body", "") or ""):
                    found.add(m.split(":", 1)[1])
        except ValueError as e:
            sys.stderr.write(f"[file-issues] list parse failed: {e}\n")
            return None
    return found


def _ensure_labels(repo, labels):
    """Best-effort: make sure each label exists so issue creation doesn't fail on
    a repo that hasn't defined them (portability — a target repo won't have our
    labels). Idempotent via --force (create or update). Non-fatal: _create_issue
    also falls back to creating the issue with no labels if this couldn't run."""
    for name in labels:
        subprocess.run(
            ["gh", "label", "create", name, "--repo", repo, "--force",
             "--color", "ededed", "--description", "duplicate-code-remover"],
            text=True, capture_output=True,
        )


def _create_issue(repo, title, body, labels):
    def _run(extra):
        return subprocess.run(
            ["gh", "issue", "create", "--repo", repo, "--title", title,
             "--body", body, *extra],
            text=True, capture_output=True,
        )
    r = _run(["--label", ",".join(labels)] if labels else [])
    if r.returncode != 0:
        # Most likely the labels don't exist / can't be applied. Retry WITHOUT
        # labels so the issue (and its /impl-feature-auto trigger) still lands.
        sys.stderr.write(f"[file-issues] create with labels failed ({r.stderr.strip()}); retrying without labels\n")
        r = _run([])
        if r.returncode != 0:
            sys.stderr.write(f"[file-issues] create failed: {r.stderr.strip()}\n")
            return ""
    # gh prints the issue URL; extract the trailing number
    m = re.search(r"/issues/(\d+)", r.stdout.strip())
    return m.group(1) if m else ""


def _post_comment(repo, number, body):
    r = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{number}/comments", "-f", f"body={body}"],
        text=True, capture_output=True,
    )
    if r.returncode != 0:
        sys.stderr.write(f"[file-issues] comment failed: {r.stderr.strip()}\n")


def main():
    try:
        conclusion, summary = _main()
    except Exception as e:  # a malformed pattern that slipped past the checks
        conclusion, summary = "failure", f"file-issues error: {e}"
    with open(os.environ["SF_EVIDENCE_OUT"], "w") as fh:
        json.dump({"conclusion": conclusion, "summary": summary}, fh)
    print(summary)


def _main():
    try:
        with open(os.path.join(os.environ["SF_INPUTS_DIR"], "evidence.json")) as fh:
            ev = json.load(fh)
    except (OSError, ValueError):
        ev = {}
    with open(os.path.join(os.environ["SF_CONTROL_DIR"], "protocol_context.json")) as fh:
        ctx = json.load(fh)
    patterns = [p for p in (ev.get("patterns") or []) if isinstance(p, dict)]
    if not patterns:
        # a clean scan of a duplication-free repo is a success
        return "success", "No duplication patterns to file."
    patterns.sort(key=lambda p: _SEV_ORDER.get(p.get("severity"), 9))
    try:
        cap = int((ctx.get("params") or {}).get("max_patterns", 3))
    except (TypeError, ValueError):
        cap = 3
    patterns = patterns[:cap]
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    labels = ["code-quality", "automated-analysis"]
    seen = _existing_fingerprints(repo)
    if seen is None:
        # the dedupe query failed: file nothing rather than risk re-filing issues
        # this cron already filed
        return "failure", "dedupe query failed; skipped issue creation to avoid duplicates"
    _ensure_labels(repo, labels)
    created, skipped = [], 0
    for p in patterns:
        fp = fingerprint(p)
        if fp.split(":", 1)[1] in seen:
            skipped += 1
            continue
        num = _create_issue(repo, issue_title(p), issue_body(p, fp), labels)
        if num:
            _post_comment(repo, num, comment_body())
            created.append(num)
    summary = f"Filed {len(created)} issue(s) (#{', #'.join(created) or '—'}); {skipped} deduped."
    return ("success" if created or skipped else "failure"), summary


if __name__ == "__main__":
    main()
