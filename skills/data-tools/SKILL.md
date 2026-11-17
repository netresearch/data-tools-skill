---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
name: data-tools
description: "Use when querying, transforming, filtering, converting, or editing ANY JSON, JSONL, YAML, TOML, XML, or CSV. MUST replace grep/sed/awk on structured formats."
license: "(MIT AND CC-BY-SA-4.0). See LICENSE-MIT and LICENSE-CC-BY-SA-4.0"
compatibility: "Requires uv (runs the plugin's hook on Python 3.11 or later), jq, yq. Optional: dasel, qsv, mlr."
metadata:
  author: Netresearch DTT GmbH
  version: "1.9.11"
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
[the cli-tools skill's table](https://github.com/netresearch/coding_agent_cli_toolset/blob/main/skills/cli-tools/SKILL.md#preferred-modern-tools).

**Convert:** `dasel -w FORMAT` or `yq -o FORMAT`.

### jq -- JSON (no in-place)

```bash
jq -r '.version' package.json
jq '.users[] | select(.role == "admin") | .name' users.json
jq -s '.[0] * .[1]' base.json override.json
```

Or `gh --jq` when the source is the GitHub CLI (see below) — no separate
`jq` process needed.

### yq -- YAML

```bash
yq '.services.web.image' docker-compose.yml
yq '.jobs[].name' .gitlab-ci.yml
yq -o json config.yml
```

### dasel -- TOML (only native tool) / XML (or `xmlstarlet` for XPath) / Universal auto-detect

```bash
dasel -f Cargo.toml '.package.version'
dasel -f pyproject.toml '.project.dependencies'
dasel -f input.json -w yaml
```

### qsv -- CSV / TSV

```bash
qsv headers data.csv && qsv stats data.csv --everything | qsv table
qsv search -s status "active" users.csv | qsv select name,email
qsv join user_id orders.csv id users.csv
```

`qsv index`, `stats` and `frequency` write files next to the input (`x.csv.idx`, `x.stats.csv*`). In a repository or a package directory, run them on a copy ([details](references/csv-processing.md#files-qsv-writes-next-to-the-input)).

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

## Editing an existing file

A serializer writes the whole document back in its own formatting: indentation, blank lines, key order, quoting. `jq … > file.json`, `yq -i`, `dasel put -f` and a script's `json.dump()` or `yaml.dump()` all do that, so a one-value change to a hand-maintained file becomes a full-file diff.

1. Find the value with the parser: `yq '.services.app.image' docker-compose.yml`.
2. Change that line with an exact-match edit (editor or edit tool), not by re-emitting the file.
3. Parse the file again (`jq empty f.json`, `yq '.' f.yml > /dev/null`) and check the diff is the size you meant: `git diff --numstat -- <file>`.

The plugin's hook denies the shell forms `yq -i`, `jq`/`yq`/`dasel … > file.json|yaml|toml` and `sponge` into such a file ([details](references/enforcement-hook.md#serializer-write-back)); it does not see `dasel put -f` or a script's `json.dump()`. A file with no hand-maintained formatting (a generated lock or cache) may be re-emitted whole: put `DATA_TOOLS_REWRITE_OK=1` in that command.

---

## Anti-Patterns

```bash
# BAD → GOOD: jq -r '.version' package.json
grep '"version"' package.json | sed 's/.*"\(.*\)".*/\1/'
# BAD → GOOD: locate with yq '.services.app.image', then edit that one line
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
| [jq Cookbook](references/jq-cookbook.md) | Filtering, transforms, GitHub CLI, large inputs ("Argument list too long", Windows) |
| [yq Cookbook](references/yq-cookbook.md) | Actions, Compose, K8s |
| [dasel Cookbook](references/dasel-cookbook.md) | TOML/XML, conversion |
| [CSV Processing](references/csv-processing.md) | qsv workflows, joins |
| [mlr Cookbook](references/mlr-cookbook.md) | JSONL, DSL, stats, joins |
| [Enforcement Hook](references/enforcement-hook.md) | PreToolUse gate shipped with this plugin: denies field extraction and serializer write-back, warns once otherwise |

Docs: [jq](https://jqlang.github.io/jq/manual/), [yq](https://mikefarah.gitbook.io/yq/), [dasel](https://daseldocs.tomwright.me/), [qsv](https://github.com/jqnatividad/qsv#available-commands), [mlr](https://miller.readthedocs.io/).
