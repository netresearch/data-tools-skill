#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
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

# …or unless the endpoint answers with a file's raw bytes instead of JSON:
# GitLab's `repository/files/<path>/raw` and `repository/blobs/<sha>/raw`, and
# GitHub's contents API asked for the raw media type. A Dockerfile fetched that
# way is text, and `grep -o` on it was denied as JSON extraction. A raw file
# whose own name is structured (`…/files/pkg.json/raw`) still matches STRUCT,
# which reads_structured() checks first. `vnd.github.raw+json` is left out on
# purpose: outside the contents API it answers JSON with a raw-text body.
GITLAB_RAW_PATH = re.compile(r"/repository/(?:files|blobs)/")
GITLAB_RAW_SUFFIX = re.compile(r"/raw(?![\w.+-])")
GITHUB_RAW_ACCEPT = re.compile(r"application/vnd\.github(?:\.v3)?\.raw(?![\w.+-])")
# The same holds for the endpoints that answer a CI log or an artifact file:
# GitLab's `jobs/<id>/trace` and `jobs/artifacts/<ref>/raw/<path>`, GitHub's
# `actions/jobs/<id>/logs`. `grep … | sed` over a job log was denied as JSON
# extraction (#83). The job object itself (`jobs/<id>`) still answers JSON, and
# a raw artifact with a structured name still matches STRUCT.
TEXT_ENDPOINTS = (
    re.compile(r"/jobs/[^/\s]+/trace(?![\w.+-])"),
    # One file out of a job's archive. `artifacts/tree` and `artifacts/keep`
    # answer JSON, and `artifacts` alone is the zip.
    re.compile(r"/jobs/[^/\s]+/artifacts/(?!(?:tree|keep)(?![\w.+-]))[^\s/?]"),
    re.compile(r"/actions/jobs/[^/\s]+/logs(?![\w.+-])"),
)
# `jobs/artifacts/<ref>/raw/<path>`: the ref can span segments
# (`refs/merge-requests/1/head`), so it is found as two ordered scans, like
# GITLAB_RAW_PATH and GITLAB_RAW_SUFFIX.
GITLAB_ARTIFACT_BY_REF = re.compile(r"/jobs/artifacts/")
RAW_SEGMENT = re.compile(r"/raw/")

# A structured name that only reaches another program as its argument says
# nothing about what that program prints: `php probe.php cases.json | grep -v X`
# greps the script's output (#83). So a stage that runs a script file through
# an interpreter does not make its statement structured. Inline code
# (`python3 -c '…'`, `node -e '…'`) and a module (`python3 -m json.tool`)
# stay structured: their first operand is code or a module name, not a script
# file, and either can print the file as it is. The script needs one of the
# SCRIPT_FILE extensions: `php bin/console debug:config … x.yaml` prints YAML.
# `uv run`, `deno run` and `bun run` put a `run` word before the script.
INTERPRETER = re.compile(
    r"(?:php[\d.]*|python[\d.]*|node|ruby[\d.]*|perl|bash|sh|deno|bun|uv)"
)
SCRIPT_FILE = re.compile(r"[\w./-]+\.(?:php|py|js|mjs|cjs|ts|rb|pl|sh|bash)")
# The word after a stdin redirection (`< f`, not `<<` or `<(`). It stops at the
# next `<`, so a run of `<` cannot rescan the same text.
STDIN_FILE = re.compile(r"(?<!<)<(?![<(])\s*([^\s<]+)")
# An excluded glob names files grep does NOT read, so its value does not count.
# Only a directory, or a glob that excludes a whole structured type
# (`--exclude=*.json`, `--exclude={*.json,*.yml}`): after
# `--exclude=package-lock.json` or `--exclude='*-lock.json'` the other .json
# files are still read. `--include` is left alone on purpose:
# `grep -rhoE '"v": "[^"]+"' --include=composer.json .` reads exactly those files.
EXCLUDE_VALUE = re.compile(r"--exclude(-dir)?(?:=|\s+)(\S+)")
WHOLE_TYPE_GLOB = re.compile(
    r"\*\.(?:json|jsonl|ya?ml|toml|xml|csv|tsv)", re.IGNORECASE
)
# grep's pattern is what it searches FOR, not a file it reads: in
# `grep -c 'hooks.json' notes.md` the only input is notes.md. The pattern is
# the first operand, unless `-e`/`--regexp` or `-f`/`--file` supply it; then
# every operand is a file. A `-f` file is read, but as a list of patterns:
# grep prints lines of the operands only, so nothing is extracted from it.
# Only a stage whose command word is grep, egrep or fgrep is read this way;
# `xargs grep`, `git grep` and the like keep their names in the check, and so
# does a grep without a file operand, which reads stdin (`grep -n5 a.json`).
GREP_COMMAND = re.compile(r"[ef]?grep")
# One shell word: quoted runs, escaped characters and plain characters. Each
# alternative starts on a character no other one accepts, as in _quoted().
SHELL_WORD = re.compile(r"""(?:'[^']*'|"(?:[^"\\]|\\.)*"|\\.|[^\s'"\\])+""", re.DOTALL)
REDIRECTION = re.compile(r"\d*[<>]")
# A `<` or `>` outside quotes. In `version<package.json` it ends the pattern
# and starts a redirection inside one shell word; such a stage is not split.
UNQUOTED_ANGLE = re.compile(r"""'[^']*'|"(?:[^"\\]|\\.)*"|\\.|([<>])""", re.DOTALL)
# Options that take a value, so the word after them is not the pattern.
GREP_SHORT_WITH_VALUE = "efmABCdD"
GREP_LONG_WITH_VALUE = {
    "regexp",
    "file",
    "max-count",
    "after-context",
    "before-context",
    "context",
    "devices",
    "directories",
    "include",
    "exclude",
    "exclude-from",
    "exclude-dir",
    "label",
    "binary-files",
    "group-separator",
}
# The long options without a value (GNU grep 3.12 `--help`). getopt accepts
# any unique prefix (`--regex=` is `--regexp=`), so a prefix is resolved
# against both lists; an ambiguous or unknown one is read as a flag.
GREP_LONG_FLAGS = {
    "basic-regexp", "binary", "byte-offset", "color", "colour", "count",
    "dereference-recursive", "extended-regexp", "files-with-matches",
    "files-without-match", "fixed-strings", "help", "ignore-case",
    "initial-tab", "invert-match", "line-buffered", "line-number",
    "line-regexp", "no-filename", "no-group-separator", "no-ignore-case",
    "no-messages", "null", "null-data", "only-matching", "perl-regexp",
    "quiet", "recursive", "silent", "text", "version", "with-filename",
    "word-regexp",
}  # fmt: skip
GREP_PATTERN_OPTIONS = {"e", "f", "regexp", "file"}
# The stages _drop_grep_patterns() is applied to: STATEMENT_SPLIT and
# STAGE_BREAK together, as single characters, but not inside quotes, so the
# alternation in `grep -n 'a.json\|b' x.py` stays in its pattern word. Quoted
# runs and escapes are matched only to be stepped over; group 1 is a break.
GREP_STAGE_SCAN = re.compile(r"""'[^']*'|"(?:[^"\\]|\\.)*"|\\.|([|;&\n])""", re.DOTALL)

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
FIRST_OPTION = re.compile(r"\s+-([a-zA-Z]*)")
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
    """grep with -c, -q, -l or -L as its first option cluster.

    Every `grep` is tried, also one inside an option cluster (`-egrep -l`),
    as the regex `grep\\b\\s+-[a-zA-Z]*[cqlL][a-zA-Z]*\\b` did.
    """
    for g in GREP.finditer(stmt):
        m = FIRST_OPTION.match(stmt, g.end())
        if (
            m
            and any(c in m.group(1) for c in "cqlL")
            and _boundary_after(stmt, m.end())
        ):
            return True
    return False


def _locates(stmt: str) -> bool:
    r"""grep whose leading option clusters include one with -n.

    Same verdict as `grep\b\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*n[a-zA-Z]*\b`: the
    options are read one cluster at a time instead of letting the nested
    repetition backtrack over them.
    """
    scanned_to = -1
    for g in GREP_ARGS.finditer(stmt):
        # A grep inside an option cluster that an earlier grep already read
        # (`grep -xgrep -n`) sees the rest of the same run, which held no -n.
        if g.start() < scanned_to:
            continue
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
        scanned_to = pos
    return False


def _last_backref_before_print(stmt: str) -> int:
    """Start of the last `\\<digit>` in stmt that a later `p` follows, or -1."""
    last_p = stmt.rfind("p")
    best = -1
    for m in BACKREF.finditer(stmt, 0, max(last_p, 0)):
        best = m.start()
    return best


def _extracts(stmt: str) -> bool:
    """True when the statement extracts a field with grep, awk or sed."""
    backref = None  # computed on the first sed -n … s/ stage, then reused
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
        if pos >= 0:
            if backref is None:
                backref = _last_backref_before_print(stmt)
            if backref >= pos:
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


def _api_answers_raw(stmt: str) -> bool:
    """Every `gh api`/`glab api` stage in stmt asks a raw-file or text endpoint.

    A single call that answers JSON — another `api` stage or a `gh … --json`
    stage — keeps the statement structured, so a raw fetch next to a list
    call does not exempt the list call. Each call is read up to the next one,
    because one stage can hold two (`cat <(glab api …) <(glab api …)`).
    """
    raw = False
    for start, end in _stages(stmt):
        if _in_order(stmt, start, end, GH_COMMAND, JSON_FLAG) >= 0:
            return False
        calls = [m.end() for m in JSON_API.finditer(stmt, start, end)]
        for pos, until in zip(calls, calls[1:] + [end]):
            if (
                _in_order(stmt, pos, until, GITLAB_RAW_PATH, GITLAB_RAW_SUFFIX) < 0
                and GITHUB_RAW_ACCEPT.search(stmt, pos, until) is None
                and not any(p.search(stmt, pos, until) for p in TEXT_ENDPOINTS)
                and _in_order(stmt, pos, until, GITLAB_ARTIFACT_BY_REF, RAW_SEGMENT) < 0
            ):
                return False
            raw = True
    return raw


def _runs_script(stage: str) -> bool:
    """The stage runs a script file through an interpreter, without inline code.

    Leading `VAR=value` words, and option words before the script, are
    skipped; the first other word must be the script. An option with a
    separate value (`-W ignore`) ends the scan on that value, which is not a
    script, so the stage keeps its structured names in the check.
    """
    words = iter(stage.split())
    for word in words:
        if "=" not in word:
            break
    else:
        return False
    if not INTERPRETER.fullmatch(os.path.basename(word)):
        return False
    for word in words:
        if word.startswith("-") or "=" in word or word == "run":
            continue
        if INTERPRETER.fullmatch(word):  # `uv run python3 x.py`
            continue
        return SCRIPT_FILE.fullmatch(word.strip("'\"")) is not None
    return False


def _drop_excluded(match: re.Match) -> str:
    """Blank an --exclude-dir value, or an --exclude of whole structured types."""
    value = match.group(2)
    # Only bash expands a brace list, and only an unquoted one: grep reads
    # `--exclude='{*.json,*.yml}'` as one literal pattern.
    if value.startswith("{") and value.endswith("}"):
        globs = value[1:-1].split(",")
    else:
        globs = [value.strip("'\"")]
    if match.group(1) or all(WHOLE_TYPE_GLOB.fullmatch(g) for g in globs):
        return " "
    return match.group(0)


def _grep_long_option(name: str) -> str:
    """The long option a possibly abbreviated name selects, or name itself."""
    if name in GREP_LONG_WITH_VALUE or name in GREP_LONG_FLAGS:
        return name
    matches = [
        o for o in (*GREP_LONG_WITH_VALUE, *GREP_LONG_FLAGS) if o.startswith(name)
    ]
    return matches[0] if len(matches) == 1 else name


def _blank_grep_patterns(cmd: str) -> str:
    """Apply _drop_grep_patterns() to every stage of every statement.

    Each stage keeps its length, so the result lines up with cmd. It runs
    before OPTION_VALUES: `-F 'x'` there is a commit message file, but in a
    grep it is the fixed-strings flag before the pattern.
    """
    out: list[str] = []
    start = 0
    for m in GREP_STAGE_SCAN.finditer(cmd):
        if m.group(1):
            out.append(_drop_grep_patterns(cmd[start : m.start()]) + m.group(1))
            start = m.end()
    out.append(_drop_grep_patterns(cmd[start:]))
    return "".join(out)


def _shell_word_spans(stage: str) -> list[tuple[int, int]] | None:
    """The spans of stage's shell words, or None for an unbalanced quote."""
    words: list[tuple[int, int]] = []
    pos = 0
    for m in SHELL_WORD.finditer(stage):
        if stage[pos : m.start()].strip():
            return None
        words.append(m.span())
        pos = m.end()
    return None if stage[pos:].strip() else words


def _grep_option(word: str) -> tuple[int, int | None]:
    """For one grep option word: (words its value takes after this one, where
    a pattern's blanking starts in the word that holds it, or None).

    A long option takes its value after `=` or as the next word; in a short
    cluster the first letter that takes a value ends it, with the value either
    the rest of the word or, when the letter is last, the next word. The start
    lets the caller blank `ex.json` in `-oex.json` and keep `-o`; it covers the
    option letter too, so no dangling `-e` is left to take the next word, and
    it is 0 when nothing would be left but the dash.
    """
    if word.startswith("--"):
        name, eq, _ = word[2:].partition("=")
        name = _grep_long_option(name)
        if name not in GREP_LONG_WITH_VALUE:
            return 0, None
        return int(not eq), 0 if name in GREP_PATTERN_OPTIONS else None
    for k, letter in enumerate(word[1:], start=2):
        if letter in GREP_SHORT_WITH_VALUE:
            step = int(k == len(word))
            if letter not in GREP_PATTERN_OPTIONS:
                return step, None
            return step, 0 if step or k == 2 else k - 1
    return 0, None


def _redirection_width(word: str) -> int:
    """How many words a redirection at word takes: 2 for `<`, 1 for `<a.json`, else 0."""
    if not REDIRECTION.match(word):
        return 0
    return 2 if REDIRECTION.fullmatch(word) else 1


def _glued_redirection(word: str) -> bool:
    """Does word hold a `<` or `>` outside quotes, as `version<a.json` does?"""
    return any(m.group(1) for m in UNQUOTED_ANGLE.finditer(word))


def _grep_roles(
    text: list[str], i: int
) -> tuple[list[tuple[int, int]], list[int]] | None:
    """grep's patterns as (word index, start in word) and its file operands
    as word indexes, from text[i] on.

    None when a word glues a redirection to something else (`version<a.json`):
    then the words cannot be told apart and every name counts.
    """
    patterns: list[tuple[int, int]] = []
    operands: list[int] = []
    options_done = False
    while i < len(text):
        word = text[i]
        width = _redirection_width(word)
        if width:
            # `< in.json` or `<in.json`: a file grep reads, never the pattern.
            i += width
            continue
        if _glued_redirection(word):
            return None
        if options_done or not word.startswith("-") or word == "-":
            operands.append(i)
        elif word == "--":
            options_done = True
        else:
            step, start = _grep_option(word)
            i += step
            if start is not None:
                patterns.append((i, start))
        i += 1
    return patterns, operands


def _drop_grep_patterns(stage: str) -> str:
    """Blank the pattern words of a grep stage, see GREP_COMMAND.

    The stage comes back unchanged when it is not a grep, or when it does not
    split into shell words (an unbalanced quote): then every name counts, as
    before, rather than none.
    """
    words = _shell_word_spans(stage)
    if words is None:
        return stage
    text = [stage[a:b] for a, b in words]
    i = 0
    while i < len(text) and "=" in text[i]:  # leading VAR=value words
        i += 1
    if i == len(text) or not GREP_COMMAND.fullmatch(os.path.basename(text[i])):
        return stage
    roles = _grep_roles(text, i + 1)
    if roles is None:
        # A redirection glued to another word: every name counts.
        return stage
    patterns, operands = roles
    if not patterns and operands:  # no -e/-f: the first operand is the pattern
        patterns.append((operands.pop(0), 0))
    if all(text[j] == "-" for j in operands):
        # grep reads stdin (no operand, or only `-`): keep the pattern in the
        # check, as before.
        return stage
    out = list(stage)
    for i, start in patterns:
        if i < len(words):
            a, b = words[i]
            a += start
            out[a:b] = " " * (b - a)
    return "".join(out)


def _stage_names_structured(stage: str) -> bool:
    """True when one pipeline stage names a structured file it reads.

    In a script run (_runs_script) only a file on the script's stdin counts
    (`< data.json`); elsewhere every name counts except excluded globs and
    directories. grep's pattern is already blank (_executable_text).
    """
    if _runs_script(stage):
        return any(
            re.search(STRUCT, m.group(1), re.IGNORECASE)
            for m in STDIN_FILE.finditer(stage)
        )
    return bool(
        re.search(STRUCT, EXCLUDE_VALUE.sub(_drop_excluded, stage), re.IGNORECASE)
    )


def _names_structured(text: str) -> bool:
    """True when text names a structured file as input to a text tool's stream.

    Each stage is judged by _stage_names_structured() and read once, so the
    test stays linear in the length.
    """
    return any(
        _stage_names_structured(stmt[start:end])
        for stmt in STATEMENT_SPLIT.split(text)
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
    cmd = _blank_grep_patterns(_strip_quoted_heredocs(cmd or ""))
    for pattern in OPTION_VALUES:
        cmd = pattern.sub(" ", cmd)
    return cmd


def reads_structured(stmt: str) -> bool:
    """True when the statement's input is structured data.

    Either it names a structured file, or it calls an API that answers JSON and
    no parser has consumed that answer yet and the endpoint is not one that
    returns a file's raw content. Only the deny level asks this: the
    advisory level stays filename-based on purpose, so an ordinary
    `gh api … | head` does not start warning.
    """
    if _names_structured(stmt):
        return True
    return (
        _calls_json_api(stmt) and not _api_parsed(stmt) and not _api_answers_raw(stmt)
    )


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
    if not _names_structured(cmd):
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
