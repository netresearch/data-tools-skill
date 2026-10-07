#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
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

import bisect
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
JSON_API = re.compile(r"\b(?:gh|glab)\s+api\b")
GH_COMMAND = re.compile(r"\bgh\s+\w+")
JSON_FLAG = re.compile(r"\s--json\s")

# …unless a parser already consumed it. `gh api … --jq '.x' | grep -oE …` greps
# jq's OUTPUT, which is text by then and legitimately grepped. The `-q` short
# form is matched only between `gh api` and the next pipe, because a bare `-q`
# elsewhere is `grep -q` and would exempt every case this hook exists for.
API_QUERY_FLAG = re.compile(r"\s(?:--jq|-q)\s")
PIPED_TO_PARSER = re.compile(r"\|\s*(?:jq|yq|dasel|mlr|qsv)\b")

# Field extraction from a structured file — the unambiguous half:
#   grep … | awk/cut/sed/head -1/tail -1
#   grep -o / -oE / -oP
#   awk -F … {print $N}
#   sed -n 's/…/\1/p'
# Each is checked by the scans in _extracts() below. Written as one regex with
# `[^|;&]*` between the words, every occurrence of the first word started a
# scan to the end of the stage, which made a long command of repeated words
# quadratic: 11 KB of `sed -n` took 8-11 s, past the hook's 3 s timeout, and a
# command the hook cannot judge in time runs unchecked.
GREP = re.compile(r"grep\b")
TO_FIELD_FILTER = re.compile(r"\s*(?:awk|cut|sed|head\s+-1|tail\s+-1)\b")
AWK, AWK_FS, AWK_PRINT = (
    re.compile(r"awk\b"),
    re.compile(r"-F"),
    re.compile(r"\{\s*print"),
)
SED, SED_N, SED_S = re.compile(r"sed\b"), re.compile(r"-n"), re.compile(r"s/")
BACKREF, PRINT_FLAG = re.compile(r"\\\d"), re.compile(r"p")
# A short option cluster: `-` and its letters. What follows the letters decides
# whether a regex `\b` would match there, so the letters are read in one pass
# instead of letting a pattern backtrack over them.
OPTION_LETTERS = re.compile(r"-([a-zA-Z]*)")
SPACED_OPTION = re.compile(r"\s-([a-zA-Z]*)")
GREP_FIRST_OPTION = re.compile(r"grep\b\s+-([a-zA-Z]*)")
GREP_ARGS = re.compile(r"grep\b\s+")
WHITESPACE = re.compile(r"\s+")
WORD_CHAR = re.compile(r"\w")

# `grep -n` locates a line; its `file:line:text` output is not a field value.
# Piping that to `sed` is almost always cosmetic (indenting, trimming a prefix
# for display), so it is exempt — but only when `sed` is the ONLY downstream
# filter. `grep -n … | cut -d: -f2` is still extraction and stays denied.
NON_COSMETIC_SINK = r"\|\s*(awk|cut|head\s+-1|tail\s+-1)\b"

# What `[^|;&]*` could not cross in the patterns these scans replace: the
# stages of a pipeline, and the parts around `;` and a single `&`.
STAGE_BREAK = re.compile(r"[|;&]")
REDIRECT_OR_STAGE_BREAK = re.compile(r"[|;&>]")

# Statement boundaries only — a pipeline stays whole, because `grep … | sed` is
# one extraction. Splitting here scopes the structured-filename test to the
# statement that actually does the extracting: a command that reads a .jsonl on
# one line and greps a .txt on the next must not be judged by both.
STATEMENT_SPLIT = re.compile(r";|\n|&&|\|\|")

# A quoted heredoc body is literal data — a file being written, a payload being
# piped. Scanning it for commands flags test fixtures and documentation that
# merely *contain* a pattern. Unquoted heredocs still expand and stay in.
# As a regex (`<<-?\s*(['"])(\w+)\1.*?^\2$`) every opener without its closing
# line scanned to the end of the command, so many openers took quadratic
# time; _strip_quoted_heredocs() looks the closing line up in an index instead.
HEREDOC_OPENER = re.compile(r"<<-?\s*(['\"])(\w+)\1")


# Prose passed as an OPTION VALUE is text about commands, not a command: a PR
# body, a commit message, an issue comment, an echo. The check blocked its own
# pull-request description, which explained the very patterns it matches.
# Values of --body/--message/-m/-f body= and friends are therefore removed
# before the scan; an option that names a FILE (--body-file) is untouched,
# because a path is not prose.
def _quoted() -> str:
    """A single- or double-quoted shell word, quoted the way bash quotes it.

    Single quotes allow no escape, so the run ends at the next `'`. Inside
    double quotes a backslash escapes the next character. Each alternative
    starts on a character no other alternative accepts, so the engine has one
    way to read every input and the time to match a quoted value grows
    linearly with its length.
    """
    return r"""(?:'[^']*'|"(?:[^"\\]|\\.)*")"""


OPTION_VALUES = (
    # --body "…" / --message='…' / -m "…" / -F '…'
    re.compile(
        r"(?:--(?:body|message|notes|description|title|comment)(?!-file)"
        r"|(?<!\w)-[mF](?!\w))[= ]\s*" + _quoted(),
        re.DOTALL,
    ),
    # gh/glab field form: -f body='…' — the '=' belongs to the field name.
    re.compile(r"(?<!\w)-f\s+\w+=\s*" + _quoted(), re.DOTALL),
)
# `echo '…'` / `printf '…'` write text; they never extract a field.
ECHOES_TEXT = re.compile(r"^\s*(echo|printf)\b")

ADVICE = (
    "use jq (JSON/JSONL) / yq (YAML·TOML·XML) / dasel (any) / qsv·mlr (CSV·TSV) — "
    "see the `data-tools` skill"
)


def _stages(text: str, breaks: re.Pattern = STAGE_BREAK):
    """Yield (start, end) of each run of text between two break characters."""
    start = 0
    for m in breaks.finditer(text):
        yield start, m.start()
        start = m.end()
    yield start, len(text)


def _in_order(text: str, start: int, end: int, *patterns: re.Pattern) -> int:
    """Offset after the patterns matched one after another in text[start:end].

    Each pattern is searched from where the previous match ended, so the
    patterns are found in order and the text is read once. Returns -1 when
    one of them is missing. Searching with pos/endpos keeps lookbehinds and
    word boundaries looking at the characters around the range, as they did
    when the same patterns were part of one regex over the whole text.
    """
    pos = start
    for pattern in patterns:
        m = pattern.search(text, pos, end)
        if m is None:
            return -1
        pos = m.end()
    return pos


def _boundary_after(text: str, pos: int) -> bool:
    r"""True where a regex `\b` after a run of letters ending at pos matches."""
    return pos >= len(text) or not WORD_CHAR.match(text, pos)


def _has_option_letter(text: str, start: int, end: int, letters: str) -> bool:
    r"""True when a whitespace-preceded `-xyz` in text[start:end] holds one of letters.

    Same verdict as `\s-[a-zA-Z]*[letters][a-zA-Z]*\b` over that range.
    """
    for m in SPACED_OPTION.finditer(text, start, end):
        if any(c in m.group(1) for c in letters) and _boundary_after(text, m.end()):
            return True
    return False


def _counts_or_tests(stmt: str) -> bool:
    """grep with -c, -q, -l or -L as its first option cluster."""
    for m in GREP_FIRST_OPTION.finditer(stmt):
        if any(c in m.group(1) for c in "cqlL") and _boundary_after(stmt, m.end()):
            return True
    return False


def _locates(stmt: str) -> bool:
    r"""grep whose leading option clusters include one with -n.

    Same verdict as `grep\b\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*n[a-zA-Z]*\b`: the
    options are read one cluster at a time instead of letting the nested
    repetition backtrack over them.
    """
    for g in GREP_ARGS.finditer(stmt):
        pos = g.end()
        while True:
            opt = OPTION_LETTERS.match(stmt, pos)
            if opt is None:
                break
            if "n" in opt.group(1) and _boundary_after(stmt, opt.end()):
                return True
            gap = WHITESPACE.match(stmt, opt.end())
            if gap is None:
                break
            pos = gap.end()
    return False


def _extracts(stmt: str) -> bool:
    """True when the statement extracts a field with grep, awk or sed."""
    for start, end in _stages(stmt):
        # grep … | awk/cut/sed/head -1/tail -1
        if (
            end < len(stmt)
            and stmt[end] == "|"
            and GREP.search(stmt, start, end)
            and TO_FIELD_FILTER.match(stmt, end + 1)
        ):
            return True
        # grep -o / -oE / -oP
        pos = _in_order(stmt, start, end, GREP)
        if pos >= 0 and _has_option_letter(stmt, pos, end, "o"):
            return True
        # awk -F … {print $N}
        if _in_order(stmt, start, end, AWK, AWK_FS, AWK_PRINT) >= 0:
            return True
        # sed -n 's/…/\1/p': the substitution itself may contain | and &
        pos = _in_order(stmt, start, end, SED, SED_N, SED_S)
        if pos >= 0 and _in_order(stmt, pos, len(stmt), BACKREF, PRINT_FLAG) >= 0:
            return True
    return False


def _calls_json_api(stmt: str) -> bool:
    """`gh api`/`glab api`, or a gh subcommand with --json in the same stage."""
    if JSON_API.search(stmt):
        return True
    return any(
        _in_order(stmt, start, end, GH_COMMAND, JSON_FLAG) >= 0
        for start, end in _stages(stmt)
    )


def _api_parsed(stmt: str) -> bool:
    """A parser consumed the API answer: --jq/-q of gh api, or a pipe into one."""
    if PIPED_TO_PARSER.search(stmt):
        return True
    return any(
        _in_order(stmt, start, end, JSON_API, API_QUERY_FLAG) >= 0
        for start, end in _stages(stmt)
    )


def _strip_quoted_heredocs(cmd: str) -> str:
    """Replace each quoted heredoc, opener to closing line, with one space.

    The closing line is the first line after the opener that consists of the
    delimiter alone; an opener without one is left in place.
    """
    lines: dict[str, list[tuple[int, int]]] = {}
    offset = 0
    for line in cmd.split("\n"):
        lines.setdefault(line, []).append((offset, offset + len(line)))
        offset += len(line) + 1
    out: list[str] = []
    copied = pos = 0
    while True:
        m = HEREDOC_OPENER.search(cmd, pos)
        if m is None:
            break
        candidates = lines.get(m.group(2), [])
        i = bisect.bisect_left(candidates, (m.end(),))
        if i == len(candidates):
            pos = m.start() + 1
            continue
        out.append(cmd[copied : m.start()])
        out.append(" ")
        copied = pos = candidates[i][1]
    out.append(cmd[copied:])
    return "".join(out)


def is_cosmetic_locate(cmd: str) -> bool:
    """True for a line-locating grep whose only downstream filter is sed."""
    return _locates(cmd) and not re.search(NON_COSMETIC_SINK, cmd)


def _executable_text(cmd: str) -> str:
    """Strip the parts of a command line that are data rather than instructions."""
    cmd = _strip_quoted_heredocs(cmd or "")
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
    return _calls_json_api(stmt) and not _api_parsed(stmt)


def extracts_from_structured(cmd: str) -> bool:
    """True when one statement both reads structured data and extracts from it."""
    for stmt in STATEMENT_SPLIT.split(_executable_text(cmd)):
        if ECHOES_TEXT.match(stmt):
            continue
        if not reads_structured(stmt):
            continue
        if not _extracts(stmt):
            continue
        if _counts_or_tests(stmt) or is_cosmetic_locate(stmt):
            continue
        return True
    return False


# Writing a structured file back THROUGH a serializer rewrites the whole file in the
# tool's own formatting — indentation, blank lines, key order, quoting — so a three-line
# change lands as a full-file diff (`yq -i` stripped every blank line of a
# .gitlab-ci.yml, 2026-08-28). Read with the parser, change the lines with an editor.
# Matched by rewrites_structured() as three scans, for the same reason as the
# extraction patterns: one regex with `[^|;&]*` was quadratic on repeated words.
YQ = re.compile(r"(?<!-)\byq\b", re.IGNORECASE)
INPLACE_FLAG = re.compile(r"\s(?:-i|--inplace)\b", re.IGNORECASE)
SERIALIZER = re.compile(r"(?<!-)\b(?:jq|yq|dasel)\b", re.IGNORECASE)
INTO_STRUCTURED_FILE = re.compile(
    r">\s*[\w./-]+\.(?:json|jsonl|ya?ml|toml)\b", re.IGNORECASE
)
SPONGE_INTO_STRUCTURED_FILE = re.compile(
    r"\bsponge\s+[\w./-]+\.(?:json|jsonl|ya?ml|toml)\b", re.IGNORECASE
)
REWRITE_ADVICE = (
    "Writing a structured file back through a serializer (yq -i, jq/yq > file, sponge) "
    "rewrites the whole file in the tool's formatting — indentation, blank lines, key order "
    "and quoting shift, the diff becomes unreviewable. Read the value with jq/yq, then change "
    "the line with the Edit tool (or a one-line anchored sed). If the file has no "
    "hand-maintained formatting (a generated lock or cache), say so and set "
    "DATA_TOOLS_REWRITE_OK=1."
)


def rewrites_structured(cmd: str) -> bool:
    """True when a statement writes a structured file back through a serializer."""
    if "DATA_TOOLS_REWRITE_OK=1" in cmd:
        return False
    for stmt in STATEMENT_SPLIT.split(_executable_text(cmd)):
        if ECHOES_TEXT.match(stmt):
            continue
        if SPONGE_INTO_STRUCTURED_FILE.search(stmt):
            return True
        for start, end in _stages(stmt, REDIRECT_OR_STAGE_BREAK):
            if _in_order(stmt, start, end, YQ, INPLACE_FLAG) >= 0:
                return True
        for start, end in _stages(stmt):
            if _in_order(stmt, start, end, SERIALIZER, INTO_STRUCTURED_FILE) >= 0:
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

    if rewrites_structured(cmd):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": REWRITE_ADVICE,
                    }
                }
            )
        )
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
                        + " (further matches of this rule stay silent this session)"
                    ),
                    "suppressOutput": True,
                }
            )
        )
    return 0


if __name__ == "__main__":
    # Fail open: any error ends with exit 0, see the module docstring.
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        sys.exit(0)
