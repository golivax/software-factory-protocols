"""The two-rounds scenario's authored evidence, played through the real code
nodes off the stack: every round of every group, the routes its choices take,
and the review `post` would publish. It keeps the scenario and the code nodes
in agreement between stack runs (the stack runs the same nodes, for real).
"""
import json
import os
import pathlib

from test_nodes import FAKE_GH, node, _gen_cases  # noqa: F401  (shared helpers)

PKG = pathlib.Path(__file__).resolve().parents[1]
SCN = PKG / "scenarios" / "two-rounds"


def evidence(name):
    p = SCN / "evidence" / f"{name}.json"
    return json.loads(p.read_text()) if p.is_file() else None


def build_mr(tmp_path):
    gen = _gen_cases()
    repo = tmp_path / "repo"
    repo.mkdir()
    gen.git(str(repo), "init", "-q")
    (repo / "README.md").write_text("# target\n")
    gen.git(str(repo), "add", "-A")
    gen.git(str(repo), "commit", "-qm", "base")
    base = gen.git(str(repo), "rev-parse", "HEAD").decode().strip()
    for f in (SCN / "repo").rglob("*"):
        if f.is_file():
            dst = repo / f.relative_to(SCN / "repo")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(f.read_bytes())
    gen.git(str(repo), "add", "-A")
    gen.git(str(repo), "commit", "-qm", "mr")
    head = gen.git(str(repo), "rev-parse", "HEAD").decode().strip()
    diff = gen.git(str(repo), "diff", base, head).decode()
    return {"repo": str(repo), "diff": diff, "files": [],
            "pr": {"number": 3, "title": "t", "body": "", "head_sha": head, "base_sha": base}}


def play_group(tmp_path, mr, select, group):
    """One group's leg, routed as its choices route it; returns collect's evidence."""
    key = group["id"]
    prepare = node("prepare.py", tmp_path, mr, {"select": select, "group": group})
    ins = {"select": select, "prepare": prepare}
    plan = evidence(f"review.{key}.plan-try.plan.step") if prepare["plan"] else None
    assert prepare["plan"] == (plan is not None), f"{key}: plan {prepare['plan']} but evidence {plan is not None}"
    rounds, previous = {}, None
    for n in (1, 2, 3):
        name = f"review.{key}.review-1" if n == 1 else f"review.{key}.review-{n}-try.review-{n}.step"
        review = evidence(name)
        locate = node("locate.py", tmp_path, mr, {**ins, **({"review": review} if review else {})})
        rows = []
        for item in locate["relocations"]:
            ev = evidence(f"review.24295562.relocate-{n}.{item['id']}.step") if key == "g001" else None
            assert ev is not None, f"{key} round {n}: no relocation evidence for {item['id']}"
            rows.append({"leg_id": "x", "key": item["id"], "state": "done", "evidence": ev})
        settle = node("settle.py", tmp_path, mr, {**ins, "locate": locate, "relocations": rows})
        filt = evidence(f"review.{key}.filter-{n}-try.filter-{n}.step")
        assert settle["filter"] == (filt is not None), f"{key} round {n}: filter route"
        confirm = node("confirm.py", tmp_path, mr,
                       {"prepare": prepare, "settle": settle, **({"filter": filt} if filt else {}),
                        **({"previous": previous} if previous else {})}, params={"round": n})
        rounds[f"round-{n}"] = previous = confirm
        if not confirm["continue"]:
            nxt = f"review.{key}.review-{n + 1}-try.review-{n + 1}.step"
            assert evidence(nxt) is None, f"{key}: round {n} stops, but {nxt} has evidence"
            break
    return node("collect.py", tmp_path, mr, {"prepare": prepare, **rounds})


def test_two_rounds_scenario(tmp_path):
    mr = build_mr(tmp_path)
    select = node("select.py", tmp_path, mr, {})
    assert select["strategy"] == "llm"
    assert select["selected"] == ["app/jobs.py", "svc/cache.go", "svc/cache_handler.go", "web/api.ts"]
    partition = node("partition.py", tmp_path, mr,
                     {"select": select, "grouping": evidence("grouping-try.grouping.step")})
    rows = [{"leg_id": g["id"], "key": g["id"], "state": "done", "evidence": play_group(tmp_path, mr, select, g)}
            for g in partition["groups"]]

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH)
    (bin_dir / "gh").chmod(0o755)
    log = tmp_path / "gh.log"
    node("post_review.py", tmp_path, mr, {"select": select, "partition": partition, "groups": rows},
         env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_GH_LOG": str(log), "GITHUB_REPOSITORY": "o/r"})
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    final = json.loads([c for c in calls if "/issues/" in c["argv"][3] and c["stdin"]][-1]["stdin"])["body"]
    for note in json.loads((SCN / "scenario.json").read_text())["expect"]["notes"]:
        assert note in final
    review = json.loads([c for c in calls if c["argv"][3].endswith("/reviews")][0]["stdin"])
    lines = sorted((c["path"], c.get("start_line"), c["line"]) for c in review["comments"])
    # c.misses++, Purge's clock read (round 2), Stats' division (re-located), the unencoded key
    assert lines == [("svc/cache.go", None, 33), ("svc/cache.go", None, 53), ("svc/cache.go", None, 63),
                     ("web/api.ts", None, 7)]
