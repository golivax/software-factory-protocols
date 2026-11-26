"""Draw protocol.json as a Mermaid flowchart, for the README.

    python3 tests/generate/gen_diagram.py            # print the diagram
    python3 tests/generate/gen_diagram.py --readme   # rewrite it in README.md

It walks the tree as the dashboard's protocol map does (a sequence's states, a
static fork's branches, a dynamic fork's `each` template): an agent node is a
rounded box, a code node a box, a `choice` a diamond whose edges carry the case
values, a fork and its join small circles, a dynamic fork a subgraph "for each
<as>". The three review rounds have one shape, so round 1 is drawn in full and
rounds 2 and 3 as one node each. tests/test_generated.py fails when README.md
holds another diagram.
"""
import json
import pathlib
import re
import sys

PKG = pathlib.Path(__file__).resolve().parents[2]
START, END = "<!-- protocol-diagram:start -->", "<!-- protocol-diagram:end -->"
LATER_ROUND = re.compile(r"^(review|locate|relocate|settle|filter-gate|filter|confirm|round-gate)-[23]"
                         r"(-try|-join)?$")


class Chart:
    def __init__(self):
        self.lines, self.ids = [], {}

    def nid(self, path):
        return self.ids.setdefault(path, f"n{len(self.ids)}")

    def node(self, path, n, indent):
        i, kind = self.nid(path), n.get("kind")
        name = n.get("label") or n["id"]
        if kind == "agent":
            shape = f'(["{name}<br/><i>agent</i>"])'
        elif kind == "code":
            shape = f'["{name}<br/><i>code</i>"]'
        elif kind == "choice":
            shape = '{"' + n["id"] + '"}'
        else:                                   # fork, join
            shape = f'(("{kind}"))'
        self.lines.append(f"{indent}{i}{shape}")
        return i

    def edge(self, a, b, label=None, indent="  "):
        self.lines.append(f"{indent}{a} -->|{label}| {b}" if label else f"{indent}{a} --> {b}")


def leg_states(leg):
    """A leg's steps: its own `states`, or itself (a bare agent/code leg; an
    `each` template has no id, so it is named after its workflow)."""
    if leg.get("kind") == "sequence":
        return leg.get("states")
    return [{**leg, "id": leg.get("id") or leg["workflow"].removesuffix("-agent")}]


def draw_sequence(chart, states, prefix, indent):
    """Draw a sequence; returns (entry id, {node id: chart id}, exit ids)."""
    ids, entries = {}, {}
    rounds_done = set()
    for n in states:
        path = f"{prefix}.{n['id']}" if prefix else n["id"]
        m = LATER_ROUND.match(n["id"])
        if m:
            rnd = re.search(r"-([23])", n["id"]).group(1)
            key = f"{prefix}.round-{rnd}"
            if rnd not in rounds_done:
                rounds_done.add(rnd)
                cid = chart.nid(key)
                chart.lines.append(f'{indent}{cid}[["round {rnd}<br/><i>as round 1, with the '
                                   f'findings confirmed so far and no plan</i>"]]')
            ids[n["id"]] = chart.nid(key)
            continue
        if n.get("kind") == "fork" and n.get("expand"):
            fork = chart.node(path, n, indent)
            sub = chart.nid(path + ".each")
            chart.lines.append(f'{indent}subgraph {sub}["for each {n["expand"]["as"]} '
                               f'({n["expand"]["hook"]})"]')
            each = n["each"]
            first, _, last = draw_sequence(chart, leg_states(each), path + ".each", indent + "  ")
            chart.lines.append(f"{indent}end")
            chart.edge(fork, first, indent=indent)
            entries[n["id"]] = fork
            ids[n["id"]] = fork
            n["_exit"] = sub
            continue
        cid = chart.node(path, n, indent)
        ids[n["id"]] = cid
        if n.get("kind") == "fork":
            for leg in n.get("branches") or []:
                first, _, last = draw_sequence(chart, leg_states(leg), f"{path}.{leg['id']}", indent)
                chart.edge(cid, first, indent=indent)
                n.setdefault("_leg_exits", []).extend(last)
    # the edges between the sequence's steps
    exits = []
    for i, n in enumerate(states):
        src = n.get("_exit") or ids[n["id"]]
        follow = states[i + 1]["id"] if i + 1 < len(states) else None
        if n.get("kind") == "choice":
            for case in n.get("cases") or []:
                when = case["when"]
                link(chart, src, case["next"], ids, when if isinstance(when, str) else json.dumps(when),
                     exits, indent)
            if n.get("default"):
                link(chart, src, n["default"], ids, "else", exits, indent)
            continue
        if n.get("kind") == "fork" and not n.get("expand"):
            join = n.get("next")
            for e in n.get("_leg_exits") or []:
                link(chart, e, join, ids, None, exits, indent)
            continue
        target = n.get("next") or follow
        link(chart, src, target, ids, None, exits, indent)
    first = ids[states[0]["id"]]
    return first, ids, exits


def link(chart, src, target, ids, label, exits, indent):
    if target in (None, "done", "failed"):
        exits.append(src)
        return
    dst = ids.get(target)
    if dst is None or dst == src:      # inside a folded round
        return
    if (src, dst) in getattr(chart, "_seen", set()):
        return
    chart._seen = getattr(chart, "_seen", set()) | {(src, dst)}
    chart.edge(src, dst, label, indent)


def diagram():
    proto = json.loads((PKG / "protocol.json").read_text())
    chart = Chart()
    chart.lines.append("flowchart TD")
    first, _, exits = draw_sequence(chart, proto["states"], "", "  ")
    start, done = chart.nid("(start)"), chart.nid("(done)")
    chart.lines.insert(1, f'  {start}(("start"))')
    chart.edge(start, first)
    chart.lines.append(f'  {done}(("done"))')
    for e in exits:
        chart.edge(e, done)
    return "\n".join(chart.lines) + "\n"


def readme_with(text):
    readme = (PKG / "README.md").read_text()
    block = f"{START}\n```mermaid\n{text}```\n{END}"
    return re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, readme, flags=re.S)


if __name__ == "__main__":
    if sys.argv[1:] == ["--readme"]:
        (PKG / "README.md").write_text(readme_with(diagram()))
    else:
        sys.stdout.write(diagram())
