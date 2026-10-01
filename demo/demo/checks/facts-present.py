#!/usr/bin/env python3
"""Settle the claim that the `facts` code node actually ran and reported facts.

Check ABI (the real engine's): `<check> <evidence.json>`, ground truth in `$CHECK_CTX`
-> one JSON object `{"check","pass","feedback"}` on stdout, ALWAYS exit 0 (a
non-zero exit is reserved for a genuine runner error, not a failed claim).

Self-contained: it settles claims from the node's OWN evidence — `ok: true` and a
non-empty `examined` trace. An absent/garbled artifact is exactly the failure a live
run must surface rather than pass silently.
"""
import json
import sys


def emit(ok, feedback):
    print(json.dumps({"check": "facts-present", "pass": bool(ok), "feedback": feedback}))
    return 0


def main():
    try:
        with open(sys.argv[1]) as f:
            ev = json.load(f)
    except (OSError, ValueError, IndexError) as exc:
        return emit(False, f"no readable evidence artifact: {exc}")
    if not isinstance(ev, dict) or ev.get("ok") is not True:
        return emit(False, "evidence did not report ok:true")
    if not ev.get("examined"):
        return emit(False, "evidence carries no `examined` trace")
    return emit(True, f"facts step ran; examined {len(ev['examined'])} item(s), "
                      f"token={ev.get('token')!r}")


if __name__ == "__main__":
    raise SystemExit(main())
