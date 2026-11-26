"""Review rules and the user's file filter, as upstream OCR resolves them.

Ported from internal/config/rules/{system_rules,sniffer}.go. Layers, highest
first: the custom rule file (`ocr review --rule`, this protocol's `rule`
input), the repository's `.opencodereview/rule.json`, then the system rules
(upstream/rules/system_rules.json and its rule_docs/, the `.m` Objective-C
sniff on top). A user's home `~/.opencodereview/rule.json` has no
counterpart in a factory run.
"""
import json
import os
import subprocess

from . import globs

UPSTREAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upstream")
RULE_FILE_EXTS = (".md", ".txt", ".markdown")
RULE_FILE_MAX = 512 * 1024
OBJC_SNIFF_PREFIXES = ("#import", "#include", "#pragma", "#if", "#define",
                       "@import", "@interface", "@implementation", "@class", "@protocol",
                       "//", "/*")


def _rule_doc(name):
    with open(os.path.join(UPSTREAM, "rules", "rule_docs", name), encoding="utf-8") as fh:
        return fh.read().rstrip("\n")


def load_system_rules():
    """(default rule text, [(pattern, rule text)] in file order)."""
    with open(os.path.join(UPSTREAM, "rules", "system_rules.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    return (_rule_doc(doc["default_rule"]),
            [(pat, _rule_doc(name)) for pat, name in doc.get("path_rule_map", {}).items()])


def looks_like_objc(first_line):
    return bool(first_line) and first_line.startswith(OBJC_SNIFF_PREFIXES)


def first_non_blank_line(content):
    content = content.removeprefix("﻿")
    for line in content.split("\n"):
        if line.strip():
            return line.strip()
    return ""


def _read_rule_file(rule, repo_dir):
    """tryReadRuleFile + readRuleFileSafe: a path relative to the repository,
    confined to it, .md/.txt/.markdown, at most 512 KB."""
    if os.path.isabs(rule) or not repo_dir:
        return None
    root = os.path.realpath(repo_dir)
    resolved = os.path.realpath(os.path.join(repo_dir, rule))
    if not resolved.startswith(root + os.sep):
        return None
    if os.path.splitext(resolved)[1].lower() not in RULE_FILE_EXTS:
        return None
    try:
        if os.path.getsize(resolved) > RULE_FILE_MAX:
            return None
        with open(resolved, encoding="utf-8") as fh:
            return fh.read().rstrip("\n")
    except OSError:
        return None


def _looks_like_file_path(s):
    return ("\n" not in s and " " not in s
            and os.path.splitext(s)[1].lower() in RULE_FILE_EXTS)


def load_project_rule(path, repo_dir):
    """A rule.json layer, its `rule` file references read, or None."""
    try:
        real = os.path.realpath(path)
        if repo_dir and not real.startswith(os.path.realpath(repo_dir) + os.sep):
            return None
        with open(real, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    entries = []
    for e in doc.get("rules") or []:
        if not isinstance(e, dict):
            continue
        entry = {"path": str(e.get("path") or ""), "rule": str(e.get("rule") or ""),
                 "merge_system_rule": bool(e.get("merge_system_rule"))}
        if entry["rule"].strip() and _looks_like_file_path(entry["rule"]):
            entry["rule"] = _read_rule_file(entry["rule"], repo_dir) or ""
        entries.append(entry)
    return {"rules": entries,
            "include": [str(p) for p in doc.get("include") or []],
            "exclude": [str(p) for p in doc.get("exclude") or []]}


class Resolver:
    """composedResolver: custom > project > system (with the `.m` sniff)."""

    def __init__(self, repo_dir="", custom_rule_path="", ref=""):
        self.repo_dir, self.ref = repo_dir, ref
        self.default_rule, self.path_rules = load_system_rules()
        self.objc_rule = _rule_doc("objc.md")
        self.layers = []
        if custom_rule_path and repo_dir:
            self.layers.append(load_project_rule(os.path.join(repo_dir, custom_rule_path), repo_dir))
        if repo_dir:
            self.layers.append(load_project_rule(
                os.path.join(repo_dir, ".opencodereview", "rule.json"), repo_dir))
        self.layers = [layer for layer in self.layers if layer]

    # -- the file filter ------------------------------------------------------
    def file_filter(self):
        """buildFileFilter: the highest layer that sets include or exclude."""
        for layer in self.layers:
            if layer["include"] or layer["exclude"]:
                return {"include": [p.lower() for p in layer["include"]],
                        "exclude": [p.lower() for p in layer["exclude"]]}
        return None

    # -- rule text ------------------------------------------------------------
    def _system(self, path):
        if path.lower().endswith(".m") and looks_like_objc(self._peek_first_line(path)):
            return self.objc_rule
        lower = path.lower()
        for pattern, rule in self.path_rules:
            if globs.match(pattern.lower(), lower):
                return rule
        return self.default_rule

    def _peek_first_line(self, path):
        if not self.repo_dir:
            return ""
        try:
            if self.ref:
                r = subprocess.run(["git", "-c", "core.quotepath=false", "show",
                                    "--end-of-options", f"{self.ref}:{path}"],
                                   cwd=self.repo_dir, capture_output=True, timeout=5)
                return first_non_blank_line(r.stdout.decode("utf-8", "replace")) \
                    if r.returncode == 0 else ""
            with open(os.path.join(self.repo_dir, path), encoding="utf-8", errors="replace") as fh:
                return first_non_blank_line(fh.read(65536))
        except (OSError, subprocess.SubprocessError):
            return ""

    def resolve(self, path):
        lower = path.lower()
        for layer in self.layers:
            for entry in layer["rules"]:
                if not entry["rule"] and not entry["merge_system_rule"]:
                    continue
                if globs.match(entry["path"].lower(), lower):
                    if entry["merge_system_rule"]:
                        return self._merge(path, entry["rule"])
                    return entry["rule"]
        return self._system(path)

    def _merge(self, path, rule):
        system = self._system(path)
        if not system:
            return rule
        if not rule:
            return system
        return ("## System-Specific Rules (Mandatory)\n\n" + system + "\n\n---\n\n"
                "## User-Specific Rules (Mandatory)\n\n" + rule)


def resolve_group_rule(resolver, diffs):
    """resolveGroupSystemRule: one block per distinct rule text, tagged with its
    files when the group spans more than one."""
    blocks, index = [], {}
    for d in sorted(diffs, key=lambda d: d["new_path"]):
        rule = resolver.resolve(d["new_path"])
        if not rule:
            continue
        if rule in index:
            blocks[index[rule]][1].append(d["new_path"])
            continue
        index[rule] = len(blocks)
        blocks.append((rule, [d["new_path"]]))
    if not blocks:
        return ""
    if len(blocks) == 1:
        return blocks[0][0]
    return "\n".join(f'<rules for="{", ".join(paths)}">\n{rule}\n</rules>' for rule, paths in blocks)
