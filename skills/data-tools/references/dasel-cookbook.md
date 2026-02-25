# dasel Cookbook

Universal selector for JSON, YAML, TOML, and XML using dasel v2 (TomWright/dasel).

---

## Basic Usage

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

---

## In-Place Editing

```bash
# Set string value (auto-detects format, writes back)
dasel put -f config.json -t string -v "localhost" '.database.host'

# Set numeric value
dasel put -f config.json -t int -v 5432 '.database.port'

# Set boolean
dasel put -f config.toml -t bool -v true '.features.experimental'
```

---

## When to Use dasel Over jq/yq

- **TOML files**: Cargo.toml, pyproject.toml, config.toml -- jq/yq cannot handle TOML
- **XML files**: pom.xml, web.xml -- simpler than xmlstarlet for basic operations
- **Mixed-format pipelines**: Read YAML, output JSON, etc.
- **Simple reads/writes**: Less syntax to remember than jq for basic operations

---

## Format Conversion

```bash
# JSON to YAML
dasel -f input.json -w yaml

# TOML to JSON
dasel -f Cargo.toml -w json

# YAML to TOML
dasel -f config.yml -w toml
```

---

## Common Workflows

### Modifying package.json (alternative to jq)

```bash
# Simpler syntax for single-value edits
dasel put -f package.json -t string -v "2.1.0" '.version'
```

### Updating Docker-Compose (alternative to yq)

```bash
dasel put -f docker-compose.yml -t string -v "postgres:16-alpine" '.services.postgres.image'
```

### TOML Configuration Editing

```bash
# Read Cargo.toml version
dasel -f Cargo.toml '.package.version'

# Update pyproject.toml
dasel put -f pyproject.toml -t string -v "3.0.0" '.project.version'
```
