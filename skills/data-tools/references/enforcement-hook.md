# Enforcement Hook

This skill's core rule — use `jq`/`yq`/`mlr`/`dasel` instead of `grep`/`sed`/`awk`
on structured formats — is an instruction, and instructions get skipped. This
reference is the gate that makes it hold: a Claude Code `PreToolUse` hook on
`Bash` that warns when a text tool is pointed at a structured file.

Install it once per harness; it then applies to every project.

## Check what is already there first

The hook block usually exists with other matchers. Extend the array — replacing
it drops whatever else is wired in.

```bash
jq '.hooks.PreToolUse[].matcher' ~/.claude/settings.json
```

No `Bash` matcher in the output means the gate is missing.

## The check

`~/.claude/hooks/pre-bash-structured-warn.py`:

```python
#!/usr/bin/env python3
"""PreToolUse hook for Bash: warn when grep/sed/awk targets a structured-data file.

The data-tools rule ("MUST replace grep/sed/awk on structured formats") exists in
CLAUDE.md and in the data-tools skill; this is the gate that makes it hold.

Uses shlex rather than splitting on '|' so a pipe inside a quoted pattern
(grep "word\\|cap" foo.yaml) does not hide the file operand.
"""

import json
import re
import shlex
import sys

TOOLS = {"grep", "egrep", "fgrep", "rg", "sed", "awk", "gawk", "mawk"}
STRUCTURED = re.compile(
    r"\.(ya?ml|json|jsonc|jsonl|ndjson|toml|xml|csv|tsv)$", re.IGNORECASE
)
SEPARATORS = {"|", "||", ";", "&&", "&", "(", ")", "\n"}
ADVICE = "jq (JSON/JSONL), yq (YAML/TOML/XML), mlr (CSV/TSV), dasel (any)"


def segments(command):
    """Split a shell command into pipeline/list segments, honouring quotes."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:  # unbalanced quotes — nothing reliable to say
        return []

    out, current = [], []
    for token in tokens:
        if token in SEPARATORS:
            out.append(current)
            current = []
        else:
            current.append(token)
    out.append(current)
    return [seg for seg in out if seg]


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return 0

    hits = []
    for seg in segments(command):
        tool = seg[0].rsplit("/", 1)[-1]
        if tool not in TOOLS:
            continue
        # Find a FILE operand, not the pattern/script. For all these tools the
        # first non-option argument is the pattern (grep/rg) or the program
        # (sed/awk) unless it was supplied via -e/-f, so skip exactly one.
        args = seg[1:]
        pattern_pending = not any(
            a in ("-e", "-f") or a.startswith(("--regexp", "--file")) for a in args
        )
        skip_next = False
        for arg in args:
            if skip_next:
                skip_next = False
                continue
            if arg in ("-e", "-f"):
                skip_next = True
                continue
            if arg.startswith("-"):
                continue
            if pattern_pending:
                pattern_pending = False
                continue
            if STRUCTURED.search(arg):
                hits.append(f"{tool} → {arg}")
                break

    if not hits:
        return 0

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": (
                        "Structured-file text tool: "
                        + ", ".join(hits)
                        + ". Line-oriented tools miss nested keys, multi-line values,"
                        " anchors and comments, and match text that is not the field"
                        f" you meant. Use {ADVICE} via the data-tools skill. If you"
                        " genuinely need a raw byte/line view (file shape, a corrupted"
                        " file, a pre-parse sanity check), proceed."
                    ),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Two details that decide whether it works:

- **Tokenize, don't split on `|`.** `grep "word\|cap" config.yaml` contains a
  pipe *inside the pattern*; a naive `tr '|' '\n'` splits there, the file operand
  lands in a segment starting with `cap"`, and the real case never fires. `shlex`
  with `punctuation_chars=True` respects quoting.
- **Skip one non-option argument.** For all these tools the first non-option
  argument is the pattern (`grep`, `rg`) or the program (`sed`, `awk`), not a
  file — otherwise `grep -c "foo.yaml" notes.txt` warns about its own pattern.
  Unless `-e`/`-f` supplied it, in which case the first operand *is* the file.

## Wire it up

Add to the `hooks.PreToolUse` array in `~/.claude/settings.json`:

```json
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "python3 $HOME/.claude/hooks/pre-bash-structured-warn.py",
      "timeout": 5
    }
  ]
}
```

Warn, do not block. The raw view is legitimate for checking file shape, reading
a file too corrupted to parse, or a pre-parse sanity check — a blocking gate
would make those cost a workaround.

## Verify

Pipe the payload the hook receives, rather than trusting that it works:

```bash
H=~/.claude/hooks/pre-bash-structured-warn.py
echo '{"tool_input":{"command":"grep -rn \"a\\|b\" .pre-commit-config.yaml"}}' | python3 $H   # warns
echo '{"tool_input":{"command":"jq -r .name package.json | grep foo"}}'        | python3 $H   # silent
echo '{"tool_input":{"command":"grep -c \"foo.yaml\" notes.txt"}}'             | python3 $H   # silent
```

Then confirm the schema and that the settings watcher picked it up:

```bash
jq -e '.hooks.PreToolUse[] | select(.matcher=="Bash") | .hooks[].command' ~/.claude/settings.json
```

If the JSON is right but no warning appears on a real `grep foo.yaml`, the
watcher has not reloaded — open `/hooks` once, or restart the session.

## Project-level variants

The same rule belongs in a repo's own pre-commit config where committed shell
scripts query structured files. There the check is a lint rule over `*.sh`
rather than a harness hook, and it blocks rather than warns, because a committed
script is reviewed once and then runs unattended.
