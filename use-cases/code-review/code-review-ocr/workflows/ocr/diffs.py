"""The diff side of upstream OCR: parsing a patch into per-file diffs, the
provider's path filters, and placing a comment on its lines.

Ported from internal/diff/{parser,hunk,quotedpath,git,gitignore,resolver,
relocation}.go. A diff here is a dict with upstream's model.Diff fields:
old_path, new_path, diff (the file's patch text, without its `index` line),
is_binary, is_new, is_deleted, is_renamed, insertions, deletions, and
new_file_content when the file was read from the checkout.
"""
import re
import subprocess

from . import globs

DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

# internal/diff/git.go providerDirIgnoreDirs: matched by prefix at the root.
PROVIDER_DIR_IGNORE_DIRS = [".idea/", ".vscode/", ".svn/", ".git/", "vendor/",
                            "node_modules/", "target/", ".happypack/",
                            ".cachefile/", "_packages/", "rpm/"]

CONTEXT, ADDED, DELETED = 0, 1, 2


# -- quoted paths -------------------------------------------------------------

_ESC = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, '"': 34, "\\": 92}


def unquote_git_path(s):
    """A C-quoted path at the start of `s` -> (path, rest) or None."""
    if not s.startswith('"'):
        return None
    out = bytearray()
    i = 1
    while i < len(s):
        c = s[i]
        if c == '"':
            return out.decode("utf-8", "surrogateescape"), s[i + 1:]
        if c != "\\":
            out.extend(c.encode("utf-8", "surrogateescape"))
            i += 1
            continue
        i += 1
        if i >= len(s):
            return None
        e = s[i]
        if e in _ESC:
            out.append(_ESC[e])
        elif e in "01234567":
            digits = s[i:i + 3]
            if len(digits) < 3 or any(d not in "01234567" for d in digits):
                return None
            v = int(digits, 8)
            if v > 0xFF:
                return None
            out.append(v)
            i += 2
        else:
            return None
        i += 1
    return None


def _split_header_paths(rest):
    if rest.startswith('"'):
        first = unquote_git_path(rest)
        if first is None:
            return None
        path1, after = first
        if not after.startswith(" "):
            return None
        after = after[1:]
        if after.startswith('"'):
            second = unquote_git_path(after)
            if second is None or second[1] != "":
                return None
            return path1, second[0]
        return path1, after
    q = rest.find('"')
    if q <= 0 or rest[q - 1] != " ":
        return None
    second = unquote_git_path(rest[q:])
    if second is None or second[1] != "":
        return None
    return rest[:q - 1], second[0]


def _split_same_path_header(rest):
    for i in range(len(rest) - 2):
        if rest[i:i + 3] != " b/":
            continue
        if rest[:i].startswith("a/") and rest[2:i] == rest[i + 3:]:
            return rest[2:i], rest[i + 3:]
    return None


def parse_diff_header_line(line):
    if line.startswith("diff --git "):
        same = _split_same_path_header(line[len("diff --git "):])
        if same:
            return same
    m = DIFF_HEADER_RE.match(line)
    if m:
        return m.group(1), m.group(2)
    if not line.startswith("diff --git "):
        return None
    paths = _split_header_paths(line[len("diff --git "):])
    if not paths:
        return None
    first, second = paths
    if not first.startswith("a/") or not second.startswith("b/"):
        return None
    return first[2:], second[2:]


_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')
_HEADER_PREFIXES = ("diff --git ", "--- ", "+++ ", "rename from ", "rename to ", "copy from ",
                    "copy to ", "Binary files ")
_CQUOTE = {7: "\\a", 8: "\\b", 9: "\\t", 10: "\\n", 11: "\\v", 12: "\\f", 13: "\\r",
           34: '\\"', 92: "\\\\"}


def _quote_like_quotepath_false(path):
    """How git writes a path with core.quotepath=false: raw, unless it holds a
    double quote, a backslash or a control character; then C-quoted, its
    non-ASCII left raw."""
    if not any(c in '"\\' or ord(c) < 0x20 or ord(c) == 0x7F for c in path):
        return path
    out = []
    for c in path:
        o = ord(c)
        if o in _CQUOTE:
            out.append(_CQUOTE[o])
        elif o < 0x20 or o == 0x7F:
            out.append(f"\\{o:03o}")
        else:
            out.append(c)
    return '"' + "".join(out) + '"'


def requote_paths(text):
    """The factory's `git diff` quotes non-ASCII paths (core.quotepath=true);
    upstream diffs with core.quotepath=false. Rewrite the quoted paths of the
    file headers as upstream's git would write them, so the diff text the
    prompts carry is upstream's. Hunk lines are left alone."""
    out, in_hunk = [], False
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            in_hunk = False
        elif line.startswith("@@"):
            in_hunk = True
        if not in_hunk and line.startswith(_HEADER_PREFIXES) and '"' in line:
            def requote(m):
                r = unquote_git_path(m.group(0))
                return _quote_like_quotepath_false(r[0]) if r and r[1] == "" else m.group(0)
            line = _QUOTED.sub(requote, line)
        out.append(line)
    return "\n".join(out)


def unquote_rename_path(s):
    if not s.startswith('"'):
        return s
    r = unquote_git_path(s)
    if r is None or r[1] != "":
        return s
    return r[0]


# -- parsing ------------------------------------------------------------------

def split_diff_lines(text):
    return [ln[:-1] if ln.endswith("\r") else ln for ln in text.split("\n")]


def _new_diff(old_path, new_path):
    return {"old_path": old_path, "new_path": new_path, "diff": "", "is_binary": False,
            "is_new": False, "is_deleted": False, "is_renamed": False,
            "insertions": 0, "deletions": 0}


def parse_patch(text):
    """ParsePatch: one diff per `diff --git` header, in patch order."""
    diffs, current, buf, in_hunk = [], None, [], False
    for line in split_diff_lines(text):
        header = parse_diff_header_line(line)
        if header:
            if current is not None:
                current["diff"] = "".join(buf).removesuffix("\n")
                diffs.append(current)
                buf = []
            current = _new_diff(*header)
            in_hunk = False
        if current is None:
            continue
        if line.startswith("@@"):
            in_hunk = True
        elif not in_hunk and line.startswith("index "):
            continue
        elif not in_hunk and line.startswith("Binary files "):
            current["is_binary"] = True
        elif line.startswith("new file mode "):
            current["is_new"] = True
        elif line.startswith("deleted file mode "):
            current["is_deleted"] = True
        elif line.startswith("rename from "):
            current["old_path"] = unquote_rename_path(line[len("rename from "):])
            current["is_renamed"] = True
        elif line.startswith("rename to "):
            current["new_path"] = unquote_rename_path(line[len("rename to "):])
            current["is_renamed"] = True
        elif not in_hunk and line.startswith("copy from "):
            current["old_path"] = unquote_rename_path(line[len("copy from "):])
        elif not in_hunk and line.startswith("copy to "):
            current["new_path"] = unquote_rename_path(line[len("copy to "):])
        elif not in_hunk and line == "--- /dev/null":
            current["is_new"] = True
        elif not in_hunk and line == "+++ /dev/null":
            current["is_deleted"] = True
        elif in_hunk and line.startswith("+"):
            current["insertions"] += 1
        elif in_hunk and line.startswith("-"):
            current["deletions"] += 1
        buf.append(line + "\n")
    if current is not None:
        current["diff"] = "".join(buf).removesuffix("\n")
        diffs.append(current)
    for d in diffs:
        if d["is_deleted"] or d["new_path"] == "/dev/null":
            d["new_path"] = "/dev/null"
    return diffs


def effective_path(d):
    return d["old_path"] if d["new_path"] == "/dev/null" else d["new_path"]


def parse_hunks(text):
    """ParseHunks: each hunk's start lines and its typed lines."""
    hunks, current = [], None
    for line in split_diff_lines(text):
        m = HUNK_HEADER_RE.match(line) if line.startswith("@@ ") else None
        if m:
            if current is not None:
                hunks.append(current)
            current = {"old_start": int(m.group(1)), "new_start": int(m.group(3)), "lines": []}
            continue
        if current is None:
            continue
        if line.startswith("\\ No newline at end of file"):
            continue
        if line.startswith("diff --git "):
            break
        if line.startswith("+"):
            current["lines"].append((ADDED, line[1:]))
        elif line.startswith("-"):
            current["lines"].append((DELETED, line[1:]))
        else:
            current["lines"].append((CONTEXT, line[1:] if line.startswith(" ") else line))
    if current is not None:
        hunks.append(current)
    return hunks


# -- the provider's path filters (git.go, gitignore.go) ------------------------

def provider_dir_prefix(rel_path):
    for prefix in PROVIDER_DIR_IGNORE_DIRS:
        if rel_path == prefix.rstrip("/") or rel_path.startswith(prefix):
            return prefix
    return ""


def parse_gitignore(text):
    return [ln.strip() for ln in text.split("\n")
            if ln.strip() and not ln.strip().startswith("#")]


def _match_gitignore_directory(rel_path, pattern):
    anchored = pattern.startswith("/")
    pattern = pattern[1:] if anchored else pattern
    if not pattern or "/" not in rel_path:
        return False
    components = rel_path[:rel_path.rfind("/")].split("/")
    full = anchored or "/" in pattern
    for i, comp in enumerate(components):
        cand = "/".join(components[:i + 1]) if full else comp
        if globs.match(pattern, cand):
            return True
    return False


def _match_gitignore_body(rel_path, body):
    if body.endswith("/"):
        return _match_gitignore_directory(rel_path, body[:-1])
    anchored = body.startswith("/")
    if anchored:
        body = body[1:]
    if "**" in body:
        return globs.match(body, rel_path)
    if "/" not in body:
        target = rel_path if anchored else rel_path.rsplit("/", 1)[-1]
        return globs.fnmatch(body, target)
    if globs.fnmatch(body, rel_path):
        return True
    return not anchored and rel_path.endswith("/" + body)


def gitignore_matches(patterns, rel_path):
    """Last matching pattern wins; `!` inverts; a negated directory pattern
    never re-admits files."""
    excluded = False
    for pat in patterns:
        negated = pat.startswith("!")
        body = pat[1:] if negated else pat
        if not body or (negated and body.endswith("/")):
            continue
        if _match_gitignore_body(rel_path, body):
            excluded = not negated
    return excluded


def partition_diffs(diffs, gitignore_patterns):
    """partitionDiffs: (included, provider-dir excluded); a path the root
    .gitignore matches is dropped altogether."""
    included, excluded = [], []
    for d in diffs:
        path = effective_path(d)
        if provider_dir_prefix(path):
            excluded.append(d)
        elif not gitignore_matches(gitignore_patterns, path):
            included.append(d)
    return included, excluded


# -- placing a comment (resolver.go) --------------------------------------------

def normalize_line(s):
    s = s.strip()
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("-"):
        s = s[1:]
    return s.strip()


def split_and_normalize(code):
    return [n for n in (normalize_line(ln) for ln in code.split("\n")) if n]


def _side_lines(hunk, new_side):
    out, old, new = [], hunk["old_start"], hunk["new_start"]
    for kind, content in hunk["lines"]:
        if kind == CONTEXT:
            out.append((new if new_side else old, normalize_line(content)))
            old += 1
            new += 1
        elif kind == ADDED:
            if new_side:
                out.append((new, normalize_line(content)))
            new += 1
        else:
            if not new_side:
                out.append((old, normalize_line(content)))
            old += 1
    return out


def _match_consecutive(side, target):
    if not target or len(side) < len(target):
        return None
    for i in range(len(side) - len(target) + 1):
        if all(side[i + j][1] == t for j, t in enumerate(target)):
            return side[i][0], side[i + len(target) - 1][0]
    return None


def _resolve_from_hunk(d, cm):
    hunks = parse_hunks(d["diff"])
    target = split_and_normalize(cm.get("existing_code") or "")
    if not hunks or not target:
        return False
    for pick in (lambda h: _side_lines(h, True),
                 lambda h: [x for x in _side_lines(h, True) if x[1] != ""],
                 lambda h: _side_lines(h, False)):
        for h in hunks:
            hit = _match_consecutive(pick(h), target)
            if hit:
                cm["start_line"], cm["end_line"] = hit
                return True
    return False


def _resolve_from_file_content(d, cm):
    content = d.get("new_file_content") or ""
    if not content:
        return False
    target = split_and_normalize(cm.get("existing_code") or "")
    if not target:
        return False
    lines, nums = [], []
    for i, line in enumerate(content.split("\n")):
        n = normalize_line(line.rstrip("\r"))
        if n:
            lines.append(n)
            nums.append(i + 1)
    for i in range(len(lines) - len(target) + 1):
        if lines[i:i + len(target)] == target:
            cm["start_line"], cm["end_line"] = nums[i], nums[i + len(target) - 1]
            return True
    return False


def resolve_comment(cm, d):
    """ResolveComment: set start_line/end_line from existing_code; True when placed."""
    if (cm.get("start_line") or 0) > 0 or (cm.get("end_line") or 0) > 0:
        return True
    if not cm.get("existing_code"):
        return False
    return _resolve_from_hunk(d, cm) or _resolve_from_file_content(d, cm)


def relocate_across_files(cm, diffs):
    """RelocateAcrossFiles: re-file a comment whose existing_code sits, uniquely,
    in another file's diff. Returns the new path, or None."""
    if not cm.get("existing_code") or not diffs:
        return None
    hits = []
    for d in diffs:
        if d["new_path"] == cm.get("path") or d["old_path"] == cm.get("path"):
            continue
        probe = {**cm, "start_line": 0, "end_line": 0}
        if not resolve_comment(probe, d):
            continue
        hits.append((d["new_path"] or d["old_path"], probe["start_line"], probe["end_line"]))
        if len(hits) > 1:
            return None
    if len(hits) != 1:
        return None
    cm["path"], cm["start_line"], cm["end_line"] = hits[0]
    return hits[0][0]


def resolve_line_numbers(comments, diffs):
    """ResolveLineNumbers: the output pass over the whole comment set."""
    by_path = {}
    for d in diffs:
        if d["new_path"] not in ("/dev/null", ""):
            by_path[d["new_path"]] = d
        if d["old_path"] not in ("/dev/null", ""):
            by_path[d["old_path"]] = d
    out = []
    for c in comments:
        cm = dict(c)
        if (cm.get("start_line") or 0) > 0 or (cm.get("end_line") or 0) > 0 \
                or not cm.get("existing_code"):
            out.append(cm)
            continue
        d = by_path.get(cm.get("path"))
        if d is not None and not _resolve_from_hunk(d, cm):
            _resolve_from_file_content(d, cm)
        out.append(cm)
    return out


def extract_code_block(text):
    """relocation.go extractCodeBlock: the first fenced block's body, trimmed."""
    text = text.strip()
    start = text.find("```")
    if start < 0:
        return ""
    after = start + 3
    nl = text.find("\n", after)
    if nl < 0:
        return ""
    after = nl + 1
    end = text.find("```", after)
    if end < 0:
        return ""
    return text[after:end].strip()


# -- reading the head's files ---------------------------------------------------

def read_new_file_contents(diffs, repo_dir, ref=""):
    """finalizeDiff: each non-deleted, non-binary diff gets its new file's
    content, read at `ref` (`git show`), or from the working tree."""
    for d in diffs:
        if d["is_deleted"] or d["new_path"] == "/dev/null" or d["is_binary"]:
            continue
        try:
            if ref:
                r = subprocess.run(["git", "-c", "core.quotepath=false", "show",
                                    "--end-of-options", f"{ref}:{d['new_path']}"],
                                   cwd=repo_dir, capture_output=True, timeout=60)
                if r.returncode == 0:
                    d["new_file_content"] = r.stdout.decode("utf-8", "replace")
            else:
                with open(f"{repo_dir}/{d['new_path']}", "rb") as fh:
                    d["new_file_content"] = fh.read().decode("utf-8", "replace")
        except (OSError, subprocess.SubprocessError):
            pass
    return diffs
