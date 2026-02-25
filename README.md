# data-tools-skill

AI agent skill for structured data manipulation. Teaches agents when and how to use dedicated tools instead of fragile text processing (grep/sed/awk) on structured formats.

## Tools Covered

| Tool | Format | Use Case |
|------|--------|----------|
| [jq](https://jqlang.github.io/jq/) | JSON | Query, filter, transform JSON data |
| [yq](https://github.com/mikefarah/yq) | YAML | Edit CI configs, docker-compose, K8s manifests |
| [dasel](https://github.com/TomWright/dasel) | JSON/YAML/TOML/XML | Universal selector, format conversion |
| [qsv](https://github.com/jqnatividad/qsv) | CSV/TSV | Fast data exploration, filtering, analysis |

## Core Principle

**Never use `grep`, `sed`, or `awk` on JSON, YAML, TOML, XML, or CSV data.** These tools treat structured data as flat text and break on multi-line values, nested structures, quoted strings, and encoding differences.

## Installation

Requires [netresearch/composer-agent-skill-plugin](https://github.com/netresearch/composer-agent-skill-plugin).

```bash
composer require netresearch/agent-data-tools
```

## Structure

```
skills/data-tools/
  SKILL.md                       # Main skill file (tool selection, patterns, anti-patterns)
  references/
    jq-cookbook.md                # Comprehensive jq patterns
    yq-cookbook.md                # YAML manipulation patterns
    csv-processing.md            # qsv workflows and recipes
```

## License

MIT
