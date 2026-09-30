<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Architecture — data-tools-skill

## Overview

An AI agent skill that teaches agents to use dedicated CLI tools (jq, yq, dasel, qsv, mlr) for structured data manipulation instead of fragile text-processing tools (grep, sed, awk). Most of the repository is documentation for the agent. One executable component ships with it: a Claude Code `PreToolUse` hook that checks each Bash command the agent is about to run and denies or flags text-tool use on structured data.

## Actors

- **AI agent** (Claude Code or another Agent Skills client): reads `SKILL.md` and the references as instructions and proposes Bash commands.
- **Claude Code harness**: loads the plugin, calls the hook before every Bash tool call, and applies the hook's decision.
- **Skill user**: installs the plugin (marketplace, skills directory, npm, Composer, release archive or clone; see README) and runs the agent sessions.
- **Maintainers and contributors**: change the repository through pull requests; CI on GitHub Actions validates each change.

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
- **mlr-cookbook.md** — Miller for JSONL, DSL transforms, statistics, joins
- **enforcement-hook.md** — what the PreToolUse hook denies, warns about and lets through, and how to verify it

### PreToolUse hook (`hooks/hooks.json`, `scripts/pre_bash_structured_warn.py`)

`hooks/hooks.json` registers the hook for the `Bash` tool: Claude Code runs `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pre_bash_structured_warn.py` before each Bash call, with a timeout of 3 seconds. The script uses only the Python standard library.

**Input.** The harness writes a JSON payload to the script's stdin. The script reads `tool_name`, `tool_input.command`, and `session_id` (or, when that is absent, the file name of `transcript_path`). Anything other than a Bash call with a non-empty command, or a payload that is not valid JSON, ends the script with exit 0 and no output. Valid JSON of an unexpected shape (not an object, a `tool_input` that is not an object, a command that is not a string) is not type-checked: the script then ends with a Python traceback and exit 1, which Claude Code treats as a non-blocking error, so the command still runs.

**Processing.** The command is only analysed with regular expressions; the script never executes it.

1. Parts that are data rather than commands are removed: bodies of quoted heredocs, and the values of `--body`, `--message`, `--notes`, `--description`, `--title`, `--comment`, `-m`, `-F` and `-f field=` options. For the two deny checks the remainder is split into statements at `;`, newlines, `&&` and `||`, and `echo` and `printf` statements are skipped.
2. **Serializer rewrite → deny.** A statement that writes a structured file back through a serializer (`yq -i`/`--inplace`, `jq`/`yq`/`dasel … > file.json|jsonl|yaml|yml|toml`, `sponge` into such a file) is denied, unless the command contains `DATA_TOOLS_REWRITE_OK=1`.
3. **Field extraction → deny.** A statement that reads structured data (a `.json`, `.jsonl`, `.yaml`, `.yml`, `.toml`, `.xml`, `.csv` or `.tsv` file name, or a `gh`/`glab api` or `gh … --json` response that no `--jq`/`-q`/`jq`/`yq`/`dasel`/`mlr`/`qsv` has consumed yet) and extracts from it with a text tool (`grep -o`, `grep … | awk/cut/sed/head -1/tail -1`, `awk -F … {print`, `sed -n 's/…\1…/p'`) is denied. Count, presence and list greps (`-c`, `-q`, `-l`, `-L`) and a `grep -n` whose only downstream filter is `sed` pass.
4. **Other text-tool use → warn once.** `grep`, `sed`, `awk`, `cat`, `head`, `tail` or `python -c` in a command that names a structured file anywhere produces an advisory message; this check reads the whole remainder, without splitting it into statements or skipping `echo`. Each distinct message is shown once per session.

**Output.** A deny is a JSON object on stdout with `hookSpecificOutput.permissionDecision: "deny"` and a reason that names the tool to use instead; Claude Code does not run the command. A warning is a JSON object with `systemMessage` and `suppressOutput: true`; the command runs. Otherwise the script prints nothing. Every handled path exits 0; the unhandled payload shapes under **Input** exit 1.

**State.** For the once-per-session warnings the script keeps a JSON list of hashes of the messages already shown in `data-tools-hook-seen-<first 16 hex of SHA-256(session id)>.json` in the system temp directory (`tempfile.gettempdir()`). Hashing the session id keeps the file name inside that directory whatever the payload contains. When there is no session id, or the file cannot be read or written, every warning is shown. Denies are never deduplicated.

### Evals (`skills/data-tools/evals/`)

`evals.json` holds evaluation definitions for testing skill effectiveness with AI agents. The Eval Validation workflow validates their structure; it does not run them against an agent.

### Repository tooling

- `scripts/test_pre_bash_structured_warn.py` — behavioural tests for the hook: it feeds each case to the script as a subprocess and compares the verdict. The Skill Tests workflow (`.github/workflows/tests.yml`) runs it.
- `Build/Scripts/check-plugin-version.sh` — fails when the version in `.claude-plugin/plugin.json` differs from `metadata.version` in `SKILL.md`. `Build/hooks/pre-push` runs it; `.envrc` points `core.hooksPath` at `Build/hooks` for direnv users.
- `scripts/verify-harness.sh` — checks AGENTS.md and the docs layout for agent-harness consistency.
- `.github/workflows/` — CI: skill validation, eval validation, the hook tests, security scans, harness verification, template drift, labelling, release and dependency auto-merge. All files except `tests.yml` are managed by the central skill template in `netresearch/.github`.

## Data flow

```
Agent proposes Bash command
        │
        ▼
Claude Code ── JSON payload (stdin) ──▶ pre_bash_structured_warn.py
        ▲                                   │  reads/writes seen-state file
        │                                   │  in the system temp directory
        └──── deny / systemMessage / nothing (stdout), exit 0
```

The skill content flows one way: the agent framework reads `SKILL.md` and the references from the installed plugin. Neither the skill content nor the hook sends data over the network. Of the repository tooling, only `scripts/verify-harness.sh` makes a network call: `gh api` to check whether the organisation's `.github` repository has a pull request template.

## Design Decisions

- **Documentation plus one guard**: the rule is taught by the skill content and enforced by the hook, which ships in the same plugin so installing the skill installs the enforcement (`references/enforcement-hook.md`).
- **Fail open**: the hook exits 0 on input that is not JSON and when its state file cannot be read or written; a payload of an unexpected shape, or a state file holding JSON that is not a list, ends with exit 1, which Claude Code does not treat as a block. A broken hook therefore never blocks the shell. It guards against mistakes; it is not a security boundary.
- **Split licensing**: code under MIT, content under CC-BY-SA-4.0.
- **Composer integration**: published as a PHP package for projects using the composer-agent-skill-plugin.

Update this document in the same pull request when a component, an input or an output of the hook changes.
