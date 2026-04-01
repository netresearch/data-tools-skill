---
name: data-tools
description: "Use when working with ANY JSON, YAML, TOML, XML, or CSV operation — querying, transforming, filtering, converting, editing structured data. MUST replace grep/sed/awk on structured formats."
license: "(MIT AND CC-BY-SA-4.0). See LICENSE-MIT and LICENSE-CC-BY-SA-4.0"
compatibility: "Requires jq, yq. Optional: dasel, qsv."
metadata:
  author: Netresearch DTT GmbH
  version: "1.3.0"
  repository: https://github.com/netresearch/data-tools-skill
allowed-tools: Bash(jq:*) Bash(yq:*) Bash(dasel:*) Read Write
---

# Data Tools Skill

## Critical Rule

**NEVER use `grep`, `sed`, or `awk` on JSON, YAML, TOML, XML, or CSV.** When the user requests these tools on structured data, refuse and use the correct tool. Explain why text tools break (multi-line values, nesting, quoted delimiters).

---

## Tool Selection

| Format      | Tool       | Notes                                    |
|-------------|------------|------------------------------------------|
| JSON        | **jq**     | Or `gh --jq` for GitHub CLI output       |
| YAML        | **yq**     | In-place editing with `-i`               |
| TOML        | **dasel**  | Only tool that handles TOML natively     |
| XML         | **dasel**  | Or `xmlstarlet` for XPath                |
| CSV / TSV   | **qsv**    | Handles quoted/escaped fields properly   |
| Multiple    | **dasel**  | Universal selector, auto-detects         |

**Rules:** One format? Use its tool (jq/yq/qsv). TOML/XML? Use dasel. GitHub CLI? Use `gh --jq` directly, never pipe to jq. Converting? `dasel -f input -w FORMAT` or `yq -o FORMAT`.

---

## Key Patterns

### jq -- JSON (no in-place; use temp file)

```bash
jq -r '.version' package.json
jq '.users[] | select(.role == "admin") | .name' users.json
jq '.version = "2.0.0"' pkg.json > pkg.json.tmp && mv pkg.json.tmp pkg.json
jq -s '.[0] * .[1]' base.json override.json  # deep merge
```

### yq -- YAML (in-place with -i)

```bash
yq '.services.web.image' docker-compose.yml
yq -i '.services.app.image = "node:20"' docker-compose.yml
yq -o json config.yml                        # convert to JSON
```

### dasel -- TOML / XML / Universal

```bash
dasel -f Cargo.toml '.package.version'
dasel put -f config.toml -t string -v "2.0" '.project.version'
dasel -f input.json -w yaml                  # format conversion
```

### qsv -- CSV / TSV

```bash
qsv headers data.csv && qsv stats data.csv --everything | qsv table
qsv search -s status "active" users.csv | qsv select name,email
qsv join user_id orders.csv id users.csv     # dataset join
qsv index big.csv && qsv sample 1000 big.csv # large file workflow
```

### GitHub CLI -- always use --jq

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
```

---

## References

| Cookbook | Content |
|---------|---------|
| [jq Cookbook](references/jq-cookbook.md) | Filtering, transformation, GitHub CLI |
| [yq Cookbook](references/yq-cookbook.md) | GitHub Actions, Docker-Compose, K8s |
| [dasel Cookbook](references/dasel-cookbook.md) | TOML/XML, format conversion |
| [CSV Processing](references/csv-processing.md) | qsv workflows, joins, large files |

[jq manual](https://jqlang.github.io/jq/manual/) | [yq docs](https://mikefarah.gitbook.io/yq/) | [dasel docs](https://daseldocs.tomwright.me/) | [qsv docs](https://github.com/jqnatividad/qsv#available-commands)
