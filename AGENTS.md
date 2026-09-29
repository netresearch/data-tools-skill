<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# AGENTS.md — data-tools-skill

## Repo Structure

```
.
├── skills/data-tools/
│   ├── SKILL.md                        # Main skill definition
│   ├── evals/evals.json                # Eval definitions (structure checked in CI)
│   └── references/
│       ├── jq-cookbook.md               # jq patterns and recipes
│       ├── yq-cookbook.md               # YAML manipulation patterns
│       ├── dasel-cookbook.md            # TOML/XML/universal selector patterns
│       ├── csv-processing.md           # qsv workflows and recipes
│       ├── mlr-cookbook.md              # Miller (JSONL, DSL, stats, joins)
│       └── enforcement-hook.md          # What the PreToolUse gate denies, warns about, lets through
├── .github/workflows/                  # CI: lint, tests, eval-validate, security, harness-verify, template drift, release
├── Build/                              # check-plugin-version.sh and the pre-push hook
├── composer.json                       # PHP package metadata
├── docs/                               # Architecture and planning docs
│   ├── ARCHITECTURE.md
│   ├── SECURITY-ASSURANCE.md
│   └── exec-plans/
├── hooks/hooks.json                    # Registers the PreToolUse gate (ships with the plugin)
├── scripts/
│   ├── pre_bash_structured_warn.py    # The gate: denies text-tool extraction from structured files
│   ├── test_pre_bash_structured_warn.py  # Its case list — run it after touching the gate
│   └── verify-harness.sh              # Harness verification script
└── README.md
```

## Commands

No Makefile or build scripts.

- `python3 scripts/test_pre_bash_structured_warn.py` — case list for the PreToolUse gate; run after any change to it.

- `bash scripts/verify-harness.sh --format=text --status` — check harness maturity level

## Rules

1. **NEVER use `grep`, `sed`, or `awk` on JSON, YAML, TOML, XML, or CSV data** — use the format-specific tool instead.
2. **Tool selection by format**: JSON → `jq`, JSONL → `mlr`, YAML → `yq`, TOML/XML → `dasel`, CSV → `qsv` (or `mlr` for cross-format / DSL transforms).
3. **GitHub CLI output**: always use `gh --jq` flag directly, never pipe to `jq`.
4. **One format, one file**: use format-specific tool. Multiple formats or TOML/XML: use `dasel`.

## References

- [SKILL.md](skills/data-tools/SKILL.md) — full skill definition and tool selection guide
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, actors, the hook's data flow
- [docs/SECURITY-ASSURANCE.md](docs/SECURITY-ASSURANCE.md) — security assurance case: threats, trust boundaries, limits
- [jq Cookbook](skills/data-tools/references/jq-cookbook.md) — JSON query/transform patterns
- [yq Cookbook](skills/data-tools/references/yq-cookbook.md) — YAML manipulation patterns
- [dasel Cookbook](skills/data-tools/references/dasel-cookbook.md) — TOML/XML/universal patterns
- [CSV Processing](skills/data-tools/references/csv-processing.md) — qsv workflows and recipes
- [mlr Cookbook](skills/data-tools/references/mlr-cookbook.md) — Miller for JSONL, DSL, stats, joins, in-place editing
