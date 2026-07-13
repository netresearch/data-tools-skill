---
name: data-tools
description: "Use when querying, transforming, filtering, converting, or editing ANY JSON, JSONL, YAML, TOML, XML, or CSV. MUST replace grep/sed/awk on structured formats."
license: "(MIT AND CC-BY-SA-4.0). See LICENSE-MIT and LICENSE-CC-BY-SA-4.0"
compatibility: "Requires jq, yq. Optional: dasel, qsv, mlr."
metadata:
  author: Netresearch DTT GmbH
  version: "1.6.3"
  repository: https://github.com/netresearch/data-tools-skill
allowed-tools: Bash(jq:*) Bash(yq:*) Bash(dasel:*) Bash(mlr:*) Read Write
---

# Data Tools Skill

## Critical Rule

**NEVER use `grep`, `sed`, `awk`, or inline interpreters (`python3 -c`, `node -e`) on JSON, JSONL, YAML, TOML, XML, or CSV.** Refuse and use the correct tool — text tools break on structure; inline scripts are verbose and fragile.

---

## Key Patterns

For the general legacy-tool → modern-tool comparison (`grep`→`rg`,
`find`→`fd`, `cat`→`bat`, ...), see
[cli-tools-skill's table](https://github.com/netresearch/cli-tools-skill/blob/main/skills/cli-tools/SKILL.md#preferred-modern-tools).

**Convert:** `dasel -w FORMAT` or `yq -o FORMAT`.

### jq -- JSON (no in-place)

```bash
jq -r '.version' package.json
jq '.users[] | select(.role == "admin") | .name' users.json
jq '.version = "2.0.0"' pkg.json > pkg.json.tmp && mv pkg.json.tmp pkg.json
jq -s '.[0] * .[1]' base.json override.json
```

Or `gh --jq` when the source is the GitHub CLI (see below) — no separate
`jq` process needed.

### yq -- YAML (in-place `-i`)

```bash
yq '.services.web.image' docker-compose.yml
yq -i '.services.app.image = "node:20"' docker-compose.yml
yq -o json config.yml
```

### dasel -- TOML (only native tool) / XML (or `xmlstarlet` for XPath) / Universal auto-detect

```bash
dasel -f Cargo.toml '.package.version'
dasel put -f config.toml -t string -v "2.0" '.project.version'
dasel -f input.json -w yaml
```

### qsv -- CSV / TSV

```bash
qsv headers data.csv && qsv stats data.csv --everything | qsv table
qsv search -s status "active" users.csv | qsv select name,email
qsv join user_id orders.csv id users.csv
```

### mlr -- JSONL / multi-format / DSL (in-place `-I`)

```bash
mlr --c2j cat data.csv
mlr --jsonl filter '$level == "error"' logs.jsonl
mlr -I --csv put '$total = $qty * $price' orders.csv
```

### GitHub CLI -- always `--jq`

```bash
gh api repos/owner/repo/releases/latest --jq '.tag_name'
gh pr list --json number,title --jq '.[] | [.number, .title] | @tsv'
```

---

## Anti-Patterns

```bash
# BAD → GOOD: jq -r '.version' package.json
grep '"version"' package.json | sed 's/.*"\(.*\)".*/\1/'
# BAD → GOOD: yq -i '.services.app.image = "node:20"' compose.yml
sed -i 's/image: node:.*/image: node:20/' docker-compose.yml
# BAD → GOOD: qsv select 2 data.csv
awk -F',' '{print $2}' data.csv
# BAD → GOOD: jq -r '.version' plugin.json
python3 -c 'import json;print(json.load(open("plugin.json"))["version"])'
```

---

## References

| Cookbook | Content |
|---------|---------|
| [jq Cookbook](references/jq-cookbook.md) | Filtering, transforms, GitHub CLI |
| [yq Cookbook](references/yq-cookbook.md) | Actions, Compose, K8s |
| [dasel Cookbook](references/dasel-cookbook.md) | TOML/XML, conversion |
| [CSV Processing](references/csv-processing.md) | qsv workflows, joins |
| [mlr Cookbook](references/mlr-cookbook.md) | JSONL, DSL, stats, joins |

Docs: [jq](https://jqlang.github.io/jq/manual/), [yq](https://mikefarah.gitbook.io/yq/), [dasel](https://daseldocs.tomwright.me/), [qsv](https://github.com/jqnatividad/qsv#available-commands), [mlr](https://miller.readthedocs.io/).
