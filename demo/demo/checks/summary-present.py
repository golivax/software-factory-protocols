#!/usr/bin/env python3
"""Settle the claim that the `summarize` agent produced a usable summary.

Check ABI (the real engine's): `<check> <evidence.json>`, ground truth in `$CHECK_CTX`
-> one JSON object `{"check","pass","feedback"}` on stdout, ALWAYS exit 0.

Self-contained: it settles two CHECKABLE claims from the agent's OWN evidence —
`saw_token` is present (the input round-tripped) and `summary` is non-empty. It
deliberately does NOT judge the summary's CONTENT — that is a judgment, and checks
settle claims, never adjudicate judgments.
"""
import json
import sys


def emit(ok, feedback):
    print(json.dumps({"check": "summary-present", "pass": bool(ok), "feedback": feedback}))
    return 0


def main():
    try:
        with open(sys.argv[1]) as f:
            ev = json.load(f)
    except (OSError, ValueError, IndexError) as exc:
        return emit(False, f"no readable evidence artifact: {exc}")
    if not isinstance(ev, dict):
        return emit(False, "evidence is not a JSON object")
    token = ev.get("saw_token")
    if not isinstance(token, str) or not token.strip():
        return emit(False, "evidence has no `saw_token` (the `facts` input did not round-trip)")
    summary = ev.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return emit(False, "evidence carries an empty `summary`")
    return emit(True, f"summary present ({len(summary)} chars); saw_token={token!r}")


if __name__ == "__main__":
    raise SystemExit(main())
