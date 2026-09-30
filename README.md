<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# data-tools-skill

AI agent skill for structured data manipulation. Teaches agents when and how to use dedicated tools instead of fragile text processing (grep/sed/awk) on structured formats.

## Tools Covered

| Tool | Format | Use Case |
|------|--------|----------|
| [jq](https://jqlang.github.io/jq/) | JSON | Query, filter, transform JSON data |
| [yq](https://github.com/mikefarah/yq) | YAML | Edit CI configs, docker-compose, K8s manifests |
| [dasel](https://github.com/TomWright/dasel) | JSON/YAML/TOML/XML | Universal selector, format conversion |
| [qsv](https://github.com/jqnatividad/qsv) | CSV/TSV | Fast data exploration, filtering, analysis |
| [mlr](https://github.com/johnkerl/miller) | CSV/TSV/JSON/JSONL/PPRINT/XTAB/NIDX | Name-indexed records, DSL stats/joins, in-place edits |

## Core Principle

**Never use `grep`, `sed`, or `awk` on JSON, YAML, TOML, XML, or CSV data.** These tools treat structured data as flat text and break on multi-line values, nested structures, quoted strings, and encoding differences.

## Installation

### Marketplace (Recommended)

Add the [Netresearch marketplace](https://github.com/netresearch/claude-code-marketplace) once, then browse and install skills:

```bash
# Claude Code
/plugin marketplace add netresearch/claude-code-marketplace
/plugin install data-tools@netresearch-claude-code-marketplace
```

### Without a marketplace

Since Claude Code 2.1.157 a plugin directory under your personal skills directory loads on its own, including the hooks this repo ships:

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/netresearch/data-tools-skill.git \
  ~/.claude/skills/data-tools
```

It loads as `data-tools@skills-dir` on the next session. Update with `git -C ~/.claude/skills/data-tools pull` and start a new session; remove it by deleting the directory. This route has no `claude plugin update`.

### npx ([skills.sh](https://skills.sh))

Install with any [Agent Skills](https://agentskills.io)-compatible agent:

```bash
npx skills add https://github.com/netresearch/data-tools-skill --skill data-tools
```

> **Limitation:** `npx skills` installs `SKILL.md`-based skills only. This repo also ships `hooks`, which it does not install — use the marketplace or the skills directory for those.

### Download Release

Download the [latest release](https://github.com/netresearch/data-tools-skill/releases/latest) and extract to your agent's skills directory.

### Git Clone

```bash
git clone https://github.com/netresearch/data-tools-skill.git
```

### Composer (PHP Projects)

```bash
composer require netresearch/data-tools-skill
```

Requires [netresearch/composer-agent-skill-plugin](https://github.com/netresearch/composer-agent-skill-plugin).

### npm (Node Projects)

```bash
npm install --save-dev \
  @netresearch/agent-skill-coordinator \
  github:netresearch/data-tools-skill
```

Requires [@netresearch/agent-skill-coordinator](https://github.com/netresearch/node-agent-skill-coordinator), which discovers the skill in `node_modules` and registers it in `AGENTS.md` via a `postinstall` hook. For pnpm, also allowlist the coordinator's postinstall:

```json
{
  "pnpm": {
    "onlyBuiltDependencies": ["@netresearch/agent-skill-coordinator"]
  }
}
```

## Structure

```
skills/data-tools/
  SKILL.md                       # Main skill file (tool selection, patterns, anti-patterns)
  references/
    jq-cookbook.md                # Comprehensive jq patterns
    yq-cookbook.md                # YAML manipulation patterns
    dasel-cookbook.md             # TOML/XML/universal selector patterns
    csv-processing.md            # qsv workflows and recipes
    mlr-cookbook.md               # Miller for JSONL, DSL, stats, joins
    enforcement-hook.md           # What the PreToolUse gate denies and lets through
hooks/hooks.json                  # Registers the PreToolUse gate for the Bash tool
scripts/
  pre_bash_structured_warn.py     # The gate (Python, standard library only)
  test_pre_bash_structured_warn.py  # Its behavioural tests
```

The components and the hook's data flow are described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Contributing

Contributions follow the [Netresearch contributing guide](https://github.com/netresearch/.github/blob/main/CONTRIBUTING.md). `pre-commit run --all-files` runs the Skill Validation linters locally, stricter than CI: markdownlint checks every Markdown file (CI: the root files), and ShellCheck runs at its default `style` severity on every file pre-commit identifies as shell, `.envrc` and `Build/hooks/pre-push` included (CI: `error`, on `*.sh` files only). `pre-commit install --install-hooks` installs them as a commit hook, but pre-commit refuses while `core.hooksPath` is set, which `.envrc` does (it points git at `Build/hooks`); direnv users run the linters by hand instead.

### Tests

The behavioural tests of the PreToolUse hook need only Python 3.10 or later:

```bash
python3 scripts/test_pre_bash_structured_warn.py
```

- The script runs `scripts/pre_bash_structured_warn.py` as a subprocess with a hook payload per case and compares the result. It covers the deny cases (serializer rewrites, field extraction from files and from `gh`/`glab` API responses), the commands that must pass (count and presence greps, cosmetic `grep -n | sed`, prose in PR bodies, commit messages and quoted heredocs, output already parsed by `--jq`), the one-time warnings and their once-per-session deduplication, that a deny is never deduplicated, and that a session id cannot steer the state file out of the temp directory.
- Each case prints one line: `OK` or `FEHL`, the case name, the expected (`erwartet`) and the actual (`erhalten`) result. The last line is `---- Fehlschlaege: N`, the number of failing cases; the script exits 1 when N is not 0.
- When it finishes, the script deletes every `data-tools-hook-seen-*` file in the system temp directory, so warnings already shown in a running session appear once more.

In CI, the Skill Tests workflow (`.github/workflows/tests.yml`) runs the script on every pull request and on pushes to `main`.

A pull request that changes what the hook denies, warns about or lets through adds a case to `scripts/test_pre_bash_structured_warn.py` that fails without the change.

## Governance and policies

This repository follows the Netresearch organisation policies:

- [Governance](https://github.com/netresearch/.github/blob/main/GOVERNANCE.md): ownership, roles, how decisions are made and disputes resolved, and continuity.
- [Roadmap](https://github.com/netresearch/.github/blob/main/ROADMAP.md): planned and explicitly excluded work for the coming year.
- [Handling of dependency and code analysis findings](https://github.com/netresearch/.github/blob/main/SECURITY.md#handling-of-dependency-and-code-analysis-findings): thresholds, deadlines and the exception process for dependency (SCA) and static analysis (SAST) findings.
- [Secret management](https://github.com/netresearch/.github/blob/main/SECURITY.md#secret-management): how CI and release credentials are stored, accessed and rotated.
- [Access roster](https://github.com/netresearch/.github/blob/main/docs/access-roster.md): who holds administrative access to this repository and the organisation.

The security assurance case for this skill (threat model, trust boundaries, countermeasures and limits) is in [docs/SECURITY-ASSURANCE.md](docs/SECURITY-ASSURANCE.md).

Checks that run on pull requests in this repository:

- Every pull request: Skill Validation (`lint.yml`: skill structure, manifest sync, markdownlint, yamllint, actionlint, JSON syntax, version parity, ShellCheck, ruff), Eval Validation (`eval-validate.yml`) and Skill Tests (`tests.yml`).
- Pull requests to `main`: `security.yml` with Betterleaks (secret scanning), zizmor (workflow static analysis), dependency review (fails on vulnerabilities of severity high or above), Composer Audit and Opengrep SAST (failure threshold: [organisation SAST rule](https://github.com/netresearch/.github/blob/main/SECURITY.md#static-analysis-sast)); Harness Verification (`harness-verify.yml`) and Template Drift (`check-template-drift.yml`).

## License

This project uses split licensing:

- **Code** (scripts, workflows, configs): [MIT](LICENSE-MIT)
- **Content** (skill definitions, documentation, references): [CC-BY-SA-4.0](LICENSE-CC-BY-SA-4.0)

See the individual license files for full terms.
