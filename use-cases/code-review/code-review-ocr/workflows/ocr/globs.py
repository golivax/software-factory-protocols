"""Glob matching as upstream OCR matches paths.

Upstream matches with github.com/bmatcuk/doublestar/v4 (`Match`) and Go's
`path/filepath.Match`, and expands `{a,b}` braces itself in some places
(internal/config/rules/system_rules.go `expandBraces`). This module gives the
same three operations:

  match(pattern, path)   doublestar.Match: `*` and `?` stay inside one path
                          segment, `**` as a whole segment spans zero or more
                          segments, `[...]` classes, `{a,b}` alternatives.
  fnmatch(pattern, path) filepath.Match: no `**`, no braces.
  expand_braces(s)       every alternative of a brace pattern, nested braces
                          included.
"""
import functools
import re


def expand_braces(s):
    """`a/{b,c}.go` -> ["a/b.go", "a/c.go"]; a pattern without braces -> [s]."""
    start = s.find("{")
    if start < 0:
        return [s]
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                inner, prefix, suffix = s[start + 1:i], s[:start], s[i + 1:]
                out = []
                for alt in _split_top_level(inner):
                    out.extend(expand_braces(prefix + alt + suffix))
                return out
    return [s]  # unbalanced: matched literally


def _split_top_level(s):
    parts, depth, cur = [], 0, []
    for c in s:
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        if c == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    parts.append("".join(cur))
    return parts


def _segment_regex(seg):
    """One path segment's glob as a regex that never crosses `/`."""
    out, i, n = [], 0, len(seg)
    while i < n:
        c = seg[i]
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "\\" and i + 1 < n:
            i += 1
            out.append(re.escape(seg[i]))
        elif c == "[":
            j = seg.find("]", i + 2 if i + 1 < n and seg[i + 1] in "!^" else i + 1)
            if j < 0:
                out.append(re.escape(c))
            else:
                body = seg[i + 1:j]
                neg = body[:1] in ("!", "^")
                if neg:
                    body = body[1:]
                body = body.replace("\\", "\\\\")
                out.append(f"[{'^/' if neg else ''}{body}]")
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


@functools.lru_cache(maxsize=4096)
def _compile(pattern, doublestar):
    segs = pattern.split("/")
    out = []
    last = len(segs) - 1
    for i, seg in enumerate(segs):
        if doublestar and seg == "**":
            if i == last:
                out.append(".*" if i == 0 else "(?:/.*)?")
            else:
                out.append("(?:.*/)?" if i == 0 else "/(?:.*/)?")
            continue
        if i > 0 and not (doublestar and segs[i - 1] == "**"):
            out.append("/")
        out.append(_segment_regex(seg))
    return re.compile("".join(out), re.DOTALL)


def match(pattern, path):
    """doublestar.Match(pattern, path), braces included."""
    return any(_compile(p, True).fullmatch(path) for p in expand_braces(pattern))


def fnmatch(pattern, path):
    """filepath.Match(pattern, path) on `/`-separated paths."""
    return bool(_compile(pattern, False).fullmatch(path))
