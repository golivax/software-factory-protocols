"""Generate the oracle cases: a real git change set with the shapes a review
meets, and inputs for every function the protocol ports.

    python3 gen_cases.py <out cases.json>

See workflows/ocr/upstream/UPSTREAM.md for running the oracle over them.
"""
import json
import os
import random
import subprocess
import sys
import tempfile

PKG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "workflows")
sys.path.insert(0, PKG)
from ocr import diffs as D  # noqa: E402

rng = random.Random(20261126)


FIXED = {"GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
         "GIT_AUTHOR_NAME": "oracle", "GIT_AUTHOR_EMAIL": "o@example.com",
         "GIT_COMMITTER_NAME": "oracle", "GIT_COMMITTER_EMAIL": "o@example.com",
         # no user or system config: signing, autocrlf or noprefix would change the ids and diffs
         "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def git(repo, *args, input=None):
    """git with fixed identities and dates: the same repo, the same commit ids."""
    return subprocess.run(["git", "-c", "init.defaultBranch=main", "-C", repo, *args], check=True,
                          capture_output=True, input=input, env={**os.environ, **FIXED}).stdout


def write(repo, rel, text, mode=None):
    p = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(p) or repo, exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(text.encode() if isinstance(text, str) else text)
    if mode:
        os.chmod(p, mode)


GO_OLD = """package svc

import "fmt"

// Handler serves one request.
func Handler(id int) error {
	if id < 0 {
		return fmt.Errorf("bad id %d", id)
	}
	cache := map[int]string{}
	cache[id] = "x"
	return nil
}

func unused() {}
"""
GO_NEW = """package svc

import (
	"fmt"
	"sync"
)

var mu sync.Mutex

// Handler serves one request.
func Handler(id int, name string) error {
	if id <= 0 {
		return fmt.Errorf("bad id %d", id)
	}

	cache := map[int]string{}
	mu.Lock()
	cache[id] = name
	mu.Unlock()
	return nil
}
"""
PY_OLD = "def f(x):\n    return x + 1\n\n\ndef g(y=[]):\n    y.append(1)\n    return y\n"
PY_NEW = "def f(x):\n    if x is None:\n        return 0\n    return x + 1\n\n\ndef g(y=None):\n    y = y or []\n    y.append(1)\n    return y\n"


def build_repo(repo=None):
    repo = repo or tempfile.mkdtemp(prefix="ocr-oracle-repo-")
    git(repo, "init", "-q", "-b", "main")
    write(repo, "svc/handler.go", GO_OLD)
    write(repo, "app/util.py", PY_OLD)
    write(repo, "app/old_name.py", "A = 1\nB = 2\nC = 3\nD = 4\nE = 5\n")
    write(repo, "docs/remove_me.md", "# gone\n\nbye\n")
    write(repo, "web/index.ts", "export const a = 1;\nexport function f(n: number) { return n * 2; }\n")
    write(repo, "img/logo.png", bytes(range(256)))
    write(repo, "scripts/run.sh", "#!/bin/sh\necho hi\n")
    write(repo, "conf/app.yaml", "a: 1\nb: 2\n")
    write(repo, "win/crlf.txt", "line one\r\nline two\r\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD").decode().strip()
    git(repo, "checkout", "-qb", "feature")
    write(repo, "svc/handler.go", GO_NEW)
    write(repo, "app/util.py", PY_NEW)
    git(repo, "mv", "app/old_name.py", "app/new_name.py")
    write(repo, "app/new_name.py", "A = 1\nB = 2\nC = 33\nD = 4\nE = 5\n")
    os.remove(os.path.join(repo, "docs/remove_me.md"))
    write(repo, "web/index.ts", "export const a = 1;\nexport function f(n: number) { return n * 3; }\n"
                                "export function g(s: string) { return eval(s); }\n")
    write(repo, "img/logo.png", bytes(reversed(range(256))))
    os.chmod(os.path.join(repo, "scripts/run.sh"), 0o755)
    write(repo, "conf/app.yaml", "a: 1\nb: 3\nc: [x, y]\n")
    write(repo, "win/crlf.txt", "line one\r\nline 2\r\n")
    write(repo, "src/üñí/naïve file.go", "package p\n\nfunc F() int { return 1 }\n")
    write(repo, "svc/handler_test.go", "package svc\n\nfunc TestX() {}\n")
    write(repo, ".env", "SECRET=1\n")
    write(repo, ".env.example", "SECRET=\n")
    write(repo, "vendor/lib/x.go", "package lib\n")
    write(repo, "api/vendor/y.go", "package y\n")
    write(repo, "src/main.m", "#import <Foundation/Foundation.h>\nint main() { return 0; }\n")
    write(repo, "notes.weird", "x\n")
    write(repo, "Makefile", "all:\n\techo hi\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "feature")
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    return repo, base, head


def main():
    pkg, out = PKG, sys.argv[1]
    repo, base, head = build_repo()
    factory_patch = git(repo, "diff", base, head).decode("utf-8", "surrogateescape")
    upstream_patch = git(repo, "-c", "core.quotepath=false", "diff", "--no-ext-diff", "--no-textconv",
                         "--find-renames", "--src-prefix=a/", "--dst-prefix=b/", "--no-color", "-U3",
                         "--end-of-options", base, head, "--").decode("utf-8", "surrogateescape")
    extra = [
        "",
        "diff --git a/x.go b/x.go\nindex 1..2 100644\n--- a/x.go\n+++ b/x.go\n@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file\n",
        'diff --git "a/q \\"x\\".go" "b/q \\"x\\".go"\nnew file mode 100644\n--- /dev/null\n+++ "b/q \\"x\\".go"\n@@ -0,0 +1,2 @@\n+one\n+two\n',
        "diff --git a/a b/a b/a b/a b\nindex 1..2\n--- a/a b\n+++ b/a b\n@@ -1,2 +1,3 @@\n ctx\n-old\n+new\n+more\n",
        "garbage before\ndiff --git a/c.py b/c.py\ndeleted file mode 100644\n--- a/c.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-x\n-y\n",
        "diff --git a/r.txt b/r.txt\r\nindex 1..2 100644\r\n--- a/r.txt\r\n+++ b/r.txt\r\n@@ -1,3 +1,3 @@\r\n a\r\n-b\r\n+B\r\n c\r\n",
    ]
    patches = [factory_patch, upstream_patch, *extra]
    diffs = D.parse_patch(factory_patch)
    for d in diffs:
        if not d["is_deleted"] and not d["is_binary"]:
            r = subprocess.run(["git", "-C", repo, "show", f"{head}:{d['new_path']}"], capture_output=True)
            if r.returncode == 0:
                d["new_file_content"] = r.stdout.decode("utf-8", "replace")
    by = {D.effective_path(d): d for d in diffs}
    go, py, ts = by["svc/handler.go"], by["app/util.py"], by["web/index.ts"]

    def cm(path, code, **kw):
        return {"path": path, "content": kw.pop("content", "issue"), "existing_code": code, **kw}

    snippets = [
        (go, "mu.Lock()"), (go, "  +mu.Lock()  "), (go, "mu.Lock()\ncache[id] = name\nmu.Unlock()"),
        (go, "if id <= 0 {\n\n\treturn fmt.Errorf(\"bad id %d\", id)"), (go, "cache[id] = \"x\""),
        (go, "func unused() {}"), (go, "nothing like this"), (go, ""), (go, "\n\n"),
        (go, "-\tcache[id] = \"x\""), (go, "package svc"), (go, "import (\n\"fmt\"\n\"sync\"\n)"),
        (go, "var mu sync.Mutex\n\n// Handler serves one request."), (py, "y = y or []"),
        (py, "def g(y=[]):"), (py, "return x + 1"), (ts, "return eval(s);"),
        (ts, "export function g(s: string) { return eval(s); }"), (by["win/crlf.txt"], "line 2"),
        (by["app/new_name.py"], "C = 33"), (by["app/new_name.py"], "E = 5"),
    ]
    resolve = [{"comment": cm(d["new_path"], code), "diff": d} for d, code in snippets]
    resolve.append({"comment": cm(go["new_path"], "mu.Lock()", start_line=7, end_line=7), "diff": go})
    no_content = {**go, "new_file_content": ""}
    resolve.append({"comment": cm(go["new_path"], "package svc"), "diff": no_content})

    relocate = [
        {"comment": cm("svc/handler.go", "return eval(s);"), "diffs": diffs},
        {"comment": cm("web/index.ts", "mu.Lock()"), "diffs": diffs},
        {"comment": cm("svc/handler.go", "A = 1"), "diffs": diffs + [{**by["app/new_name.py"], "new_path": "app/dup.py", "old_path": "app/dup.py"}]},
        {"comment": cm("svc/handler.go", "no such code"), "diffs": diffs},
        {"comment": cm("other/file.go", "y = y or []"), "diffs": diffs},
        {"comment": cm("svc/handler.go", ""), "diffs": diffs},
    ]
    resolve_all = [{"comments": [c["comment"] for c in resolve], "diffs": diffs}]

    code_blocks = ["```go\nmu.Lock()\n```", "text before\n```\n  a\n  b\n```\nafter", "```", "no fence",
                   "```\nunterminated", "  ```python\nx = 1\n```  ", "```one-line```"]

    gitignore = []
    pats = [["*.log"], ["build/"], ["/root.txt"], ["docs/*.md"], ["**/gen/**"], ["*", "!*.go", "!*/"],
            ["secret*", "!secret_ok"], ["a/b/"], ["/dist/"], ["foo/**/bar"], ["*.py", "!/app/"],
            ["\\#hash"], ["[abc].txt"], ["sub/*.txt"], ["!*.go"]]
    paths = ["x.log", "a/x.log", "build/x", "a/build/y.go", "root.txt", "a/root.txt", "docs/a.md",
             "a/docs/a.md", "x/gen/y.go", "gen/y", "main.go", "a/main.go", "a/b.txt", "secret.txt",
             "secret_ok", "a/b/c.go", "dist/x.js", "a/dist/x.js", "foo/bar", "foo/x/y/bar", "app/u.py",
             "#hash", "a.txt", "d.txt", "sub/x.txt", "sub/deeper/x.txt", "x.go"]
    for p in pats:
        for path in paths:
            gitignore.append({"patterns": p, "path": path})

    provider = ["vendor", "vendor/x.go", "a/vendor/x.go", "node_modules/a.js", ".git/config", "target",
                "targets/x", "rpm/x.spec", ".idea", ".idea/x", "x/.idea/y"]

    with open(os.path.join(pkg, "ocr", "upstream", "rules", "system_rules.json")) as fh:
        rule_patterns = list(json.load(fh)["path_rule_map"])
    with open(os.path.join(pkg, "ocr", "upstream", "allowlist", "supported_file_types.json")) as fh:
        exts = json.load(fh)
    with open(os.path.join(pkg, "ocr", "upstream", "allowlist", "default_exclude_patterns.json")) as fh:
        excl = json.load(fh)
    rule_paths = []
    for pat in rule_patterns + excl:
        for alt in __import__("ocr.globs", fromlist=["x"]).expand_braces(pat):
            concrete = alt.replace("**/", rng.choice(["", "a/", "deep/er/"])).replace("**", "x/y")
            concrete = concrete.replace("*", rng.choice(["foo", "Bar_test", "mapper"]))
            rule_paths.append(concrete)
            rule_paths.append(concrete.upper() if rng.random() < 0.2 else "pre/" + concrete)
    rule_paths += [f"src/file{e}" for e in exts] + [f"src/FILE{e.upper()}" for e in exts[:20]]
    rule_paths += ["Dockerfile", "Makefile", "README", ".env", ".env.local", ".env.example", "x/.env.sample",
                   "home/.ssh/config", "id_rsa", "a/id_ed25519", ".npmrc", "a/.netrc", "x._netrc",
                   ".github/workflows/ci.yml", ".github/dependabot.yml", "k8s/deploy.yaml", "x.json5",
                   "a/b/UserMapper.xml", "a/dao.xml", "pom.xml", "sub/pom.xml", "src/app.test.ts",
                   "pkg/foo_test.go", "foo_test.go", "tests/test_x.py", "src/x.R", "src/x.r", "src/x.m",
                   "BUILD", "a/WORKSPACE", "Gemfile", "x.gemspec", "lib.rs", "a/tests/x.rs", ".hidden",
                   "noext", "a.b.c.TS", "weird.", "dir.with.dot/file"]

    repos = [
        {"files": {}, "custom": "", "paths": ["a.go", "b.py", "c.unknown"]},
        {"files": {".opencodereview/rule.json": json.dumps({"rules": [
            {"path": "**/*.go", "rule": "Go team rules"},
            {"path": "**/*.py", "rule": "PY extra", "merge_system_rule": True},
            {"path": "docs/**", "rule": "rules/docs.md"},
            {"path": "**/*.ts", "rule": ""}],
            "include": ["**/*.WEIRD"], "exclude": ["gen/**", "**/*.{pb.go,g.dart}"]}),
            "rules/docs.md": "Docs rule from a file\n\n"},
         "custom": "", "paths": ["a.go", "x/b.py", "docs/a.md", "w.ts", "y.rs"]},
        {"files": {"custom.json": json.dumps({"rules": [{"path": "*.go", "rule": "custom go"}],
                                              "exclude": ["only/**"]}),
                   ".opencodereview/rule.json": json.dumps({"rules": [{"path": "**/*.go", "rule": "project go"}],
                                                            "include": ["x/**"]})},
         "custom": "custom.json", "paths": ["a.go", "sub/a.go", "b.py"]},
        {"files": {".opencodereview/rule.json": json.dumps({"rules": [
            {"path": "**/*.md", "rule": "../escape.md"}, {"path": "**/*.txt", "rule": "notes.txt"}]}),
            "notes.txt": "plain text rules\n"},
         "custom": "", "paths": ["a.md", "b.txt"]},
    ]

    selectable = [d for d in diffs]
    select = [{"diffs": selectable, "filter": None, "max_tokens": 200000},
              {"diffs": selectable, "filter": {"Include": ["**/*.weird", "vendor/**"], "Exclude": ["app/**"]},
               "max_tokens": 200000},
              {"diffs": selectable, "filter": {"Include": [], "Exclude": ["**/*.{go,ts}"]}, "max_tokens": 40}]

    def mk(path, ins, dels, new=False, deleted=False, renamed=False):
        return {"old_path": path, "new_path": "/dev/null" if deleted else path, "diff": "x" * (ins + dels),
                "is_new": new, "is_deleted": deleted, "is_renamed": renamed, "is_binary": False,
                "insertions": ins, "deletions": dels}

    ds = [mk(f"f{i}.go", i * 7 % 50, i % 9) for i in range(13)]
    grouping_parse = [
        {"content": json.dumps([{"label": "a", "files": [0, 1, 2]}, {"label": "b", "files": [3, 3, 99, -1]}]), "diffs": ds[:6]},
        {"content": "```json\n" + json.dumps([{"label": "all", "files": list(range(13))}]) + "\n```", "diffs": ds},
        {"content": "not json", "diffs": ds[:3]},
        {"content": "[]", "diffs": ds[:3]},
        {"content": json.dumps([{"label": "x", "files": [2, 0]}, {"label": "y", "files": [0]}]), "diffs": ds[:4]},
    ]
    big = mk("big.go", 1, 1)
    big["diff"] = "y" * 1000
    token_budget = [{"groups": [{"label": "g", "diffs": [ds[0], big]}, {"label": "h", "diffs": ds[1:3]}],
                     "limit": 100}, {"groups": [{"label": "g", "diffs": [ds[0], big]}], "limit": 0}]
    thresholds = [[f, t, m] for f in (1, 2, 3, 4, 10) for t in (0, 49, 50, 99, 100, 199, 200, 500)
                  for m in (0, 49, 50)]

    comments = [{"path": "a.go", "content": "multi\nline <b>&amp;</b> " + "z" * 400, "existing_code": "x := 1\n  y ",
                 "category": "bug", "severity": "high"},
                {"path": "b.go", "content": "short", "existing_code": ""},
                {"path": "ü.go", "content": "é" * 310, "existing_code": "ß" * 205}]
    confirmed = [[], comments, comments[:1]]
    filter_json = [[], comments]
    file_list = [diffs, [ds[0]]]
    concat = [diffs[:3], [ds[0]]]
    change = [{"all": diffs, "group": diffs[:2]}, {"all": diffs, "group": []}, {"all": [ds[0]], "group": [ds[0]]}]
    group_rule = [["a.go"], ["a.go", "b.go"], ["b.py", "a.go", "c.go"], ["x.unknownext"], ["m.properties", "a.java", "b.java"]]

    rule = "#### Rule\n- check {{diffs}} literally"
    main = []
    for plan in ("", "Summary: x\n\nIssues\n\n1. [high] y"):
        for conf in ("", "The following issues...\n<confirmed_findings>\n1. a.go\n</confirmed_findings>"):
            for lang in ("English", "Chinese"):
                main.append({"date": "2026-11-26 10:00", "rule": rule, "change_files": "MODIFIED   x.go (+1/-0)",
                             "diffs": '<file path="a.go">\n+{{system_rule}}\n</file>', "background": "bg {{plan_guidance}}",
                             "plan": plan, "confirmed": conf, "language": lang})
    plan_cases = [{"date": "2026-11-26 10:00", "rule": rule, "change_files": "", "diffs": "<file/>",
                   "background": "", "language": "English"}]
    filter_cases = [{"key": "a.go,b.go", "diffs": "<file path=\"a.go\">\n+x\n</file>", "comments": "[{\"id\":\"c-0\"}]"}]
    relocation = [{"comment": {"path": "a.go", "content": "c {diff}", "existing_code": "e {existing_code}"},
                   "diff": {"old_path": "a.go", "new_path": "a.go", "diff": "@@ -1 +1 @@\n-a\n+b {suggestion_content}"}}]
    grouping = ["[0] MODIFIED   a.go (+1/-0)\n[1] ADDED   b.go (+3/-0)\n"]

    cases = {"patches": patches, "resolve": resolve, "resolve_all": resolve_all, "relocate": relocate,
             "code_blocks": code_blocks, "gitignore": gitignore, "provider_dirs": provider,
             "paths": rule_paths, "repos": repos, "select": select, "grouping_parse": grouping_parse,
             "token_budget": token_budget, "thresholds": thresholds, "confirmed": confirmed,
             "filter_json": filter_json, "file_list": file_list, "concat": concat, "change": change,
             "group_rule": group_rule, "main": main, "plan": plan_cases, "filter": filter_cases,
             "relocation": relocation, "grouping": grouping,
             "tools": tool_cases(repo, base, head, diffs)}
    with open(out, "w") as fh:
        json.dump(cases, fh, ensure_ascii=False, indent=1)
    print(f"{out}: {sum(len(v) for v in cases.values())} cases")


def tool_cases(repo, base, head, diffs):
    long_line = "x" * 3000
    calls = [
        ("file_read", {"file_path": "svc/handler.go"}),
        ("file_read", {"file_path": "svc/handler.go", "start_line": 5, "end_line": 9}),
        ("file_read", {"file_path": "svc/handler.go", "start_line": 9, "end_line": 5}),
        ("file_read", {"file_path": "svc/handler.go", "start_line": 400}),
        ("file_read", {"file_path": "svc/handler.go", "start_line": 0, "end_line": -3}),
        ("file_read", {"file_path": "nope.go"}),
        ("file_read", {}),
        ("file_read", {"file_path": "svc/handler.go", "side": "old"}),
        ("file_read", {"file_path": "app/old_name.py", "side": "old", "end_line": 2}),
        ("file_read", {"file_path": "app/old_name.py"}),
        ("file_read", {"file_path": "svc/handler.go", "side": "sideways"}),
        ("file_read", {"file_path": "win/crlf.txt"}),
        ("file_read", {"file_path": "src/üñí/naïve file.go", "start_line": 2.0}),
        ("code_search", {"search_text": "mu.Lock("}),
        ("code_search", {"search_text": "HANDLER"}),
        ("code_search", {"search_text": "HANDLER", "case_sensitive": True}),
        ("code_search", {"search_text": "func \\w+\\(", "use_perl_regexp": True}),
        ("code_search", {"search_text": "func (", "use_perl_regexp": True}),
        ("code_search", {"search_text": "return", "file_patterns": ["*.py", ":(exclude)app/new_name.py"]}),
        ("code_search", {"search_text": "return", "file_patterns": ["../x"]}),
        ("code_search", {"search_text": "   "}),
        ("code_search", {"search_text": "zzz-not-there"}),
        ("code_search", {"search_text": "cache", "side": "old"}),
        ("code_search", {"search_text": "e", "file_patterns": ["svc/"]}),
        ("file_find", {"query_name": "handler"}),
        ("file_find", {"query_name": "HANDLER", "case_sensitive": True}),
        ("file_find", {"query_name": "app/n"}),
        ("file_find", {"query_name": "make"}),
        ("file_find", {"query_name": "remove_me", "side": "old"}),
        ("file_find", {"query_name": "remove_me"}),
        ("file_find", {"query_name": " "}),
        ("file_read_diff", {"path_array": ["svc/handler.go", "missing.go"]}),
        ("file_read_diff", {"path_array": []}),
        ("file_read_diff", {"path_array": ["missing.go"]}),
    ]
    diffmap = {D.effective_path(d): d["diff"] for d in diffs}
    return {"repo": repo, "base": base, "head": head, "diffmap": diffmap,
            "calls": [{"tool": t, "args": a} for t, a in calls], "long_line": long_line}


if __name__ == "__main__":
    main()
