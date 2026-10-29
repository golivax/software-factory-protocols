# software-factory-protocols

The template library for the [software-factory](https://github.com/golivax/software-factory)
engine: protocol templates (`use-cases/`) and demos (`demo/`), each a **source-only**
protocol package. A customer copies a protocol template into a repository the factory
watches and adapts it as a customer protocol; a demo shows the factory end to end and
backs its canary. The engine repo consumes this one as a git submodule at `protocols/`
(its test suite reads these protocols), so a change here is picked up by the engine by
bumping the submodule pointer. A protocol carries its own unit tests in `tests/` (Python
test dependencies, if any, in `tests/requirements.txt`; only the factory's protocol test
API, `sf_protocol_testing`, is imported) and its scenario walks in `scenarios/`. Run one
protocol's tests from the engine repo with `cd engine && uvx nox -s protocol --
../protocols/<path to the protocol>`, every protocol's with `uvx nox -s protocols`.

## Layout

```
demo/                       the end-to-end demos (see the engine repo's docs/DEMO.md)
  demo/  grumpy/  hello/  toy/
use-cases/                  protocol templates, grouped by what they are for
  code-cleanup/duplicate-code-remover/
  code-review/code-review-ocr/
  feature-implementation/impl-feature-auto/
.github/aw/actions-lock.json   gh-aw's action pin table (used by `gh aw compile`)
```

`code-review`, `recover-mental-model`, `recover-mental-model-interactive` and the
shared `commons/` units they use moved to the factory's default catalogue,
golivax/software-factory-protocols-private: they are factory protocols, which the
factory serves to a target; they are not copied into a repo.

Every protocol directory is one self-contained protocol package with the shape the factory's
`ProtocolFetch` expects:

```
<name>/
  README.md                  what it does, triggers, states, units, how to install
  protocol.json              states, checks, transitions (DATA — the engine interprets it)
  *.evidence.schema.json     the rubric each agent must fill (the CONTRACT)
  checks/                    deterministic checks (any language)
  scripts/                   inline `code` node bodies (deprecated) + trusted `conclude` hooks
  expand/                    dynamic fan-out expanders (where used)
  workflows/                 the dispatched units: `<wf>.md` (gh-aw agent SOURCE)
                             or `<wf>.yml` (a plain GitHub-Actions workflow, code lane)
```

The nested `demo/` and `use-cases/<category>/` grouping is for browsing only. The
factory resolves protocol packages by **directory name** under a flat
`<repo>/.softwarefactory/protocols/<name>/` — so install a protocol by copying its
directory to that path.

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
gh aw compile --dir demo/grumpy/workflows
# → <unit>.lock.yml beside each <unit>.md
```

`--dir` points at a protocol package's `workflows/` directory; `.github/aw/actions-lock.json`
at this repo's root supplies the pinned action SHAs. This is the version the engine's
runtime substrate is adapted to (the lock transforms in the engine repo's
`runtime/factory/tools/run_under_act/` are anchored on v0.89.0 output — see
`docs/compatibility/COMPATIBILITY.md` there). A newer compiler may produce locks the
substrate does not recognise; bump both together.

A unit that `{{#runtime-import}}`s `shared/skill-preamble.md` carries that file under
its own `workflows/shared/` (the dispatcher copies a protocol package's whole `workflows/` dir
next to the unit, nothing else).

## Status

`demo/hello`, `demo/toy`, `demo/demo` and `demo/grumpy` are verified live on the
deployed factory. The `use-cases/` protocols were ported from the engine's
GitHub-Actions era and have **not** been re-verified on the deployed service: their
units still reference in-repo `.github/agent-factory/...` paths and some checks assume
that layout. They are kept here as the engine's regression corpus and as protocol
templates; bringing each one back to life is tracked in golivax/software-factory#269
(re-verify the ported use-case protocols live on microVM-per-job). Each protocol's README states its own status.

## Authoring

The DSL, the check ABI and the trust zones are documented in the engine repo under
`docs/engine/` (`PROTOCOL-DSL.md`, `AUTHORING.md`, `HOW-IT-WORKS.md`). The authoring
schema is `engine/protocol.schema.json` there; lint a protocol with

```bash
python3 <software-factory>/engine/protocol_lint.py <name>/protocol.json
```

### An agent's evidence is its final answer

Every `agent` node's evidence schema is in the **structured-output subset**
(engine 13.0.0; `protocol_lint` refuses a protocol otherwise): the root is
`type: object`; every object has fixed `properties`, all of them `required`, and
`additionalProperties: false`; an optional field is nullable instead
(`type: [T, "null"]`, or `anyOf` with `{"type": "null"}` for an object or array);
only `type`, `properties`, `required`, `additionalProperties`, `items`, `enum`,
`anyOf`, `description` and `title`. What the subset cannot say (a minimum length, a
pattern, a count) is a check's job.

On a `codex` or `claude` engine the factory constrains the agent's final answer to
that schema and hands it to the engine as the evidence. So a prompt says *"call
`noop`, then give your final answer: it IS the evidence"*, and the unit writes no
evidence file and has no post-step to copy one (`demo/demo`, `demo/toy` and the
`use-cases/` agents). A unit whose evidence is not its agent's answer hands it over
itself: the staged-review pattern below (whatever its engine: the factory leaves its
lock alone), and any unit on an engine without native structured output (copilot,
gemini, pi), whose post-step copies the evidence to `evidence-out.json`.

### Agents that write to the forge: stage, check, publish

An agent never writes to the forge itself. When its deliverable is a forge write
(review comments, a review verdict, an MR comment, a pull request, an issue):

1. it **stages** the write (`safe-outputs: staged: true`), so gh-aw validates and
   threat-scans it and writes nothing;
2. a `steps:` entry under `safe-outputs:` hands the staged items, each projected
   onto the evidence schema's fields (values verbatim), plus the reviewed commit to
   the engine as the node's evidence (`{sha, staged}`);
3. the node's evidence schema states which item types and fields are allowed (the
   engine enforces it);
4. checks settle each type's required fields, the counts, and the proposal against
   the MR (right commit, anchors in the diff, …);
5. a **dispatched** `code` node (its own microVM) publishes it, pinned to the
   reviewed commit. Inline `script` nodes are deprecated.

`demo/grumpy` is the reference implementation; copy it. The full rule is in the
engine repo's `docs/engine/AUTHORING.md` ("Agents that write to the forge").
