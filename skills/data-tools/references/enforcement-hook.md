# Enforcement Hook

This skill's core rule — use `jq`/`yq`/`mlr`/`dasel` instead of `grep`/`sed`/`awk`
on structured formats — is an instruction, and instructions get skipped. The gate
that makes it hold **ships with this plugin**: `hooks/hooks.json` registers
`scripts/pre_bash_structured_warn.py` as a `PreToolUse` hook on `Bash`, so
installing the plugin installs the enforcement. There is no per-machine setup
step, and no copy of the script to keep in sync.

## What it does

Two levels, because the two cases differ in how certain the mistake is.

**Field extraction is denied.** `grep -oE '"x": "[^"]+"' f.json`,
`grep … | awk '{print $2}'`, `awk -F: '{print $2}' f.yaml`, `grep -n … | cut -d: -f2`.
A structured parser is strictly correct here and the text tool is strictly
fragile — key order, escaping and multiline values all break it. An advisory
message for exactly this case ran for a full session on one machine and was
ignored every time, which is why it is a gate rather than a hint.

**Everything else warns once.** A presence, count or locate grep (`-c`, `-q`,
`-l`, `-n`) is frequently aimed at a **comment**, which no structured parser can
see at all, so the command is often right — as is reading a file too corrupted to
parse, or a pre-parse sanity check. Those get one message per rule per session:
the first firing carries the information, repeats only cost the reader attention
while scrolling (measured: 43 advisory firings from six rules in a single
session).

## What it deliberately lets through

Each of these was a false positive first, then a rule:

- `grep -c 'GITLEAKS' x.json` — counting a **comment**; `jq` cannot see comments.
- `grep -n 'name' pkg.json | sed 's/^/  /'` — `grep -n` locates a line, and a
  lone `sed` downstream is cosmetic (indenting for display). Add `cut`/`awk`
  behind it and it is extraction again, which is denied.
- A `.jsonl` read on one line and a `.txt` grep on the next — the check is scoped
  per statement, not per tool call, so two unrelated statements are judged
  separately.
- An extraction pattern inside a **quoted heredoc** — that body is data being
  written, not a command being run.

## Verify

Feed the hook the payload it receives, rather than trusting that it works:

```bash
H="$CLAUDE_PLUGIN_ROOT/scripts/pre_bash_structured_warn.py"   # or the plugin cache path
echo '{"tool_name":"Bash","tool_input":{"command":"grep -oE \"\\\"a\\\": .\" f.json"}}' | python3 "$H"  # deny
echo '{"tool_name":"Bash","tool_input":{"command":"grep -c TODO ci.yaml"}}'             | python3 "$H"  # warn
echo '{"tool_name":"Bash","tool_input":{"command":"jq -r .name package.json"}}'         | python3 "$H"  # silent
```

The full case list runs as `python3 scripts/test_pre_bash_structured_warn.py`.

If nothing happens on a real `grep -oE … f.json`, the plugin's hooks have not been
picked up — open `/hooks` once, or restart the session.

## If the harness already has its own gate

Some setups wire a combined `PreToolUse` script in `~/.claude/settings.json` that
covers this rule among others. Two hooks enforcing the same rule produce two
messages for one command. Check before adding anything by hand:

```bash
jq -r '.hooks.PreToolUse[]?.hooks[]?.command' ~/.claude/settings.json
```

If a local script already covers structured-data access, remove that part of it
and let the plugin own the rule — one rule, one place.

## Project-level variants

The same rule belongs in a repo's own pre-commit config where committed shell
scripts query structured files. There the check is a lint rule over `*.sh`
rather than a harness hook, and it blocks rather than warns, because a committed
script is reviewed once and then runs unattended.
