# Vendored from alibaba/open-code-review

Every file in this directory except this one is copied byte for byte from
[alibaba/open-code-review](https://github.com/alibaba/open-code-review) at commit
`d4f568f71d3a9d5c5ec972791b1509e40cd31ad1` (release v1.14.4 and later), under its
Apache-2.0 license (`LICENSE`, beside this file). Copyright 2026 alibaba/open-code-review
Contributors.

| Here | Upstream |
|---|---|
| `task_template.json` | `internal/config/template/task_template.json` |
| `prompts/*.md` | `internal/config/template/prompts/` (the review's tasks only) |
| `rules/system_rules.json`, `rules/rule_docs/` | `internal/config/rules/` |
| `allowlist/*.json` | `internal/config/allowlist/` |
| `toolsconfig/tools.json` | `internal/config/toolsconfig/tools.json` |

The Python beside this directory (`workflows/ocr/`, `workflows/*.py`) is a port
of upstream's Go code at the same commit; each module names the files it ports.

## Moving to a newer upstream

1. Copy the files in the table above from the new commit, and update the commit here.
2. Regenerate the oracle's answers. The oracle is a set of Go test files that run
   upstream's own functions on the cases in `tests/golden/cases.json`. Copy
   `tests/golden/oracle/{diff,rules,agent,tool}_oracle_test.go.txt` into the upstream
   checkout as `zz_oracle_test.go` of `internal/diff`, `internal/config/rules`,
   `internal/agent` and `internal/tool`, then:

   ```bash
   python3 tests/golden/oracle/gen_cases.py /tmp/cases.json
   cd <upstream checkout>
   for pkg in diff config/rules agent tool; do
     OCR_ORACLE_IN=/tmp/cases.json OCR_ORACLE_OUT=/tmp/upstream_$(echo $pkg | tr / _).json \
       LC_ALL=C go test ./internal/$pkg/ -run '^TestOracle$' -count=1
   done
   ```

   Copy `/tmp/cases.json` and the four `/tmp/upstream_*.json` into `tests/golden/`.
3. Run the protocol's tests: a failing parity test is a behaviour upstream changed,
   to port.
