# AGENTS.md — data-tools-skill

## Repo Structure

```
.
├── skills/data-tools/
│   ├── SKILL.md                        # Main skill definition
│   └── references/
│       ├── jq-cookbook.md               # jq patterns and recipes
│       ├── yq-cookbook.md               # YAML manipulation patterns
│       ├── dasel-cookbook.md            # TOML/XML/universal selector patterns
│       └── csv-processing.md           # qsv workflows and recipes
├── .github/workflows/                  # CI workflows
├── composer.json                       # PHP package metadata
├── docs/                               # Architecture and planning docs
│   ├── ARCHITECTURE.md
│   └── exec-plans/
├── scripts/
│   └── verify-harness.sh              # Harness verification script
└── README.md
```

## Commands

No Makefile or build scripts. This is a documentation-only skill repo.

- `bash scripts/verify-harness.sh --format=text --status` — check harness maturity level

## Rules

1. **NEVER use `grep`, `sed`, or `awk` on JSON, YAML, TOML, XML, or CSV data** — use the format-specific tool instead.
2. **Tool selection by format**: JSON → `jq`, YAML → `yq`, TOML/XML → `dasel`, CSV → `qsv`.
3. **GitHub CLI output**: always use `gh --jq` flag directly, never pipe to `jq`.
4. **One format, one file**: use format-specific tool. Multiple formats or TOML/XML: use `dasel`.

## References

- [SKILL.md](skills/data-tools/SKILL.md) — full skill definition and tool selection guide
- [jq Cookbook](skills/data-tools/references/jq-cookbook.md) — JSON query/transform patterns
- [yq Cookbook](skills/data-tools/references/yq-cookbook.md) — YAML manipulation patterns
- [dasel Cookbook](skills/data-tools/references/dasel-cookbook.md) — TOML/XML/universal patterns
- [CSV Processing](skills/data-tools/references/csv-processing.md) — qsv workflows and recipes
