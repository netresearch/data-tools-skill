# Architecture — data-tools-skill

## Overview

A documentation-only AI agent skill that teaches agents to use dedicated CLI tools (jq, yq, dasel, qsv) for structured data manipulation instead of fragile text-processing tools (grep, sed, awk).

## Components

### Skill Definition (`skills/data-tools/SKILL.md`)

The main entry point loaded by agent frameworks. Contains:
- Tool selection decision tree (format → tool mapping)
- Quick-reference examples for each tool
- Anti-patterns and common mistakes

### Reference Cookbooks (`skills/data-tools/references/`)

Detailed pattern libraries for each tool:
- **jq-cookbook.md** — JSON querying, filtering, transformation, in-place editing
- **yq-cookbook.md** — YAML manipulation (CI configs, docker-compose, K8s manifests)
- **dasel-cookbook.md** — Universal selector for TOML, XML, and cross-format conversion
- **csv-processing.md** — qsv-based CSV/TSV exploration, filtering, and analysis

### Evals (`skills/data-tools/evals/`)

Evaluation definitions for testing skill effectiveness with AI agents.

## Design Decisions

- **No runtime code**: this repo contains only documentation and skill metadata. No scripts to build or test.
- **Split licensing**: code under MIT, content under CC-BY-SA-4.0.
- **Composer integration**: published as a PHP package for projects using the composer-agent-skill-plugin.
