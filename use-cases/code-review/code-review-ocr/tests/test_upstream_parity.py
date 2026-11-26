"""The port answers as upstream OCR does, case for case.

tests/golden/cases.json holds the inputs (a real git change set with renames,
deletions, a binary, a mode change, CRLF, quoted non-ASCII paths, and the
edge cases around them); tests/golden/upstream_*.json hold what upstream's own
Go functions answered on them, at the commit the vendored data is pinned to
(workflows/ocr/upstream/UPSTREAM.md says how to regenerate both). Every
section here runs the protocol's port on the same inputs and compares.
"""
import json
import pathlib
import sys

import pytest

PKG = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "workflows"))

from ocr import diffs as D  # noqa: E402
from ocr import render as T  # noqa: E402
from ocr import rules as R  # noqa: E402
from ocr import selection as S  # noqa: E402

GOLDEN = PKG / "tests" / "golden"
CASES = json.loads((GOLDEN / "cases.json").read_text())
UP_DIFF = json.loads((GOLDEN / "upstream_diff.json").read_text())
UP_RULES = json.loads((GOLDEN / "upstream_config_rules.json").read_text())
UP_AGENT = json.loads((GOLDEN / "upstream_agent.json").read_text())

DIFF_FIELDS = ("old_path", "new_path", "diff", "is_binary", "is_new", "is_deleted", "is_renamed",
               "insertions", "deletions")


def lines(c):
    return {"path": c.get("path", ""), "existing_code": c.get("existing_code", ""),
            "start_line": c.get("start_line", 0), "end_line": c.get("end_line", 0)}


@pytest.mark.parametrize("i", range(len(CASES["patches"])))
def test_parse_patch(i):
    got = [{k: d[k] for k in DIFF_FIELDS} for d in D.parse_patch(CASES["patches"][i])]
    want = [{k: d[k] for k in DIFF_FIELDS} for d in UP_DIFF["patches"][i]]
    assert got == want


def test_the_factory_diff_reads_as_upstreams():
    """cases' patch 0 is the change as the factory's `git diff` prints it (quoted
    non-ASCII paths), patch 1 the same change as upstream's git invocation
    prints it: requoted, the first parses to exactly what upstream parsed from the second."""
    got = [{k: d[k] for k in DIFF_FIELDS} for d in D.parse_patch(D.requote_paths(CASES["patches"][0]))]
    want = [{k: d[k] for k in DIFF_FIELDS} for d in UP_DIFF["patches"][1]]
    assert got == want


@pytest.mark.parametrize("i", range(len(CASES["resolve"])))
def test_resolve_comment(i):
    case = CASES["resolve"][i]
    cm = dict(case["comment"])
    D.resolve_comment(cm, case["diff"])
    assert lines(cm) == lines(UP_DIFF["resolve"][i])


def test_resolve_line_numbers():
    for case, want in zip(CASES["resolve_all"], UP_DIFF["resolve_all"]):
        got = D.resolve_line_numbers(case["comments"], case["diffs"])
        assert [lines(c) for c in got] == [lines(c) for c in want]


@pytest.mark.parametrize("i", range(len(CASES["relocate"])))
def test_relocate_across_files(i):
    case, want = CASES["relocate"][i], UP_DIFF["relocate"][i]
    cm = dict(case["comment"])
    to = D.relocate_across_files(cm, case["diffs"])
    assert (to or "", to is not None) == (want["to"], want["ok"])
    assert lines(cm) == lines(want["comment"])


def test_extract_code_block():
    assert [D.extract_code_block(b) for b in CASES["code_blocks"]] == UP_DIFF["code_blocks"]


def test_gitignore():
    got = [D.gitignore_matches(c["patterns"], c["path"]) for c in CASES["gitignore"]]
    bad = [(c, g) for c, g, w in zip(CASES["gitignore"], got, UP_DIFF["gitignore"]) if g != w]
    assert not bad


def test_provider_dirs():
    assert [D.provider_dir_prefix(p) for p in CASES["provider_dirs"]] == UP_DIFF["provider_dirs"]


def test_path_gates_and_system_rule():
    default, path_rules = R.load_system_rules()
    bad = []
    for path, want in zip(CASES["paths"], UP_RULES["paths"]):
        ext = S.ext_from_path(path)
        pattern = next((p for p, _ in path_rules if __import__("ocr.globs", fromlist=["x"]).match(
            p.lower(), path.lower())), "default")
        got = {"secret": S.is_secret_path(path), "allowed": ext == "" or S.is_allowed_ext(ext),
               "excluded": S.is_excluded_path(path), "pattern": pattern}
        if got != want:
            bad.append((path, got, want))
    assert not bad


@pytest.mark.parametrize("i", range(len(CASES["repos"])))
def test_rule_layers(i, tmp_path):
    case, want = CASES["repos"][i], UP_RULES["repos"][i]
    for rel, content in case["files"].items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    res = R.Resolver(str(tmp_path), case["custom"])
    assert [res.resolve(p) for p in case["paths"]] == want["rules"]
    flt = res.file_filter()
    assert (flt and {"Include": flt["include"] or None, "Exclude": flt["exclude"] or None}) == \
        (want["filter"] and {"Include": want["filter"]["Include"], "Exclude": want["filter"]["Exclude"]})


def test_select_files():
    for case, want in zip(CASES["select"], UP_AGENT["select"]):
        flt = case["filter"] and {"include": [p.lower() for p in case["filter"]["Include"] or []],
                                  "exclude": [p.lower() for p in case["filter"]["Exclude"] or []]}
        got = [reason for _, reason in S.select_files(case["diffs"], flt, case["max_tokens"])]
        if case["max_tokens"] >= 1000:
            assert got == want
            continue
        # A size gate this tight decides on the tokenizer (upstream's cl100k,
        # this port's 4-bytes estimate: a documented deviation): every other
        # decision still agrees.
        assert [g for g, w in zip(got, want) if "too_large" not in (g, w)] == \
            [w for g, w in zip(got, want) if "too_large" not in (g, w)]


def _groups(gs):
    return [{"label": g["label"], "files": [d["new_path"] for d in g["diffs"]]} for g in gs]


@pytest.mark.parametrize("i", range(len(CASES["grouping_parse"])))
def test_grouping_response(i):
    case, want = CASES["grouping_parse"][i], UP_AGENT["grouping_parse"][i]
    try:
        answer = json.loads(S.strip_code_fences(case["content"]))
    except ValueError:
        assert want == "ERROR"
        return
    assert _groups(S.parse_grouping_response(answer, case["diffs"])) == want


def test_group_token_budget():
    for case, want in zip(CASES["token_budget"], UP_AGENT["token_budget"]):
        assert _groups(S.enforce_group_token_budget(case["groups"], case["limit"])) == want


def test_thresholds():
    tpl = S.template()
    got = [{"grouping": S.grouping_plan(tpl, f, t), "plan": S.plan_required(tpl, f, t, m)}
           for f, t, m in CASES["thresholds"]]
    assert got == UP_AGENT["thresholds"]


def test_prompt_pieces():
    assert [T.confirmed_block(c) for c in CASES["confirmed"]] == UP_AGENT["confirmed"]
    assert [T.filter_comments_json(c) for c in CASES["filter_json"]] == UP_AGENT["filter_json"]
    assert [S.build_file_list(d) for d in CASES["file_list"]] == UP_AGENT["file_list"]
    assert [S.build_concatenated_diffs(d) for d in CASES["concat"]] == UP_AGENT["concat"]
    assert [S.build_change_files_except_group(c["all"], c["group"]) for c in CASES["change"]] == UP_AGENT["change"]


def test_group_rule():
    res = R.Resolver()
    got = [R.resolve_group_rule(res, [{"new_path": p, "old_path": p} for p in paths])
           for paths in CASES["group_rule"]]
    assert got == UP_AGENT["group_rule"]


def _msgs(m):
    return [{"role": r, "content": c} for r, c in m]


@pytest.mark.parametrize("i", range(len(CASES["main"])))
def test_main_prompt(i):
    c = CASES["main"][i]
    got = T.main(date=c["date"], rule=c["rule"], change_files=c["change_files"], diffs=c["diffs"],
                 background=c["background"], plan_result=c["plan"], confirmed=c["confirmed"],
                 language=c["language"])
    assert _msgs(got) == UP_AGENT["main"][i]


def test_plan_prompt():
    for c, want in zip(CASES["plan"], UP_AGENT["plan"]):
        got = T.plan(date=c["date"], rule=c["rule"], change_files=c["change_files"], diffs=c["diffs"],
                     background=c["background"], language=c["language"])
        assert _msgs(got) == want


def test_main_tool_definitions():
    defs = T.tool_definitions()
    got = [defs[n] for n in T.template_task("MAIN_TASK")["tools"]]
    assert got == UP_AGENT["main_tool_defs"]


def test_filter_relocation_grouping_prompts():
    for c, want in zip(CASES["filter"], UP_AGENT["filter"]):
        assert _msgs(T.review_filter(group_key=c["key"], diffs=c["diffs"], comments_json=c["comments"])) == want
    for c, want in zip(CASES["relocation"], UP_AGENT["relocation"]):
        got = T.relocation(diff=c["diff"]["diff"], existing_code=c["comment"]["existing_code"],
                           content=c["comment"]["content"])
        assert _msgs(got) == want
    for c, want in zip(CASES["grouping"], UP_AGENT["grouping"]):
        assert _msgs(T.grouping(c)) == want
