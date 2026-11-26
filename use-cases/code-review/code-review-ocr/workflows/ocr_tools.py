#!/usr/bin/env python3
"""Upstream OCR's four context tools, for the review agent to call from its shell.

    python3 ocr_tools.py <tool> '<arguments as JSON>'

<tool> is code_search | file_read | file_read_diff | file_find, with the
arguments of upstream's tool definitions (toolsconfig/tools.json); the output is
what upstream's tool returns to the model (internal/tool/{code_search,
file_read,file_read_diff,file_find}.go), errors included. Files are read from
the repository in the current directory at the run's commit when the checkout
holds it (upstream's range mode reads `--to` the same way), else from the
working tree. Self-contained: it is copied next to the prompt.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GREP_MAX = 100
READ_MAX_LINES = 500
READ_MAX_LINE_BYTES = 2048
READ_MAX_RESULT_BYTES = 256 * 1024
FIND_MAX = 100
DIFF_NOT_FOUND_MAX_LISTED = 10
KEEP_EXTENSIONLESS = {"Makefile", "Dockerfile", "LICENSE", "Vagrantfile", "Containerfile",
                      "BUILD", "WORKSPACE"}


class ToolError(Exception):
    """An error upstream returns as a Go error: the model reads
    `Error executing tool <name>: <message>`."""


def _git(args, timeout=10):
    return subprocess.run(["git", *args], cwd=os.getcwd(), capture_output=True, timeout=timeout)


def _commit(key):
    """pr.json's `key` commit, when the checkout holds it."""
    try:
        with open(os.path.join(HERE, "pr.json"), encoding="utf-8") as fh:
            sha = (json.load(fh) or {}).get(key) or ""
    except (OSError, ValueError):
        sha = ""
    if sha and not sha.startswith("-") and _git(["cat-file", "-e", f"{sha}^{{commit}}"]).returncode == 0:
        return sha
    return ""


# -- code_search ---------------------------------------------------------------

def code_search(args, ref):
    text = args.get("search_text") if isinstance(args.get("search_text"), str) else ""
    case = args.get("case_sensitive") is True
    perl = args.get("use_perl_regexp") is True
    patterns = []
    for p in args.get("file_patterns") or []:
        if isinstance(p, str) and p:
            if ".." in p.replace("\\", "/").split("/"):
                return "Error: file_patterns must not contain .."
            patterns.append(p.replace("\\", "/"))
    if not text.strip():
        return "Error: search_text is blank"
    cmd = ["--no-pager", "-c", "core.quotepath=false", "grep", "-I"]
    if not ref:
        cmd.append("--untracked")
    if not case:
        cmd.append("-i")
    cmd += ["-P" if perl else "-F", "-n", "--no-color", "--max-count", str(GREP_MAX + 1), "-e", text]
    if ref:
        cmd.append(ref)
    cmd += ["--", *patterns]
    try:
        r = _git(cmd)
    except subprocess.TimeoutExpired:
        raise ToolError("git grep timed out; try narrowing file_patterns to a more specific path: "
                        "context deadline exceeded")
    out, err = r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")
    if r.returncode != 0 and not out:
        if not err and r.returncode == 1:
            return "No matches found"
        msg = err.strip()
        if r.returncode == 129 and "\n" in msg:
            msg = msg.split("\n", 1)[0].strip()
        if not msg:
            raise ToolError(f"git grep failed: exit status {r.returncode}")
        if perl and r.returncode == 128:
            msg += ("; fix the regular expression (e.g. use \\( for a literal opening parenthesis), "
                    "or set use_perl_regexp=false to search for the entire text literally")
        raise ToolError(f"git grep failed: exit status {r.returncode}: {msg}")
    order, matches, files, count, truncated = [], {}, set(), 0, False
    split_n, off = (4, 1) if ref else (3, 0)
    for line in out.rstrip("\n").split("\n"):
        if not line:
            continue
        parts = line.split(":", split_n - 1)
        if len(parts) < split_n:
            continue
        name = parts[off]
        try:
            num = int(parts[off + 1])
        except ValueError:
            continue
        files.add(name)
        if count >= GREP_MAX:
            truncated = True
            continue
        if name not in matches:
            order.append(name)
            matches[name] = []
        matches[name].append((num, parts[off + 2]))
        count += 1
    res = []
    if truncated:
        res.append(f"Note: Showing the first {GREP_MAX} matches across {len(files)} matching files. "
                   "Some files are partially shown or omitted entirely. Narrow file_patterns to see the rest.\n")
    for name in order:
        res.append(f"File: {name}\nMatch lines: {len(matches[name])}\n")
        res.extend(f"{n}|{c}\n" for n, c in matches[name])
        res.append("\n")
    if r.returncode != 0 and err:
        res.append(f"Warning: {err.strip()}\n")
    return "".join(res)


# -- file_read -----------------------------------------------------------------

def _read_file(path, ref):
    if ref:
        r = _git(["-c", "core.quotepath=false", "show", "--end-of-options", f"{ref}:{path}"], timeout=30)
        if r.returncode != 0:
            raise OSError(f"git show {ref}:{path}: exit status {r.returncode}")
        return r.stdout.decode("utf-8", "replace")
    root = os.path.realpath(os.getcwd())
    full = os.path.realpath(os.path.join(root, path))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        raise OSError(f'read file "{path}": no such file or directory')
    with open(full, "rb") as fh:
        return fh.read().decode("utf-8", "replace")


def scan_lines(content):
    """filereader.go scanLines: every line, `\\r\\n` trimmed, and one more, empty,
    when the content ends with a newline."""
    parts = content.split("\n")
    lines = [p[:-1] if p.endswith("\r") else p for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1][:-1] if parts[-1].endswith("\r") else parts[-1])
    elif content:
        lines.append("")
    return lines


def _cap_line(s):
    b = s.encode("utf-8")
    if len(b) <= READ_MAX_LINE_BYTES:
        return s, False
    cut = READ_MAX_LINE_BYTES
    while cut > 0 and (b[cut] & 0xC0) == 0x80:
        cut -= 1
    return f"{b[:cut].decode('utf-8', 'replace')} …[line truncated, {len(b) - cut} more bytes omitted]", True


def file_read(args, ref):
    path = args.get("file_path") if isinstance(args.get("file_path"), str) else ""
    if not path:
        return "Error: file_path is required"
    start = args.get("start_line")
    end = args.get("end_line")
    start = int(start) if isinstance(start, (int, float)) and not isinstance(start, bool) and start > 0 else 1
    end = int(end) if isinstance(end, (int, float)) and not isinstance(end, bool) and end > 0 else 0
    max_lines = READ_MAX_LINES
    if end > 0:
        requested = end - start + 1
        if requested <= 0:
            raise ToolError(f"invalid line range: start_line {start} is greater than end_line {end}")
        max_lines = min(max_lines, requested)
    try:
        content = _read_file(path, ref)
    except OSError as e:
        raise ToolError(f'file "{path}" not found: {e}')
    all_lines = scan_lines(content)
    total = len(all_lines)
    if total > 0 and start - 1 >= total:
        raise ToolError(f'file "{path}" has only {total} lines, requested range {start}-{end}')
    lines = all_lines[start - 1:start - 1 + max_lines]
    effective_end = min(end, total) if end > 0 else total
    full_range = effective_end - (start - 1)
    body, shown, size, line_cut, out_cut = [], 0, 0, False, False
    for i, line in enumerate(lines):
        text, cut = _cap_line(line)
        entry = f"{start + i}|{text}\n"
        if size > 0 and size + len(entry.encode("utf-8")) > READ_MAX_RESULT_BYTES:
            out_cut = True
            break
        line_cut = line_cut or cut
        size += len(entry.encode("utf-8"))
        shown = i + 1
        body.append(entry)
    truncated = full_range > READ_MAX_LINES or line_cut or out_cut
    res = [f"File: {path} (Total lines: {total})\n", f"IS_TRUNCATED: {'true' if truncated else 'false'}\n",
           f"LINE_RANGE: {start}-{start - 1 + shown}\n", *body]
    if line_cut:
        res.append(f"\nNote: Lines longer than {READ_MAX_LINE_BYTES} bytes were cut mid-line and the omitted "
                   "bytes are not part of this result. Reason about the visible part only.\n")
    if out_cut:
        res.append(f"\nNote: Output truncated at {READ_MAX_RESULT_BYTES} bytes. Re-read the remaining lines "
                   "with a narrower start_line/end_line range.\n")
    if full_range > READ_MAX_LINES:
        res.append(f"\nNote: Results truncated to {READ_MAX_LINES} lines. Please narrow your line range.\n")
    return "".join(res)


# -- file_read_diff ------------------------------------------------------------

def file_read_diff(args, _ref):
    try:
        with open(os.path.join(HERE, "ocr-diffmap.json"), encoding="utf-8") as fh:
            diffmap = json.load(fh)
    except (OSError, ValueError):
        diffmap = {}
    paths = args.get("path_array") or []
    if not isinstance(paths, list) or not paths:
        return "Error: no files found"
    res, missing = [], []
    for p in paths:
        if not isinstance(p, str):
            continue
        if p in diffmap:
            res.append(f"==== FILE: {p} ====\n{diffmap[p]}\n")
        else:
            missing.append(p)
    if missing:
        if res:
            res.append("\n")
        res.append("Error: diff not found for: " + ", ".join(missing) + "\n")
        available = sorted(diffmap)
        if not available:
            res.append("This run has no diffs. Read the file with file_read instead.\n")
        else:
            listed = available[:DIFF_NOT_FOUND_MAX_LISTED]
            rest = len(available) - len(listed)
            res.append("Diffs exist for: " + ", ".join(listed) + (f" (and {rest} more)" if rest > 0 else ""))
            res.append("\nUse one of those paths, or file_read for a file outside the reviewed set.\n")
    out = "".join(res)
    return out or "Error: diff not found for the requested paths"


# -- file_find -----------------------------------------------------------------

def _skip(path):
    base = path.rsplit("/", 1)[-1]
    return "." not in base and base not in KEEP_EXTENSIONLESS


def file_find(args, ref):
    query = args.get("query_name") if isinstance(args.get("query_name"), str) else ""
    if not query.strip():
        return "// The file was not found"
    case = args.get("case_sensitive") is True
    cmd = (["-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "--end-of-options", ref] if ref
           else ["-c", "core.quotepath=false", "ls-files", "--cached", "--others", "--exclude-standard"])
    r = _git(cmd)
    if r.returncode != 0:
        raise ToolError(r.stderr.decode("utf-8", "replace").strip() or "git ls-files failed")
    files = [f for f in r.stdout.decode("utf-8", "replace").rstrip("\n").split("\n") if f and not _skip(f)]
    q = query.replace("\\", "/")
    q = q if case else q.lower()
    matched = [f for f in files if q in (f.rsplit("/", 1)[-1] if case else f.rsplit("/", 1)[-1].lower())][:FIND_MAX]
    if not matched:
        matched = [f for f in files if q in (f if case else f.lower())][:FIND_MAX]
    return "\n".join(matched) if matched else "// The file was not found"


TOOLS = {"code_search": code_search, "file_read": file_read,
         "file_read_diff": file_read_diff, "file_find": file_find}
SIDE_TOOLS = ("code_search", "file_read", "file_find")


def run_tool(name, args):
    """CodeAccess.execute: `side` picks the reviewed commit (new, the default)
    or the comparison base (old); an old-side answer or error is prefixed."""
    if name not in SIDE_TOOLS:
        return TOOLS[name](args, "")
    side = args.get("side", "new")
    if side not in ("new", "old"):
        raise ToolError("side must be new or old")
    if side == "new":
        return TOOLS[name](args, _commit("head_sha"))
    base = _commit("base_sha")
    prefix = f"SIDE: old\nREVISION: {base}\n"
    if not base:
        raise ToolError(prefix + "the comparison base is not in this checkout")
    try:
        return prefix + TOOLS[name](args, base)
    except ToolError as e:
        raise ToolError(prefix + str(e))


STREAKS = os.path.join(HERE, "ocr-tool-streaks.json")


def _streak(name, failed):
    """reviewtask's tool failure streak: consecutive failures of one tool,
    reset by its next success."""
    try:
        with open(STREAKS, encoding="utf-8") as fh:
            counts = json.load(fh)
    except (OSError, ValueError):
        counts = {}
    counts[name] = counts.get(name, 0) + 1 if failed else 0
    try:
        with open(STREAKS, "w", encoding="utf-8") as fh:
            json.dump(counts, fh)
    except OSError:
        pass
    return counts[name]


def failure_result(name, message):
    """toolFailureResult."""
    n = _streak(name, True)
    if n == 1:
        return message
    if n == 2:
        return (f"{message}\nThis is the second consecutive failure calling {name} for this task. "
                "Fix your arguments, or call task_done if you have nothing further to report.")
    return (f"{name} has failed repeatedly for this task and has been skipped; it will not be retried "
            "further. Move on to your next finding, or call task_done if you have nothing further to report.")


def main(argv):
    if len(argv) < 2 or argv[1] not in TOOLS:
        print("Error: tool not available. Use one of: " + ", ".join(TOOLS))
        return 0
    name = argv[1]
    try:
        args = json.loads(argv[2]) if len(argv) > 2 else {}
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
    except ValueError as e:
        print(failure_result(name, f"Error parsing tool arguments for {name}: {e}"))
        return 0
    try:
        out = run_tool(name, args)
    except ToolError as e:
        print(failure_result(name, f"Error executing tool {name}: {e}"))
        return 0
    _streak(name, False)
    print(out, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
