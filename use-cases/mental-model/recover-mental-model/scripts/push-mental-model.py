#!/usr/bin/env python3
"""Merge hook for the `combine` state of recover-mental-model.

Collects the four method outputs (legion-map, codeset-vibing, ubiquitous-language,
socratic) and pushes them, all at once, into a single orphan `_mental_model` branch
on the target repo — recreated/overwritten every run. Mirrors the layout of
golivax2/yuanrong-datasystem@_mental_model:

    _mental_model/
      METHODS.txt
      legion-map/           <- legion leg tree
      vibed-codeset/        <- codeset leg tree
      ubiquitous-language/  <- domain-modeling leg tree (CONTEXT.md)
      socratic/             <- socratic leg (phase-2) tree

ABI: <hook> <workdir> <instance>
  <workdir>/inputs/{legion,codeset,ubiquitous-language,socratic}/  leg file trees
  (the sibling <leg>.json evidence files are staged too; the checks already
  gated on them, so this hook only needs the trees)
Env: ENGINE_LOCAL, GITHUB_REPOSITORY, FORGE_KIND, PUBLISH_TOKEN,
     MM_TARGET_REMOTE, PR, PR_HEAD_SHA (inherited).

Where the actual file trees come from: the ENGINE stages them. Each leg declares
`outputs: true`, so its unit writes into `$SF_OUTPUTS_DIR`, the engine collects
that directory off the sandbox before teardown, and `inputs[].from` naming the leg
hands this hook its own copy at `inputs/<as>/` beside the evidence at
`inputs/<as>.json` (issue #68).

This replaced a `gh run download -n mm-tree-<leg>` per leg, which only ever worked
on github.com: the factory's runner is `act`, whose artifact server is per-run and
in-VM, and the forge behind gh2gl (GitLab/CodeHub) has no Actions artifacts at all.
The legs still upload those artifacts for a human to inspect — they are no longer
the transport.

Prints {"conclusion","summary"} to stdout. This hook runs TRUSTED in zone 4 (NOT a
sandboxed check) — it holds the publish token.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

# Locate the engine so `lib` is importable. $ENGINE_DIR is set by the engine for
# every hook it spawns (lib.hook_base_env / the conclude env); the walk-up is the
# fallback for a hook run by hand or by a harness that is not the engine, and it
# searches rather than guessing a fixed depth -- the package sits at
# `use-cases/<category>/<name>/` in the library but `.softwarefactory/protocols/<name>/`
# in a customer repo, so no single `../../..` is right everywhere.
def _engine_dir():
    d = os.environ.get("ENGINE_DIR")
    if d and os.path.isfile(os.path.join(d, "lib.py")):
        return d
    here = os.path.dirname(os.path.abspath(__file__))
    while True:
        cand = os.path.join(here, "engine")
        if os.path.isfile(os.path.join(cand, "lib.py")):
            return cand
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


_ED = _engine_dir()
if _ED:
    sys.path.insert(0, _ED)
import lib  # noqa: E402

BRANCH = "_mental_model"

# leg name -> (input alias, destination dir in the branch). The alias is what the
# `combine` node's `inputs[].as` calls the leg, which is what names both halves of
# its staging: inputs/<alias>.json and inputs/<alias>/.
LEGS = [
    ("legion", "legion", "legion-map"),
    ("codeset", "codeset", "vibed-codeset"),
    ("ubiquitous-language", "ubiquitous-language", "ubiquitous-language"),
    ("socratic", "socratic", "socratic"),
]

METHOD_LINES = {
    "legion": "legion-map         : claude -p /legion:map  (9thLevelSoftware/legion)",
    "codeset": "vibed-codeset      : python -m codeset .   (codeset-vibing)",
    "ubiquitous-language": "ubiquitous-language: /domain-modeling  (mattpocock/skills)",
    "socratic": "socratic           : /socratic-code-theory-recovery  (LLM-Coding/Semantic-Anchors)",
}


def _local():
    return os.environ.get("ENGINE_LOCAL", "0") == "1"


def _git(cwd, *args, token=None):
    """Run git; never echo the token. Returns CompletedProcess (check=True)."""
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          text=True, capture_output=True)


def _leg_tree(workdir, alias):
    """A leg's collected file tree at `inputs/<alias>/`, or None if it produced none.

    The directory sits beside that leg's evidence at `inputs/<alias>.json`. The two
    halves are independent -- a leg can write a verdict and no files, or the
    reverse -- so a missing tree is a skipped leg here, not an error."""
    d = os.path.join(workdir, "inputs", alias)
    return d if os.path.isdir(d) else None


def _with_credential(url, token, forge):
    """`url` carrying `token` as a git-over-HTTP credential, per forge.

    Same shape the engine's own clone builder uses (service/protocol/fetch.py
    `clone_url`): GitLab and its CodeHub fork accept `oauth2:<token>`, GitHub wants
    `x-access-token:<token>`. Kept OUT of MM_TARGET_REMOTE deliberately — the
    remote is a plain URL an operator can read in a config file and this hook can
    name in an error, and the secret arrives separately in PUBLISH_TOKEN. A URL
    that already carries a credential is returned untouched."""
    if not token:
        return url
    scheme, sep, rest = url.partition("://")
    if not sep or "@" in rest.split("/", 1)[0]:
        return url                                 # not http(s), or already credentialed
    user = "x-access-token" if forge in ("", "github") else "oauth2"
    return f"{scheme}://{user}:{token}@{rest}"


def _target_remote():
    """Authenticated push URL for the orphan branch, or "".

    MM_TARGET_REMOTE is the forge-agnostic seam (the node declares it in `env`):
    any git URL — an internal GitLab over plain http, a CodeHub instance, a bare
    repo on disk in the hook test. Only when it is unset does this fall back to
    deriving a github.com URL from GITHUB_REPOSITORY, which is what this function
    used to do unconditionally — and which silently pushed nowhere useful on every
    non-GitHub deployment, the forges this engine exists to be agnostic about.

    The token is injected here rather than baked into the remote so the two can be
    configured (and logged) separately."""
    forge = os.environ.get("FORGE_KIND", "").strip()
    token = os.environ.get("PUBLISH_TOKEN", "")
    explicit = os.environ.get("MM_TARGET_REMOTE", "").strip()
    if explicit:
        return _with_credential(explicit, token, forge)
    if _local():
        return ""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        return ""
    return _with_credential(f"https://github.com/{repo}.git", token, "github")


def _public_url(remote):
    """`remote` with any embedded credential stripped — safe to print or link."""
    scheme, sep, rest = remote.partition("://")
    if not sep:
        return remote
    host_part, slash, path = rest.partition("/")
    if "@" in host_part:
        host_part = host_part.split("@", 1)[1]
    return f"{scheme}://{host_part}{slash}{path}"


def main():
    workdir = sys.argv[1]
    instance = sys.argv[2] if len(sys.argv) > 2 else ""

    present = []          # (leg, dest_dir, tree_path)
    for leg, inp, dest_dir in LEGS:
        tree = _leg_tree(workdir, inp)
        if tree and os.listdir(tree):
            present.append((leg, dest_dir, tree))
        else:
            sys.stderr.write(f"[push-mm] leg '{leg}' produced no tree — skipping\n")

    if not present:
        print(json.dumps({"conclusion": "neutral",
                          "summary": "No method produced a tree; nothing to push."}))
        return

    remote = _target_remote()
    if not remote:
        print(json.dumps({"conclusion": "neutral",
                          "summary": "No push remote resolved (set MM_TARGET_REMOTE, "
                                     "or GITHUB_REPOSITORY on a github deployment)."}))
        return

    sha = os.environ.get("PR_HEAD_SHA", "") or instance

    # Build a fresh orphan worktree and assemble the three subtrees.
    staging = tempfile.mkdtemp(prefix="mm-branch-")
    try:
        _git(staging, "init", "-q", "-b", BRANCH)
        method_lines = []
        for leg, dest_dir, tree in present:
            shutil.copytree(tree, os.path.join(staging, dest_dir))
            method_lines.append(METHOD_LINES.get(leg, dest_dir))
        with open(os.path.join(staging, "METHODS.txt"), "w") as f:
            f.write("Mental-model recovery methods (one directory each)\n")
            f.write(f"source commit: {sha}\n\n")
            f.write("\n".join(method_lines) + "\n")

        _git(staging, "add", "-A")
        _git(staging, "-c", "user.name=agentic-engine",
             "-c", "user.email=agentic-engine@users.noreply.github.com",
             "commit", "-q", "-m", f"mental model for {sha or instance}")
        # Single overwrite of the orphan branch (no history kept).
        _git(staging, "push", "--force", remote, f"HEAD:{BRANCH}")
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"[push-mm] git failed: {e.stderr}\n")
        print(json.dumps({"conclusion": "failure",
                          "summary": "Failed to push the _mental_model branch."}))
        return
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    legs_done = ", ".join(leg for leg, _, _ in present)
    pr = os.environ.get("PR", "")
    # Derived from the remote that was actually pushed to, credential stripped —
    # not rebuilt from github.com, which on a GitLab deployment linked a URL that
    # does not exist. A non-http remote (the hook test's bare repo on disk) has no
    # browsable form, so the branch name stands alone.
    base = _public_url(remote)
    link = f"{base[:-4] if base.endswith('.git') else base}/tree/{BRANCH}" \
        if base.startswith("http") else BRANCH
    # Ref-targeted runs (UI/workflow_dispatch) have no PR to comment on — status is
    # served by the visibility API; the branch + this verdict are the output.
    if pr:
        lib.post_pr_comment(
            pr, f"🧠 **Mental model recovered** ({legs_done}) — pushed to "
                f"[`{BRANCH}`]({link}).")
    print(json.dumps({"conclusion": "success",
                      "summary": f"Pushed {BRANCH} ({legs_done})."}))


if __name__ == "__main__":
    main()
