#!/usr/bin/env python3
"""PreToolUse hook for Bash: keep text tools off structured-data files.

The data-tools rule — use jq/yq/dasel/qsv/mlr instead of grep/sed/awk on
JSON, JSONL, YAML, TOML, XML and CSV — is an instruction, and instructions
get skipped. This is the gate that makes it hold, shipped with the plugin so
no per-machine installation step can be forgotten.

Two levels, because the two cases differ in how certain the mistake is:

* **Field extraction is denied.** `grep -oE '"x": "[^"]+"' f.json`,
  `grep … | awk '{print $2}'`, `awk -F: '{print $2}' f.yaml` — a structured
  parser is strictly correct here and the text tool is strictly fragile
  (order, escaping, multiline values). An advisory message for this case ran
  for a full session on one machine and was ignored every time, so it is a
  gate rather than a hint.
* **Everything else is a one-time warning.** A presence, count or locate grep
  (`-c`, `-q`, `-l`, `-n`) is frequently aimed at a COMMENT, which no
  structured parser can see at all, so the command is often right. The
  warning fires once per rule per session: the first firing carries the
  information, repeats only add noise (measured: 43 advisory firings from six
  rules in one session).

Exit code is always 0; a hook that crashes must never block a shell.
"""

import hashlib
import json
import os
import re
import sys
import tempfile

STRUCT = r"\.(json|jsonl|ya?ml|toml|xml|csv|tsv)(\b|['\"])"

# A response that IS JSON carries no filename: `gh api …/git/trees/…`,
# `gh pr list --json …`. The path in `…/contents/pkg.json` happens to match
# STRUCT, so those were covered by accident while the list endpoints — the ones
# fleet work uses — were not, and field extraction from them stayed silent.
JSON_API = re.compile(r"\b(?:gh|glab)\s+api\b|\bgh\s+\w+[^|;&]*\s--json\s")

# …unless a parser already consumed it. `gh api … --jq '.x' | grep -oE …` greps
# jq's OUTPUT, which is text by then and legitimately grepped. The `-q` short
# form is matched only between `gh api` and the next pipe, because a bare `-q`
# elsewhere is `grep -q` and would exempt every case this hook exists for.
API_PARSED = re.compile(
    r"\b(?:gh|glab)\s+api\b[^|;&]*\s(?:--jq|-q)\s"
    r"|\|\s*(?:jq|yq|dasel|mlr|qsv)\b"
)

# Field extraction from a structured file — the unambiguous half.
EXTRACT = (
    r"grep\b[^|;&]*\|\s*(awk|cut|sed|head\s+-1|tail\s+-1)\b"  # grep … | awk/cut/sed
    r"|grep\b[^|;&]*\s-[a-zA-Z]*o[a-zA-Z]*\b"  # grep -o / -oE / -oP
    r"|awk\b[^|;&]*-F[^|;&]*\{\s*print"  # awk -F … {print $N}
    r"|sed\b[^|;&]*-n[^|;&]*s/.*\\\d.*/?p"  # sed -n 's/…/\1/p'
)
COUNT_OR_TEST = r"grep\b\s+-[a-zA-Z]*[cqlL][a-zA-Z]*\b"

# `grep -n` locates a line; its `file:line:text` output is not a field value.
# Piping that to `sed` is almost always cosmetic (indenting, trimming a prefix
# for display), so it is exempt — but only when `sed` is the ONLY downstream
# filter. `grep -n … | cut -d: -f2` is still extraction and stays denied.
LOCATE = r"grep\b\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*n[a-zA-Z]*\b"
NON_COSMETIC_SINK = r"\|\s*(awk|cut|head\s+-1|tail\s+-1)\b"

# Statement boundaries only — a pipeline stays whole, because `grep … | sed` is
# one extraction. Splitting here scopes the structured-filename test to the
# statement that actually does the extracting: a command that reads a .jsonl on
# one line and greps a .txt on the next must not be judged by both.
STATEMENT_SPLIT = re.compile(r";|\n|&&|\|\|")

# A quoted heredoc body is literal data — a file being written, a payload being
# piped. Scanning it for commands flags test fixtures and documentation that
# merely *contain* a pattern. Unquoted heredocs still expand and stay in.
QUOTED_HEREDOC = re.compile(r"<<-?\s*(['\"])(\w+)\1.*?^\2$", re.DOTALL | re.MULTILINE)


# Prose passed as an OPTION VALUE is text about commands, not a command: a PR
# body, a commit message, an issue comment, an echo. The check blocked its own
# pull-request description, which explained the very patterns it matches.
# Values of --body/--message/-m/-f body= and friends are therefore removed
# before the scan; an option that names a FILE (--body-file) is untouched,
# because a path is not prose.
def _quoted(group: str) -> str:
    """A single- or double-quoted run, closing on its own opening quote.

    The quote is a NAMED group so two of these can live in one pattern set;
    with plain `(['\"])…\\1` the second copy's backreference silently points at
    the first copy's group, never matches, and the whole branch is dead.
    """
    return rf"(?P<{group}>['\"])(?:\\.|(?!(?P={group})).)*(?P={group})"


OPTION_VALUES = (
    # --body "…" / --message='…' / -m "…" / -F '…'
    re.compile(
        r"(?:--(?:body|message|notes|description|title|comment)(?!-file)"
        r"|(?<!\w)-[mF](?!\w))[= ]\s*" + _quoted("q"),
        re.DOTALL,
    ),
    # gh/glab field form: -f body='…' — the '=' belongs to the field name.
    re.compile(r"(?<!\w)-f\s+\w+=\s*" + _quoted("q"), re.DOTALL),
)
# `echo '…'` / `printf '…'` write text; they never extract a field.
ECHOES_TEXT = re.compile(r"^\s*(echo|printf)\b")

ADVICE = (
    "use jq (JSON/JSONL) / yq (YAML·TOML·XML) / dasel (any) / qsv·mlr (CSV·TSV) — "
    "see the `data-tools` skill"
)


def is_cosmetic_locate(cmd: str) -> bool:
    """True for a line-locating grep whose only downstream filter is sed."""
    return bool(re.search(LOCATE, cmd)) and not re.search(NON_COSMETIC_SINK, cmd)


def _executable_text(cmd: str) -> str:
    """Strip the parts of a command line that are data rather than instructions."""
    cmd = QUOTED_HEREDOC.sub(" ", cmd or "")
    for pattern in OPTION_VALUES:
        cmd = pattern.sub(" ", cmd)
    return cmd


def reads_structured(stmt: str) -> bool:
    """True when the statement's input is structured data.

    Either it names a structured file, or it calls an API that answers JSON and
    no parser has consumed that answer yet. Only the deny level asks this: the
    advisory level stays filename-based on purpose, so an ordinary
    `gh api … | head` does not start warning.
    """
    if re.search(STRUCT, stmt, re.IGNORECASE):
        return True
    return bool(JSON_API.search(stmt)) and not API_PARSED.search(stmt)


def extracts_from_structured(cmd: str) -> bool:
    """True when one statement both reads structured data and extracts from it."""
    for stmt in STATEMENT_SPLIT.split(_executable_text(cmd)):
        if ECHOES_TEXT.match(stmt):
            continue
        if not reads_structured(stmt):
            continue
        if not re.search(EXTRACT, stmt):
            continue
        if re.search(COUNT_OR_TEST, stmt) or is_cosmetic_locate(stmt):
            continue
        return True
    return False


def advisory_nudges(cmd: str) -> list[str]:
    """Non-extracting text-tool use on a structured file: warn, do not block."""
    cmd = _executable_text(cmd)
    out: list[str] = []
    if not re.search(STRUCT, cmd, re.IGNORECASE):
        return out
    if re.search(r"(^|[|&;]|\bxargs\s+)\s*(grep|sed|awk|cat|head|tail)\b", cmd):
        out.append(f"text tool on structured data — {ADVICE}.")
    if re.search(r"\bpython3?\s+-c\b", cmd):
        out.append(f"inline python parsing a structured file — {ADVICE}.")
    return out


# ─── once-per-session dedup for the advisory messages ────────────────────────
# The value sits in the FIRST firing: it is read once and either changes the
# next command or has a deliberate reason not to. Firings 2..n change nothing
# and only cost the operator attention while scrolling the session.


def _session_key(payload: dict) -> str:
    """A filename-safe digest of the session identity, or "" when there is none.

    The raw identifier comes from the harness payload and is hashed rather than
    interpolated: a value carrying `/` or `..` would otherwise steer the state
    file out of the temp directory.
    """
    raw = payload.get("session_id") or os.path.basename(
        payload.get("transcript_path") or ""
    )
    raw = str(raw).strip()
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def first_per_session(nudges: list[str], payload: dict) -> list[str]:
    """Keep only nudges whose rule has not fired in this session yet.

    Without a session identity, or when the state file cannot be read or
    written, this fails OPEN — a broken temp dir must never swallow the first,
    valuable firing.
    """
    key = _session_key(payload)
    if not key:
        return nudges
    path = os.path.join(tempfile.gettempdir(), f"data-tools-hook-seen-{key}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            seen = set(json.load(fh))
    except (OSError, ValueError):
        # No state yet, or it is unreadable — treat every rule as unseen.
        seen = set()
    fresh = []
    for n in nudges:
        h = hashlib.sha256(n.encode("utf-8")).hexdigest()[:12]
        if h in seen:
            continue
        seen.add(h)
        fresh.append(n)
    if fresh:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(sorted(seen), fh)
        except OSError:
            pass
    return fresh


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        # Malformed or unreadable payload — say nothing rather than break a shell.
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command", "")
    if not cmd:
        return 0

    if extracts_from_structured(cmd):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"Field extraction from a structured file with a text tool. {ADVICE}. "
                            "If you are grepping for a COMMENT (which no structured parser can "
                            "see), use grep -c/-q/-n/-l and this check will let it through."
                        ),
                    }
                }
            )
        )
        return 0

    nudges = first_per_session(advisory_nudges(cmd), payload)
    if nudges:
        print(
            json.dumps(
                {
                    "systemMessage": (
                        "data-tools: "
                        + " ".join(nudges)
                        + " (warned once per rule per session)"
                    ),
                    "suppressOutput": True,
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
