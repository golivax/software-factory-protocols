#!/usr/bin/env python3
"""Check: the agent's max claim is settled against the code node's ground truth.

Toy check ABI (this test-drive): `check <evidence.json> <ground_truth.json>`,
prints one `{"check","pass","feedback"}` object and ALWAYS exits 0 — matching the
real engine's contract (non-zero is reserved for a runner error).

It settles the two CHECKABLE claims (`claimed_max_id`, `claimed_max_value`)
against `compute`'s facts. It deliberately does NOT touch `assessment` — that is a
judgment, and checks settle claims, never adjudicate judgments.
"""
import json
import sys


def emit(ok, feedback=""):
    print(json.dumps({"check": "max-claim-correct", "pass": bool(ok), "feedback": feedback}))
    sys.exit(0)


def main():
    try:
        ev = json.load(open(sys.argv[1]))
    except (OSError, ValueError, IndexError) as exc:
        emit(False, f"evidence unreadable/not JSON: {exc}")
    try:
        facts = json.load(open(sys.argv[2]))
    except (OSError, ValueError, IndexError) as exc:
        emit(False, f"ground-truth unreadable: {exc}")

    # shape (a schema-valid check would be separate; fold the essentials here)
    for key, typ in (("claimed_max_id", str), ("claimed_max_value", int)):
        if key not in ev or not isinstance(ev[key], typ) or isinstance(ev[key], bool):
            emit(False, f"evidence missing/ill-typed `{key}`")

    records = facts.get("records")
    if not isinstance(records, list) or not records:
        emit(False, "ground-truth has no records")

    # re-derive the truth ourselves; never trust the agent's arithmetic
    true_max = max(records, key=lambda r: r["value"])
    true_id, true_val = true_max["id"], true_max["value"]

    claimed_id, claimed_val = ev["claimed_max_id"], ev["claimed_max_value"]
    problems = []
    if claimed_id != true_id:
        problems.append(f"claimed_max_id={claimed_id!r} but the max record is {true_id!r}")
    if claimed_val != true_val:
        problems.append(f"claimed_max_value={claimed_val} but the true max value is {true_val}")

    if problems:
        emit(False, "; ".join(problems) + f" (records: {[(r['id'], r['value']) for r in records]})")
    emit(True, f"claim settled: {true_id}={true_val} matches the facts")


if __name__ == "__main__":
    main()
