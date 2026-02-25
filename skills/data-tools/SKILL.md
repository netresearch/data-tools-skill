---
name: data-tools
description: "Use when querying, transforming, or editing structured data (JSON, YAML, TOML, XML, CSV). Prefer these tools over grep/sed/awk on structured formats."
---

# Data Tools Skill

## Critical Rule

**NEVER use `grep`, `sed`, or `awk` on JSON, YAML, TOML, XML, or CSV data.**

These text-processing tools treat structured data as flat text. They break on:
- Multi-line values, nested structures, quoted strings containing delimiters
- Field reordering, whitespace changes, encoding differences
- Edge cases that silently produce wrong results

Use the right tool for the format. Every time.

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

## jq -- JSON Query and Transformation

### Basic Extraction

```bash
# Single field
jq '.name' package.json

# Nested field
jq '.repository.url' package.json

# Array elements
jq '.items[]' response.json

# Array element by index
jq '.items[0]' response.json

# Multiple fields
jq '{name: .name, version: .version}' package.json
```

### Filtering

```bash
# Select matching objects from array
jq '.users[] | select(.role == "admin")' users.json

# Multiple conditions
jq '.items[] | select(.age > 18 and .active == true)' data.json

# Null-safe access
jq '.items[] | select(.email != null)' data.json

# Regex matching
jq '.files[] | select(.name | test("^test.*\\.js$"))' manifest.json
```

### Transformation

```bash
# Map over array
jq '[.items[] | {id: .id, label: .name}]' data.json

# Group by field
jq 'group_by(.category) | map({key: .[0].category, count: length})' items.json

# Sort
jq 'sort_by(.date) | reverse' events.json

# Flatten nested arrays
jq '[.groups[].members[]]' org.json

# Unique values
jq '[.items[].category] | unique' data.json

# Aggregate
jq '[.items[].price] | add' cart.json
```

### In-Place Editing

jq does not support in-place editing natively. Use a temp file pattern:

```bash
# Safe in-place edit with temp file
jq '.version = "2.0.0"' package.json > package.json.tmp && mv package.json.tmp package.json

# Or with sponge (from moreutils)
jq '.version = "2.0.0"' package.json | sponge package.json
```

### GitHub CLI Integration

**Always prefer the `--jq` flag over piping to jq.** It saves a process and is idiomatic.

```bash
# GOOD: --jq flag (preferred)
gh api repos/owner/repo/releases --jq '.[0].tag_name'
gh pr list --json number,title,author --jq '.[] | "\(.number)\t\(.title)\t\(.author.login)"'
gh run list --json status,conclusion --jq '.[] | select(.status == "completed")'

# BAD: piping to jq (wasteful, extra process)
gh api repos/owner/repo/releases | jq '.[0].tag_name'
```

The `--jq` flag works on both `gh api` and structured `gh` commands that support `--json`.

---

## yq -- YAML Query and Transformation

Mike Farah's yq (Go implementation). Same jq-like syntax for YAML.

### Basic Operations

```bash
# Read a field
yq '.services.web.image' docker-compose.yml

# Read nested field
yq '.jobs.build.steps[0].uses' .github/workflows/ci.yml

# List all keys at a level
yq '.services | keys' docker-compose.yml
```

### In-Place Editing

yq supports true in-place editing with `-i`:

```bash
# Set a value
yq -i '.version = "3.0.0"' chart.yaml

# Add an element to an array
yq -i '.services.web.ports += ["8080:8080"]' docker-compose.yml

# Delete a field
yq -i 'del(.services.debug)' docker-compose.yml

# Set nested value (creates intermediate keys)
yq -i '.jobs.test.env.CI = "true"' .github/workflows/ci.yml
```

### GitHub Actions Workflow Editing

```bash
# Update action version
yq -i '(.jobs.build.steps[] | select(.uses == "actions/checkout@*")).uses = "actions/checkout@v4"' \
  .github/workflows/ci.yml

# Add a new step
yq -i '.jobs.build.steps += [{"name": "Lint", "run": "npm run lint"}]' \
  .github/workflows/ci.yml

# Update matrix values
yq -i '.jobs.test.strategy.matrix.php-version = ["8.2", "8.3", "8.4"]' \
  .github/workflows/ci.yml
```

### Docker-Compose Manipulation

```bash
# Change image tag
yq -i '.services.app.image = "myapp:2.0"' docker-compose.yml

# Add environment variable
yq -i '.services.app.environment.DEBUG = "true"' docker-compose.yml

# Add a volume mount
yq -i '.services.app.volumes += ["./data:/app/data"]' docker-compose.yml
```

### Multi-Document YAML

```bash
# Evaluate across all documents (---separated)
yq eval-all 'select(.kind == "Deployment")' k8s-manifests.yml

# Merge multiple files
yq eval-all '. as $item ireduce ({}; . * $item)' base.yml override.yml
```

### Format Conversion

```bash
# YAML to JSON
yq -o json file.yml

# JSON to YAML
yq -P file.json

# YAML to properties
yq -o props file.yml
```

---

## dasel -- Universal Selector

### Basic Usage

dasel auto-detects format from file extension:

```bash
# JSON
dasel -f config.json '.database.host'

# YAML
dasel -f config.yml '.server.port'

# TOML
dasel -f Cargo.toml '.package.version'

# XML
dasel -f pom.xml '.project.version'
```

### In-Place Editing

```bash
# Set value (auto-detects format, writes back)
dasel put -f config.json -t string -v "localhost" '.database.host'

# Set numeric value
dasel put -f config.json -t int -v 5432 '.database.port'

# Set boolean
dasel put -f config.toml -t bool -v true '.features.experimental'
```

### When to Use dasel Over jq/yq

- **TOML files**: Cargo.toml, pyproject.toml, config.toml -- jq/yq cannot handle TOML
- **XML files**: pom.xml, web.xml -- simpler than xmlstarlet for basic operations
- **Mixed-format pipelines**: Read YAML, output JSON, etc.
- **Simple reads/writes**: Less syntax to remember than jq for basic operations

### Format Conversion

```bash
# JSON to YAML
dasel -f input.json -w yaml

# TOML to JSON
dasel -f Cargo.toml -w json

# YAML to TOML
dasel -f config.yml -w toml
```

---

## qsv -- CSV/TSV Processing

### Data Exploration

```bash
# Column names and types
qsv headers data.csv
qsv stats data.csv --everything

# Row count
qsv count data.csv

# Frequency distribution of a column
qsv frequency data.csv --select category

# First/last rows
qsv slice data.csv --len 10
qsv slice data.csv --start -10
```

### Filtering and Selection

```bash
# Select specific columns
qsv select name,email,role data.csv

# Search with regex
qsv search "error|warn" --select level logs.csv

# Filter rows by condition
qsv search -s status "active" users.csv
```

### Transformation

```bash
# Sort by column
qsv sort --select revenue --reverse sales.csv

# Join two CSV files
qsv join id users.csv user_id orders.csv

# Deduplicate
qsv dedup --select email contacts.csv

# Add computed column
qsv eval "total = price * quantity" orders.csv
```

### When to Use qsv Over awk/Python

- **Large files**: qsv is compiled Rust, handles millions of rows efficiently
- **Standard operations**: stats, frequency, join, sort -- one-liners vs multi-line scripts
- **CSV correctness**: Handles quoting, escaping, encodings properly
- **Exploration**: Quick data profiling without writing code

---

## Common Workflows

### Parsing API Responses

```bash
# Get latest release tag from GitHub
gh api repos/owner/repo/releases --jq '.[0].tag_name'

# List open PRs with labels
gh pr list --json number,title,labels --jq '.[] | "\(.number) \(.title) [\(.labels | map(.name) | join(", "))]"'

# Extract specific data from curl response
curl -s https://api.example.com/data | jq '.results[] | {id, name, status}'
```

### Editing CI Configuration

```bash
# Update Node.js version in GitHub Actions
yq -i '.jobs.build.strategy.matrix.node-version = ["18", "20", "22"]' .github/workflows/ci.yml

# Add a new environment variable to all jobs
yq -i '.env.FORCE_COLOR = "1"' .github/workflows/ci.yml
```

### Updating Docker-Compose

```bash
# Bump service image version
yq -i '.services.postgres.image = "postgres:16-alpine"' docker-compose.yml

# Or with dasel
dasel put -f docker-compose.yml -t string -v "postgres:16-alpine" '.services.postgres.image'
```

### Modifying package.json

```bash
# Update version
jq '.version = "2.1.0"' package.json > package.json.tmp && mv package.json.tmp package.json

# Add a script
jq '.scripts.lint = "eslint src/"' package.json > package.json.tmp && mv package.json.tmp package.json

# Or with dasel (simpler for single values)
dasel put -f package.json -t string -v "2.1.0" '.version'
```

### Analyzing CSV Data

```bash
# Quick data profile
qsv stats data.csv --everything | qsv table

# Find most common values
qsv frequency data.csv --select category --limit 10

# Filter and export subset
qsv search -s country "Germany" customers.csv | qsv select name,email > german_customers.csv
```

---

## Anti-Patterns

### JSON: grep/sed vs jq

```bash
# BAD: Fragile, breaks on formatting changes
grep '"version"' package.json | sed 's/.*: "\(.*\)".*/\1/'

# GOOD: Correct regardless of formatting
jq -r '.version' package.json
```

```bash
# BAD: Multi-line JSON defeats grep
grep '"name"' response.json

# GOOD: Handles any structure
jq '.items[].name' response.json
```

```bash
# BAD: sed on JSON changes (breaks on nested quotes, escapes)
sed -i 's/"version": "1.0.0"/"version": "2.0.0"/' package.json

# GOOD: Structural edit
jq '.version = "2.0.0"' package.json > package.json.tmp && mv package.json.tmp package.json
```

### YAML: sed vs yq

```bash
# BAD: sed does not understand YAML indentation or multi-line values
sed -i 's/image: node:.*/image: node:20/' docker-compose.yml

# GOOD: Structural edit that respects YAML semantics
yq -i '.services.app.image = "node:20"' docker-compose.yml
```

```bash
# BAD: grep on YAML misses context
grep "uses:" .github/workflows/ci.yml

# GOOD: Query with structure
yq '.jobs[].steps[].uses | select(. != null)' .github/workflows/ci.yml
```

### CSV: awk vs qsv

```bash
# BAD: awk breaks on quoted fields containing commas
awk -F',' '{print $2}' data.csv

# GOOD: Proper CSV parsing
qsv select 2 data.csv
```

```bash
# BAD: sort does not understand CSV structure
sort -t',' -k3 -n data.csv

# GOOD: CSV-aware sort
qsv sort --select 3 --numeric data.csv
```

### GitHub CLI: pipe vs --jq

```bash
# BAD: Extra process, more tokens, less readable
gh api repos/owner/repo/pulls | jq '.[].title'

# GOOD: Built-in jq evaluation
gh api repos/owner/repo/pulls --jq '.[].title'
```

---

## References

- [jq Cookbook](references/jq-cookbook.md) -- Comprehensive jq patterns and recipes
- [yq Cookbook](references/yq-cookbook.md) -- YAML manipulation patterns
- [CSV Processing Guide](references/csv-processing.md) -- qsv workflows and recipes
- [jq Manual](https://jqlang.github.io/jq/manual/)
- [yq Documentation](https://mikefarah.gitbook.io/yq/)
- [dasel Documentation](https://daseldocs.tomwright.me/)
- [qsv Documentation](https://github.com/jqnatividad/qsv#available-commands)
