#!/usr/bin/env python3
"""Render one agent node's upstream OCR conversation before the agent starts.

    agent_prompt.py <task> <out_dir>

<task> is grouping | plan | review | filter | relocate. Runs as a step of the
agent's job, outside the agent: it reads the node's staged inputs
($GITHUB_WORKSPACE/inputs/<as>.json) and the run's MR snapshot
($SF_SUBJECT_DIR), fills the task's vendored prompts exactly as upstream fills
them (ocr/render.py), and writes <out_dir>/ocr-prompt.md, and the same text in
parts of at most 6000 bytes (ocr-prompt.part-NNN.md, their count in
ocr-prompt.parts): an agent CLI shows a long command output truncated, so the
agent reads the parts. For `review` it also writes the tool definitions (one
ocr-tool-<name>.json each), the context tools' data (ocr-diffmap.json) and
copies the tools (ocr_tools.py) beside them. A missing input the task needs exits nonzero, so the
agent never starts on a half-rendered prompt.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ocr import context as C  # noqa: E402
from ocr import diffs as D  # noqa: E402
from ocr import render as T  # noqa: E402
from ocr import selection as S  # noqa: E402


def need(name):
    doc = C.read_input(name)
    if doc is None:
        raise C.Failure(f"input {name!r} is missing")
    return doc


def group_diffs(sel, prepare):
    diffs = C.by_paths(sel.kept, prepare.get("files") or [])
    if not diffs:
        raise C.Failure("the group names no file of the selection")
    return diffs


def render(task, out_dir):
    if task == "grouping":
        return T.grouping(need("select").get("file_list") or "")

    sel = C.Selection(need("select"))
    if task == "relocate":
        item = need("relocation")
        d = sel.find(item.get("path") or "")
        if d is None:
            raise C.Failure(f"no diff for {item.get('path')!r}")
        return T.relocation(diff=d["diff"], existing_code=item.get("existing_code") or "",
                            content=item.get("content") or "")

    prepare = need("prepare")
    diffs = group_diffs(sel, prepare)
    concatenated = S.build_concatenated_diffs(diffs)
    if task == "filter":
        settle = need("settle")
        comments = settle.get("comments") or []
        candidates = [comments[i] for i in settle.get("candidates") or []]
        return T.review_filter(group_key=prepare["key"], diffs=concatenated,
                               comments_json=T.filter_comments_json(candidates))

    common = dict(date=prepare["date"], rule=prepare["system_rule"],
                  change_files=S.build_change_files_except_group(sel.kept, diffs),
                  diffs=concatenated, background=prepare.get("background") or "",
                  language=prepare.get("language") or "English")
    if task == "plan":
        return T.plan(**common)
    if task == "review":
        plan = C.read_input("plan") or {}
        previous = C.read_input("previous") or {}
        diffmap = {D.effective_path(d): d["diff"] for d in sel.included}
        with open(os.path.join(out_dir, "ocr-diffmap.json"), "w", encoding="utf-8") as fh:
            json.dump(diffmap, fh, ensure_ascii=False)
        defs = T.tool_definitions()
        for name in T.template_task("MAIN_TASK")["tools"]:     # one file a tool: each reads whole
            with open(os.path.join(out_dir, f"ocr-tool-{name}.json"), "w", encoding="utf-8") as fh:
                json.dump(defs[name], fh, ensure_ascii=False, indent=2)
        shutil.copy(os.path.join(HERE, "ocr_tools.py"), os.path.join(out_dir, "ocr_tools.py"))
        return T.main(**common, plan_result=plan.get("plan") or "",
                      confirmed=T.confirmed_block(previous.get("confirmed") or []))
    raise C.Failure(f"unknown task {task!r}")


PART_BYTES = 6000


def parts(text, limit=PART_BYTES):
    """`text` cut at line ends into parts of at most `limit` bytes (a longer line
    is cut inside). An agent CLI shows a long command output truncated, so the
    agent reads the conversation part by part, never in one `cat`."""
    out, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line.encode("utf-8")) > limit:
            head = line.encode("utf-8")[:limit].decode("utf-8", "ignore")
            if cur:
                out.append(cur)
                cur = ""
            out.append(head)
            line = line[len(head):]
        if cur and len((cur + line).encode("utf-8")) > limit:
            out.append(cur)
            cur = ""
        cur += line
    if cur:
        out.append(cur)
    return out


def main():
    task, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    text = T.to_markdown(render(task, out_dir)) + "\n"
    path = os.path.join(out_dir, "ocr-prompt.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    chunks = parts(text)
    for i, chunk in enumerate(chunks, 1):
        with open(os.path.join(out_dir, f"ocr-prompt.part-{i:03d}.md"), "w", encoding="utf-8") as fh:
            fh.write(chunk)
    with open(os.path.join(out_dir, "ocr-prompt.parts"), "w", encoding="utf-8") as fh:
        fh.write(f"{len(chunks)}\n")
    print(f"[ocr] rendered the {task} prompt: {path} ({len(text.encode('utf-8'))} bytes, "
          f"{len(chunks)} part(s))")


if __name__ == "__main__":
    C.run(main)
