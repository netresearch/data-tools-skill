<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Security assurance case — data-tools-skill

This document states what a user can expect from this repository in terms of security, and argues why that expectation holds. Every claim names the file that implements it. Reporting a vulnerability: see the [security policy](https://github.com/netresearch/.github/blob/main/SECURITY.md). Components and data flow: [ARCHITECTURE.md](ARCHITECTURE.md).

## What the repository ships

| Part | Files | Runs where |
| --- | --- | --- |
| Skill instructions for an AI agent | `skills/data-tools/SKILL.md`, `skills/data-tools/references/*.md` | Read by the agent as instructions; not executed |
| PreToolUse hook | `hooks/hooks.json`, `scripts/pre_bash_structured_warn.py` | On the user's machine, started by Claude Code before each Bash tool call |
| Repository checks | `scripts/test_pre_bash_structured_warn.py`, `Build/Scripts/check-plugin-version.sh`, `Build/hooks/pre-push`, `scripts/verify-harness.sh` | In this repository's CI and on contributors' machines |

The skill has no server component and handles no user accounts or credentials.

## Security requirements

1. The hook never executes the command it inspects, nor any other part of its input.
2. The hook sends nothing over the network.
3. The only file the hook writes is its once-per-session state file, and its input cannot choose where that file is written.
4. A command the hook denies is denied every time it is proposed; the once-per-session deduplication applies to warnings only.
5. Nothing committed to this repository contains a secret.

## Actors and trust boundaries

- **Agent → hook.** The command text in the payload is written by the AI agent, which may have been steered by content it read. The hook treats it as untrusted text: it matches regular expressions against it and does nothing else with it (`scripts/pre_bash_structured_warn.py`).
- **Claude Code → hook.** The harness starts the hook with the command from `hooks/hooks.json` and passes the payload on stdin. The hook trusts the harness to apply its decision; enforcement happens in Claude Code, not in the hook.
- **Hook → temp directory.** The state file lives in the system temp directory (`tempfile.gettempdir()`). Its content only decides which advisory warnings are suppressed as repeats; the deny decisions do not read it.
- **CI.** Workflows run on GitHub-hosted runners. Every workflow sets `permissions: {}` at the top level and grants each job only what its reusable workflow needs (`.github/workflows/*.yml`).

## Threats and countermeasures

| Threat | Countermeasure | Evidence |
| --- | --- | --- |
| The hook runs the inspected command or text from it (CWE-78, CWE-94) | The script imports only `bisect`, `hashlib`, `json`, `os`, `re`, `sys` and `tempfile`; it uses no `subprocess`, `eval`, `exec` or shell. The command is only matched with `re` | `scripts/pre_bash_structured_warn.py` |
| A crafted `session_id` steers the state file out of the temp directory (CWE-22) | The file name is built from the first 16 hex digits of the SHA-256 of the session id, never from the id itself | `_session_key()` in `scripts/pre_bash_structured_warn.py`; the case "Pfad-Traversal in der Session-ID" in `scripts/test_pre_bash_structured_warn.py` passes `../../../../tmp/evil` and asserts that the state file appears in the temp directory under the digest name and not at the traversal target |
| A long quoted option value makes the hook outlive its 3-second timeout, so the command runs unchecked (CWE-1333) | Quoted option values are matched by a pattern whose alternatives never accept the same character, so the time to match one grows linearly with its length | `_quoted()` in `scripts/pre_bash_structured_warn.py`; the three timed cases in `scripts/test_pre_bash_structured_warn.py` run the hook on 5000-backslash runs with no closing quote and require the right verdict in under one second |
| A long command of repeated words (`sed -n`, `awk -F`, `grep`, `gh`, `yq`, `jq >`, quoted heredoc openers) makes the hook outlive its 3-second timeout, so the command runs unchecked (CWE-1333) | The extraction, API and rewrite checks find their words one after another within each pipeline stage, option letters are read in one pass, and quoted heredocs are closed through an index of the command's lines, so each check reads the command a bounded number of times | `_extracts()`, `_counts_or_tests()`, `_locates()`, `_calls_json_api()`, `_api_parsed()`, `rewrites_structured()` and `_strip_quoted_heredocs()` in `scripts/pre_bash_structured_warn.py`; the 100 KB timed cases in `scripts/test_pre_bash_structured_warn.py` require the right verdict in under one second |
| A repeated forbidden extraction slips through after the first deny | Deny decisions are made before and independently of the deduplication | `main()` in `scripts/pre_bash_structured_warn.py`; the cases "Deny bleibt pro Aufruf, Lauf 1/2" in the tests |
| A malformed payload makes the hook break the shell | Invalid JSON on stdin ends the script with exit 0 and no output; any other exception, from a payload of an unexpected shape or a state file with unexpected content, is caught by the top-level guard and ends the same way | `main()` and the `__main__` guard in `scripts/pre_bash_structured_warn.py`; the three "exit 0 ohne Ausgabe" cases in `scripts/test_pre_bash_structured_warn.py` |
| A regression changes what the hook denies or lets through | The behavioural tests run on every pull request and push to `main`; the script exits 1 when a case fails | `.github/workflows/tests.yml`, `scripts/test_pre_bash_structured_warn.py` |
| A release is tagged with inconsistent version metadata | Skill Validation checks that `SKILL.md` `metadata.version` matches `.claude-plugin/plugin.json`; the local pre-push hook runs `check-plugin-version.sh` for the same comparison | `.github/workflows/lint.yml`, `Build/hooks/pre-push`, `Build/Scripts/check-plugin-version.sh` |
| A secret is committed | Betterleaks scans every push to `main` and every pull request to `main` | `.github/workflows/security.yml` |
| A vulnerable or malicious dependency is added | Dependency review fails a pull request on vulnerabilities of severity high or above; Composer Audit checks the Composer dependencies against known advisories; Renovate proposes updates, including pre-commit hook revisions | `.github/workflows/security.yml`, `renovate.json` |
| Insecure code or workflow patterns | Opengrep scans the code (failure threshold: [organisation SAST rule](https://github.com/netresearch/.github/blob/main/SECURITY.md#static-analysis-sast)); zizmor analyses the workflows; Skill Validation runs ShellCheck at severity `error` on every `*.sh` file and `ruff check` / `ruff format --check` on every Python file | `.github/workflows/security.yml`, `.github/workflows/lint.yml` |

Which of these checks must pass before a pull request can merge is set in the branch protection of `main`, not in this repository.

## Secure design principles applied

- **Economy of mechanism:** the hook is one Python file using only the standard library; it has no configuration beyond the `DATA_TOOLS_REWRITE_OK=1` override for serializer rewrites.
- **Least privilege:** the hook needs no credentials, opens no network connection and writes one file; the CI workflows start from `permissions: {}`.
- **Input treated as data:** the command is matched, never parsed into anything that runs, and the session id is hashed before it becomes part of a path.
- **Stateless decisions where it matters:** denies depend only on the command text, so shared or stale state cannot turn a deny into an allow.

## What a user cannot expect

- The hook guards against mistakes; it is not a security boundary. It recognises the text-tool patterns described in `skills/data-tools/references/enforcement-hook.md`, and an agent can reach the same data by other means.
- The hook fails open by design: on a payload it cannot read, or when its state file is unusable, it lets the command run. Under Claude Code's hook semantics a hook that exceeds its 3-second timeout (`hooks/hooks.json`) or fails does not block the command either.
- Detection of structured files is based on file names (`.json`, `.jsonl`, `.yaml`, `.yml`, `.toml`, `.xml`, `.csv`, `.tsv`) and on `gh`/`glab` JSON API calls; a structured file with another name is not recognised.
- The commands the skill recommends are examples for the agent. The skill does not install jq, yq, dasel, qsv or mlr; users obtain and update those tools from their own sources.
