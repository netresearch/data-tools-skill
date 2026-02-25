---
name: data-tools
description: "Use when querying, transforming, or editing structured data (JSON, YAML, TOML, XML, CSV). Prefer these tools over grep/sed/awk on structured formats."
---

# Data Tools Skill

## Critical Rule

**NEVER use `grep`, `sed`, or `awk` on JSON, YAML, TOML, XML, or CSV data.**

These text-processing tools treat structured data as flat text. They break on multi-line values, nested structures, quoted strings containing delimiters, and field reordering. Use the right tool for the format.

---

## Tool Selection Guide

| Format           | Tool       | Notes                                        |
|------------------|------------|----------------------------------------------|
| JSON             | **jq**     | Or `gh --jq` for GitHub CLI output           |
| YAML             | **yq**     | Same jq-like syntax, in-place editing         |
| TOML             | **dasel**  | Native TOML support                           |
| XML              | **dasel**  | Or `xmlstarlet` for XPath                     |
| CSV / TSV        | **qsv**    | Fast, memory-efficient, purpose-built         |
| Mixed / multiple | **dasel**  | Universal selector, auto-detects format       |

**Quick decision:**
- One format, one file? Use the format-specific tool (jq/yq/qsv).
- Multiple formats or TOML/XML? Use dasel.
- GitHub CLI output? Use `gh --jq` flag directly (never pipe to jq).

---

## Quick Examples

### jq -- JSON

```bash
jq -r '.version' package.json
jq '.users[] | select(.role == "admin")' users.json
jq '.version = "2.0.0"' pkg.json > pkg.json.tmp && mv pkg.json.tmp pkg.json
```

### yq -- YAML

```bash
yq '.services.web.image' docker-compose.yml
yq -i '.jobs.test.strategy.matrix.php-version = ["8.2", "8.3", "8.4"]' .github/workflows/ci.yml
```

### dasel -- TOML / XML / Universal

```bash
dasel -f Cargo.toml '.package.version'
dasel put -f config.json -t string -v "localhost" '.database.host'
dasel -f input.json -w yaml
```

### qsv -- CSV / TSV

```bash
qsv headers data.csv && qsv stats data.csv --everything | qsv table
qsv search -s status "active" users.csv | qsv select name,email
```

### GitHub CLI -- always use --jq

```bash
gh api repos/owner/repo/releases --jq '.[0].tag_name'
gh pr list --json number,title --jq '.[] | "\(.number)\t\(.title)"'
```

---

## Anti-Patterns

```bash
# BAD: grep/sed on JSON (breaks on formatting, nesting, escapes)
grep '"version"' package.json | sed 's/.*: "\(.*\)".*/\1/'
# GOOD:
jq -r '.version' package.json
```

```bash
# BAD: sed on YAML (ignores indentation, multi-line values)
sed -i 's/image: node:.*/image: node:20/' docker-compose.yml
# GOOD:
yq -i '.services.app.image = "node:20"' docker-compose.yml
```

```bash
# BAD: awk on CSV (breaks on quoted fields containing commas)
awk -F',' '{print $2}' data.csv
# GOOD:
qsv select 2 data.csv
```

---

## References

| Cookbook | Content |
|---------|---------|
| [jq Cookbook](references/jq-cookbook.md) | Extraction, filtering, transformation, GitHub CLI patterns |
| [yq Cookbook](references/yq-cookbook.md) | YAML editing, GitHub Actions, Docker-Compose, Kubernetes |
| [dasel Cookbook](references/dasel-cookbook.md) | TOML/XML editing, format conversion, universal selector |
| [CSV Processing](references/csv-processing.md) | qsv workflows, joins, stats, large file handling |

External docs: [jq manual](https://jqlang.github.io/jq/manual/) | [yq docs](https://mikefarah.gitbook.io/yq/) | [dasel docs](https://daseldocs.tomwright.me/) | [qsv docs](https://github.com/jqnatividad/qsv#available-commands)
