# software-factory-protocols

The protocol library for the [software-factory](https://github.com/golivax/software-factory)
engine: every protocol we ship, as a **source-only** package you copy into a repo the
factory watches. The engine repo consumes this one as a git submodule at `protocols/`
(its test suite walks these protocols), so a change here is picked up by the engine by
bumping the submodule pointer.

## Layout

```
commons/workflows/          agent units shared by more than one protocol
demo/                       the end-to-end demo packages (see the engine repo's docs/DEMO.md)
  demo/  grumpy/  hello/  toy/
use-cases/                  real protocols, grouped by what they are for
  code-cleanup/duplicate-code-remover/
  code-review/code-review/
  code-review/code-review-ocr/
  feature-implementation/impl-feature-auto/
  mental-model/recover-mental-model/
  mental-model/recover-mental-model-interactive/
.github/aw/actions-lock.json   gh-aw's action pin table (used by `gh aw compile`)
```

Every protocol directory is one self-contained package with the shape the factory's
`ProtocolFetch` expects:

```
<name>/
  README.md                  what it does, triggers, states, units, how to install
  protocol.json              states, checks, transitions (DATA — the engine interprets it)
  *.evidence.schema.json     the rubric each agent must fill (the CONTRACT)
  checks/                    deterministic checks (any language)
  scripts/                   inline `code` node bodies + trusted `conclude` hooks
  expand/                    dynamic fan-out expanders (where used)
  workflows/                 the dispatched units: `<wf>.md` (gh-aw agent SOURCE)
                             or `<wf>.yml` (a plain GitHub-Actions workflow, code lane)
```

The nested `demo/` and `use-cases/<category>/` grouping is for browsing only. The
factory resolves packages by **directory name** under a flat
`<repo>/.softwarefactory/protocols/<name>/`, with `commons/` beside them — so install a
protocol by copying its directory (and `commons/` if its README says so) to that path.

## gh-aw version

Agent units are gh-aw markdown sources. **Only the `.md` is committed; the compiled
`*.lock.yml` is not** (`.gitignore` refuses it). The factory runs the compiled lock, so
compile before you install:

| tool | version |
|---|---|
| `gh aw` (the gh-aw compiler extension) | **v0.89.0** |
| gh-aw-firewall (selected by that compiler) | v0.28.14 |

```bash
gh extension install github/gh-aw@v0.89.0     # or: gh extension upgrade gh-aw
gh aw compile --dir use-cases/code-review/code-review/workflows
# → <unit>.lock.yml beside each <unit>.md
```

`--dir` points at a package's `workflows/` directory; `.github/aw/actions-lock.json`
at this repo's root supplies the pinned action SHAs. This is the version the engine's
runtime substrate is adapted to (the lock transforms in the engine repo's
`runtime/factory/tools/run_under_act/` are anchored on v0.89.0 output — see
`docs/compatibility/COMPATIBILITY.md` there). A newer compiler may produce locks the
substrate does not recognise; bump both together.

A unit that `{{#runtime-import}}`s `shared/skill-preamble.md` carries that file under
its own `workflows/shared/` (the dispatcher copies a package's whole `workflows/` dir
next to the unit, nothing else).

## Status

`demo/hello`, `demo/toy`, `demo/demo` and `demo/grumpy` are verified live on the
deployed factory. The `use-cases/` protocols were ported from the engine's
GitHub-Actions era and have **not** been re-verified on the deployed service: their
units still reference in-repo `.github/agent-factory/...` paths and some checks assume
that layout. They are kept here as the engine's regression corpus and as reference
packages; bringing each one back to life is tracked as follow-up work in the engine
repo. Each protocol's README states its own status.

## Authoring

The DSL, the check ABI and the trust zones are documented in the engine repo under
`docs/engine/` (`PROTOCOL-DSL.md`, `AUTHORING.md`, `HOW-IT-WORKS.md`). The authoring
schema is `engine/protocol.schema.json` there; lint a package with

```bash
python3 <software-factory>/engine/protocol_lint.py <name>/protocol.json
```
