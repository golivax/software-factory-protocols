"""Generate code-review-ocr/protocol.json: the three review rounds are one shape,
written out (the DSL has no accumulating loop). Edit this, then

    python3 tests/generate/gen_protocol.py > protocol.json

tests/test_generated.py fails when protocol.json and this disagree."""
import json
import sys

TOLERANT = "quorum:0%"   # a leg that failed is tolerated: upstream logs and goes on


def try_fork(fid, leg, join, nxt):
    """A single-leg fork whose join tolerates the leg's failure."""
    return [{"id": fid, "kind": "fork", "branches": [leg], "next": join},
            {"id": join, "kind": "join", "of": fid, "policy": TOLERANT, "next": nxt}]


def review_agent(n, inputs):
    return {"id": f"review-{n}", "kind": "agent", "label": f"Review round {n}",
            "workflow": "review-agent", "evidence": "review.evidence.schema.json",
            "max_iterations": 2, "inputs": inputs}


def round_nodes(n, last):
    nxt_gate = f"round-gate-{n}"
    base = [{"from": "select", "as": "select"}, {"from": "prepare", "as": "prepare"}]
    nodes = []
    if n == 1:
        nodes.append({**review_agent(1, base + [{"from": "plan", "as": "plan"}]), "next": "locate-1"})
    else:
        nodes += try_fork(f"review-{n}-try",
                          review_agent(n, base + [{"from": f"confirm-{n - 1}", "as": "previous"}]),
                          f"review-{n}-join", f"locate-{n}")
    nodes += [
        {"id": f"locate-{n}", "kind": "code", "label": f"Locate round {n}", "workflow": "locate",
         "checkout": True,
         "inputs": base + [{"from": f"review-{n}", "as": "review"}], "next": f"relocate-{n}"},
        {"id": f"relocate-{n}", "kind": "fork", "label": f"Re-locate round {n}",
         "inputs": [{"from": f"locate-{n}", "as": "locate"}],
         "expand": {"hook": "expand-relocations", "as": "relocation", "id_from": "$.id", "max_legs": 256},
         "each": {"kind": "agent", "workflow": "relocate-agent", "evidence": "relocate.evidence.schema.json",
                  "max_iterations": 2, "inputs": [{"from": "select", "as": "select"}]},
         "next": f"relocate-{n}-join"},
        {"id": f"relocate-{n}-join", "kind": "join", "of": f"relocate-{n}", "policy": TOLERANT,
         "next": f"settle-{n}"},
        {"id": f"settle-{n}", "kind": "code", "label": f"Settle round {n}", "workflow": "settle",
         "checkout": True,
         "inputs": base + [{"from": f"locate-{n}", "as": "locate"},
                           {"from_fork": f"relocate-{n}", "as": "relocations"}],
         "next": f"filter-gate-{n}"},
        {"id": f"filter-gate-{n}", "kind": "choice", "on": {"from": f"settle-{n}", "path": "$.filter"},
         "cases": [{"when": True, "next": f"filter-{n}-try"}], "default": f"confirm-{n}"},
    ]
    nodes += try_fork(f"filter-{n}-try",
                      {"id": f"filter-{n}", "kind": "agent", "label": f"Review filter round {n}",
                       "workflow": "filter-agent", "evidence": "filter.evidence.schema.json",
                       "max_iterations": 2,
                       "inputs": base + [{"from": f"settle-{n}", "as": "settle"}]},
                      f"filter-{n}-join", f"confirm-{n}")
    confirm_inputs = [{"from": "select", "as": "select"}, {"from": "prepare", "as": "prepare"},
                      {"from": f"settle-{n}", "as": "settle"},
                      {"from": f"filter-{n}", "as": "filter"}]
    if n > 1:
        confirm_inputs.append({"from": f"confirm-{n - 1}", "as": "previous"})
    nodes.append({"id": f"confirm-{n}", "kind": "code", "label": f"Confirm round {n}",
                  "workflow": "confirm", "params": {"round": n}, "inputs": confirm_inputs,
                  "next": "collect" if last else nxt_gate})
    if not last:
        nodes.append({"id": nxt_gate, "kind": "choice", "on": {"from": f"confirm-{n}", "path": "$.continue"},
                      "cases": [{"when": True, "next": f"review-{n + 1}-try"}],
                      "default": "collect"})
    return nodes


group_states = [
    {"id": "prepare", "kind": "code", "label": "Prepare", "workflow": "prepare", "checkout": True,
     "inputs": [{"from": "select", "as": "select"}], "next": "plan-gate"},
    {"id": "plan-gate", "kind": "choice", "on": {"from": "prepare", "path": "$.plan"},
     "cases": [{"when": True, "next": "plan-try"}], "default": "over-budget-gate"},
    *try_fork("plan-try",
              {"id": "plan", "kind": "agent", "label": "Plan", "workflow": "plan-agent",
               "evidence": "plan.evidence.schema.json", "max_iterations": 2,
               "inputs": [{"from": "select", "as": "select"}, {"from": "prepare", "as": "prepare"}]},
              "plan-join", "review-1"),
    {"id": "over-budget-gate", "kind": "choice", "on": {"from": "prepare", "path": "$.over_budget"},
     "cases": [{"when": True, "next": "collect"}], "default": "review-1"},
]
for n in (1, 2, 3):
    group_states += round_nodes(n, last=(n == 3))
group_states.append(
    {"id": "collect", "kind": "code", "label": "Collect", "workflow": "collect",
     "inputs": [{"from": "prepare", "as": "prepare"}] +
               [{"from": f"confirm-{n}", "as": f"round-{n}"} for n in (1, 2, 3)]})

protocol = {
    "name": "code-review-ocr",
    "_note": "Alibaba OpenCodeReview (alibaba/open-code-review, `ocr review`) as a protocol: see README.md.",
    "min_engine_version": "21.1.0",
    "max_depth": 6,
    "inputs": {
        "type": "object",
        "properties": {
            "effort": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium",
                       "description": "`ocr review --effort`: review rounds per group (1, 2, 3)."},
            "language": {"type": "string", "default": "English",
                         "description": "The language OCR reviews in (`ocr config set language`)."},
            "background": {"type": "string", "default": "",
                           "description": "`ocr review --background`: the requirement background."},
            "rule": {"type": "string", "default": "",
                     "description": "`ocr review --rule`: a custom rule.json, relative to the repository."},
            "no_filter": {"type": "boolean", "default": False,
                          "description": "`ocr review --no-filter`: skip the review filter."}
        }
    },
    "result": {"kind": "comment", "description": "OpenCodeReview's review: inline comments and a summary comment"},
    "triggers": [
        {"on": "pull_request", "actions": ["opened", "reopened"], "command": "start",
         "_note": "Not synchronize: on GitLab every MR update is one, the factory's own status writes included."},
        {"on": "issue_comment", "comment_prefix": "/open-code-review", "command": "start"}
    ],
    "states": [
        {"id": "select", "kind": "code", "label": "Select files", "workflow": "select", "checkout": True,
         "next": "grouping-gate"},
        {"id": "grouping-gate", "kind": "choice", "on": {"from": "select", "path": "$.strategy"},
         "cases": [{"when": "llm", "next": "grouping-try"}], "default": "partition"},
        *try_fork("grouping-try",
                  {"id": "grouping", "kind": "agent", "label": "Group files", "workflow": "grouping-agent",
                   "evidence": "grouping.evidence.schema.json", "max_iterations": 2,
                   "inputs": [{"from": "select", "as": "select"}]},
                  "grouping-join", "partition"),
        {"id": "partition", "kind": "code", "label": "Partition", "workflow": "partition",
         "inputs": [{"from": "select", "as": "select"}, {"from": "grouping", "as": "grouping"}],
         "next": "review"},
        {"id": "review", "kind": "fork", "label": "Review",
         "inputs": [{"from": "partition", "as": "partition"}],
         "expand": {"hook": "expand-groups", "as": "group", "id_from": "$.id", "max_legs": 256},
         "each": {"kind": "sequence", "states": group_states},
         "next": "review-join"},
        {"id": "review-join", "kind": "join", "of": "review", "policy": TOLERANT, "next": "post"},
        {"id": "post", "kind": "code", "label": "Post review", "workflow": "post-review", "checkout": True,
         "inputs": [{"from": "select", "as": "select"}, {"from": "partition", "as": "partition"},
                    {"from_fork": "review", "as": "groups"}]}
    ]
}

json.dump(protocol, sys.stdout, indent=2, ensure_ascii=False)
print()
