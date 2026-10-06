#!/usr/bin/env python3
"""Consume the colleague's handed-over work — the step a careless wipe would break.

This is the point of the whole protocol. The first two steps can only ASSERT that
destroying untracked files would be bad. This step depends on those bytes, so if
the worker's cleanup had reached past its own files, this step could not run, and
it says so by failing. That turns "the policy protects you from collateral damage"
from a claim into something the pipeline demonstrates.

How it knows. It holds the handover manifest, which carries each file's exact
contents, and the worker's digests, which were computed against the real tree
AFTER cleanup. Hashing the manifest and comparing gives three distinguishable
outcomes, and only the first is a pass:

    digest present and equal   the file survived intact
    digest absent              the file was deleted
    digest present, different  the file was overwritten or truncated

An inline `code` node's verdict is its EXIT CODE — it takes no `checks`, because
its own exit already is the verdict. So a destroyed handover exits nonzero and the
node goes red.

ABI: <script> <workdir> <instance-key>; inputs at <workdir>/inputs/<as>.json;
one JSON object on stdout.
"""
import hashlib
import json
import os
import sys

inputs_dir = os.path.join(sys.argv[1], "inputs")


def read(name):
    path = os.path.join(inputs_dir, f"{name}.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def done(payload, code):
    print(json.dumps(payload))
    raise SystemExit(code)


handover = read("handover")
worker = read("worker")

files = handover.get("files") or []
if not files:
    done({"conclusion": "failure",
          "summary": "No handover manifest reached this step; there is nothing to assemble."}, 1)

digests = {d.get("path"): d.get("sha256")
           for d in (worker.get("handover_digests") or []) if isinstance(d, dict)}

destroyed, altered, survived = [], [], []
for f in files:
    path = f.get("path")
    expected = hashlib.sha256((f.get("content") or "").encode()).hexdigest()
    seen = digests.get(path)
    if not seen:
        destroyed.append(path)
    elif seen.lower() != expected:
        altered.append(path)
    else:
        survived.append(path)

if destroyed or altered:
    lost = ", ".join(destroyed) or "none"
    changed = ", ".join(altered) or "none"
    done({"conclusion": "failure",
          "destroyed": destroyed, "altered": altered, "survived": survived,
          "summary": ("Cannot assemble the release notes: the colleague's uncommitted work "
                      f"did not survive the previous step. Deleted: {lost}. Altered: {changed}. "
                      "Untracked files have no copy in git, so nothing can restore them.")}, 1)

# Every byte is intact, so the work the colleague left can actually be used.
sections = []
for f in files:
    sections.append(f"## {os.path.basename(f['path'])}\n\n{f['content'].rstrip()}")
assembled = "# Release notes\n\n" + "\n\n".join(sections) + "\n"

done({"conclusion": "success",
      "destroyed": [], "altered": [], "survived": survived,
      "assembled": assembled,
      "summary": (f"Assembled the release notes from {len(survived)} handed-over file(s), "
                  "each byte-identical to what the colleague left behind.")}, 0)
