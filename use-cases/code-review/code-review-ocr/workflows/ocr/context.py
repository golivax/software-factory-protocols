"""What every node of the protocol reads: the run's MR snapshot, its inputs,
and the diff set the `select` node decided on.

Diffs never travel in evidence (an MR's diff can be megabytes): a node re-parses
the snapshot's diff.patch, the bytes every node and check of the run sees, and
keeps the paths `select` recorded. So every node works on the same diffs.
"""
import json
import os
import sys

from . import diffs as D


class Failure(Exception):
    """The node cannot do its work: it exits nonzero and the factory retries."""


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def subject_dir():
    d = os.environ.get("SF_SUBJECT_DIR") or os.path.join(os.environ.get("GITHUB_WORKSPACE", "."), ".sf-subject")
    return d


def pr_json():
    return load_json(os.path.join(subject_dir(), "pr.json"), {}) or {}


def diff_text():
    """The snapshot's diff. A snapshot the factory could not compute (pr.json
    names the MR, no base_sha) is a failure, never an MR that changes nothing."""
    pr = pr_json()
    if pr.get("number") and not pr.get("base_sha"):
        raise Failure(f"the factory could not compute MR {pr['number']}'s diff (pr.json names no base_sha)")
    try:
        with open(os.path.join(subject_dir(), "diff.patch"), encoding="utf-8", errors="surrogateescape") as fh:
            return D.requote_paths(fh.read())
    except OSError:
        return ""


def all_parsed_diffs():
    return D.parse_patch(diff_text())


def by_paths(parsed, paths):
    """The parsed diffs whose effective path is in `paths`, in `paths` order."""
    index = {D.effective_path(d): d for d in parsed}
    return [index[p] for p in paths if p in index]


def inputs_dir():
    return os.environ.get("SF_INPUTS_DIR") or os.path.join(os.environ.get("GITHUB_WORKSPACE", "."), "inputs")


def read_input(name, default=None):
    return load_json(os.path.join(inputs_dir(), f"{name}.json"), default)


def protocol_context():
    ctl = os.environ.get("SF_CONTROL_DIR")
    if ctl:
        return load_json(os.path.join(ctl, "protocol_context.json"), {}) or {}
    raw = os.environ.get("AW_CONTEXT") or "{}"
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def protocol_inputs():
    return protocol_context().get("protocol_inputs") or {}


def write_evidence(doc):
    with open(os.environ["SF_EVIDENCE_OUT"], "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)


def run(main):
    """Run a code node's body: a Failure exits 1 with its reason."""
    try:
        main()
    except Failure as e:
        print(f"[ocr] {e}", file=sys.stderr)
        sys.exit(1)


class Selection:
    """The `select` node's decisions over the snapshot's diffs."""

    def __init__(self, select_evidence):
        ev = select_evidence or {}
        self.evidence = ev
        parsed = all_parsed_diffs()
        self.included = by_paths(parsed, ev.get("included") or [])   # the DiffMap set
        self.kept = by_paths(parsed, ev.get("kept") or [])           # selected + deletions
        self.selected = by_paths(parsed, ev.get("selected") or [])

    def find(self, path):
        """findDiff over the kept set, by new or old path."""
        for d in self.kept:
            if d["new_path"] == path or d["old_path"] == path:
                return d
        return None
