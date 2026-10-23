#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""Cases for scripts/pre_bash_structured_warn.py — run it, read its verdict.

Most cases are command shapes that actually occurred in a session; the
constructed ones say so. The comments name what each one protects against.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid

HOOK = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "pre_bash_structured_warn.py"
)

# The one line the first advisory carries so the dedup is visible exactly once.
SUPPRESSION_NOTICE = "further matches of this rule stay silent this session"

# (name, expected verdict, command)
VERDICT_CASES = [
    # Serializer rewrites — denied.
    ("yq -i auf .gitlab-ci.yml", "DENY", "yq -i '.build.needs = []' .gitlab-ci.yml"),
    ("yq --inplace", "DENY", "yq --inplace '.a = 1' config.yaml"),
    ("jq > dieselbe json", "DENY", "jq '.version = \"2\"' package.json > package.json"),
    ("yq > neue yaml", "DENY", "yq '.x' in.yml > out.yml"),
    ("jq | sponge", "DENY", "jq '.a=1' a.json | sponge a.json"),
    ("yq lesen geht durch", "durch", "yq '.build.script' .gitlab-ci.yml"),
    ("jq nach txt geht durch", "durch", "jq -r '.name' pkg.json > name.txt"),
    # `--jq` / `--yq` are FLAGS of gh and glab, not the serializer. The output
    # is a fresh capture of an API answer; no structured file is written back.
    (
        "gh api --jq nach .json geht durch",
        "durch",
        "gh api repos/o/r/pulls/comments/1 --jq '{path,body}' > /tmp/s/cr.json",
    ),
    (
        "gh api --jq= nach .json geht durch",
        "durch",
        "gh api repos/o/r --jq='.name' > /tmp/s/o.json",
    ),
    (
        "glab api --yq nach .yaml geht durch",
        "durch",
        "glab api projects/1 --yq '.path' > /tmp/s/p.yaml",
    ),
    # …und ein echtes jq mit vorangehendem Pfad bleibt gesperrt.
    ("/usr/bin/jq > neue json", "DENY", "/usr/bin/jq '.a=1' a.json > b.json"),
    # `-i` is the include-headers flag of gh/glab api, not yq's in-place flag,
    # so `--yq … -i` must not reach the rewrite branch either.
    (
        "glab api --yq mit -i geht durch",
        "durch",
        "glab api projects/1 --yq '.path' -i",
    ),
    (
        "Rewrite mit Freigabe geht durch",
        "durch",
        "DATA_TOOLS_REWRITE_OK=1 jq . a.json > a.json",
    ),
    # Extraction — denied.
    ("grep -oE aus .json", "DENY", """grep -oE '"name": "[^"]+"' pkg.json"""),
    (
        "grep | awk aus .jsonl",
        "DENY",
        """grep '"shape"' /tmp/x.jsonl | awk '{print $2}'""",
    ),
    ("awk -F print aus .yaml", "DENY", "awk -F: '{print $2}' config.yaml"),
    ("grep | cut aus .csv", "DENY", "grep foo data.csv | cut -d, -f2"),
    # Constructed to pin the scans that replaced the extraction regex: a sed
    # substitution prints a field only through a back-reference, and grep feeds
    # cut only through a pipe, not through `&`.
    (
        "sed -n 's/…/\\1/p' aus .json",
        "DENY",
        """sed -n 's/.*"name": "\\(.*\\)".*/\\1/p' pkg.json""",
    ),
    ("sed -n ohne Rueckverweis geht durch", "durch", "sed -n 's/a/b/p' f.json"),
    # A grep inside an option cluster counts as a grep of its own, as it did
    # for the regex: `-l` after it is a list grep, which only warns.
    (
        "grep in einem Optionsbuendel vor -l",
        "durch",
        "grep -egrep -l x f.json | head -1",
    ),
    (
        "grep & cut ist keine Pipe",
        "durch",
        "grep foo data.json & cut -d, -f2 notes.txt",
    ),
    # Comment/presence greps — a structured parser cannot see comments at all.
    ("grep -c auf .json", "durch", "grep -c 'GITLEAKS' /tmp/x.json"),
    ("grep -q auf .yaml", "durch", "grep -q 'TODO' ci.yaml"),
    ("grep -l ueber .toml", "durch", "grep -l 'edition' Cargo.toml"),
    # grep -n locates a line; piping only to sed is cosmetic, not extraction.
    (
        "grep -n | sed ist kosmetisch",
        "durch",
        "grep -n 'name' pkg.json | sed 's/^/  /'",
    ),
    (
        "grep -n | cut bleibt Extraktion",
        "DENY",
        "grep -n 'name' pkg.json | cut -d: -f2",
    ),
    # Statement scoping: the .jsonl read and the .txt grep are separate statements.
    (
        "zwei Anweisungen, nur .txt extrahiert",
        "durch",
        (
            "python3 detect.py --file /tmp/a.jsonl > /tmp/after.txt\n"
            "grep -oE \"'shape'\" /tmp/after.txt | sed 's/^/  /'"
        ),
    ),
    # A quoted heredoc body is data being written, not a command being run.
    (
        "Extraktionsmuster nur im zitierten Heredoc",
        "durch",
        "cat <<'EOF' > doc.md\ngrep -oE '\"x\"' f.json | awk '{print}'\nEOF",
    ),
    # Prose ABOUT commands is not a command. This blocked the pull request that
    # introduced the hook, whose body explained the patterns it matches.
    (
        "Muster nur im PR-Body",
        "durch",
        """gh pr create --title "gate" --body "denies grep -oE '\\"x\\"' f.json here" """,
    ),
    (
        "Muster nur in der Commit-Nachricht",
        "durch",
        """git commit -m "document that grep -oE on a .json is denied" """,
    ),
    (
        "Muster nur in echo",
        "durch",
        """echo "grep -oE '\\"a\\"' f.json | awk '{print}'" """,
    ),
    # The gh/glab field form: the '=' belongs to the field name, so it needs its
    # own branch in the pattern. Written as one alternative it never matched and
    # every review reply carrying an example was denied.
    (
        "Muster in gh api -f body=",
        "durch",
        """gh api repos/o/r/pulls/1/comments/2/replies -f body='fixed the grep -oE "x" f.json case'""",
    ),
    (
        "Muster in --body= mit Gleichheitszeichen",
        "durch",
        """gh pr comment 1 --body='inline grep -oE "a" f.json'""",
    ),
    (
        "Muster in glab mr note -m",
        "durch",
        """glab mr note 1 -m 'siehe grep -oE "a" f.json'""",
    ),
    # --body-file names a path, not prose: nothing to strip, nothing to flag.
    ("body-file bleibt unberuehrt", "durch", "gh pr create --body-file /tmp/b.md"),
    # A JSON API response carries no filename. The list endpoints are what fleet
    # work uses, and extraction from them was silent while the same extraction
    # against a file was denied.
    (
        "Extraktion aus git/trees",
        "DENY",
        """gh api repos/o/r/git/trees/main?recursive=1 | grep -oE '"path": "[^"]+"'""",
    ),
    (
        "Extraktion aus gh --json",
        "DENY",
        """gh pr list --json number,title | grep '"title"' | cut -d'"' -f4""",
    ),
    (
        "awk -F auf einen API-Koerper",
        "DENY",
        """glab api projects/1/pipelines | awk -F'"' '{print $4}'""",
    ),
    # A raw-file endpoint answers the file itself, not JSON. Observed 2026-10-23:
    # reading a pinned digest out of a Dockerfile was denied as JSON extraction.
    (
        "Dockerfile ueber GitLab files/…/raw",
        "durch",
        'export GITLAB_HOST=git.netresearch.de; P=orocommerce%2Foro-commerce-enterprise-reference; glab api "projects/$P/repository/files/Dockerfile-init-test/raw?ref=main" | grep -n \'ci-env\' ; d=$(glab api "projects/$P/repository/files/Dockerfile-init-test/raw?ref=main" | grep -o \'sha256:[0-9a-f]*\' | head -1); echo "pinned=$d"',
    ),
    # Constructed: the same for GitHub's contents API with the raw media type.
    (
        "gh contents mit raw-Accept",
        "durch",
        """gh api -H 'Accept: application/vnd.github.raw' repos/o/r/contents/Dockerfile | grep -o 'sha256:[0-9a-f]*'""",
    ),
    (
        "gh contents mit v3.raw-Accept",
        "durch",
        """gh api repos/o/r/contents/Dockerfile -H "Accept: application/vnd.github.v3.raw" | grep -o 'FROM .*'""",
    ),
    # Constructed: the exemption covers the raw file, not what it is called. A
    # raw .json is still JSON; a contents call without the raw media type
    # answers JSON; `raw+json` answers JSON outside the contents API; and a
    # raw fetch must not exempt a JSON call in the same statement.
    (
        "raw .json ueber GitLab bleibt DENY",
        "DENY",
        """glab api "projects/1/repository/files/composer.json/raw?ref=main" | grep -o '"name": "[^"]*"'""",
    ),
    (
        "gh contents ohne raw-Accept bleibt DENY",
        "DENY",
        """gh api repos/o/r/contents/Dockerfile | grep -o '"sha": "[^"]*"'""",
    ),
    (
        "gh raw+json-Accept bleibt DENY",
        "DENY",
        """gh api -H 'Accept: application/vnd.github.raw+json' repos/o/r/issues/1 | grep -o '"body": "[^"]*"'""",
    ),
    (
        "raw-Abruf neben JSON-Aufruf bleibt DENY",
        "DENY",
        """glab api projects/1/repository/files/D/raw | cat - <(glab api projects/1) | grep -o '"name": "[^"]*"'""",
    ),
    (
        "zwei API-Aufrufe in einer Stufe bleiben DENY",
        "DENY",
        """cat <(glab api projects/1/repository/files/D/raw) <(glab api projects/1) | grep -o '"name": "[^"]*"'""",
    ),
    (
        "raw-Abruf neben gh --json bleibt DENY",
        "DENY",
        """gh pr list --json title | cat - <(glab api projects/1/repository/files/D/raw) | grep -o '"title": "[^"]*"'""",
    ),
    (
        "Extraktion aus glab api projects/1",
        "DENY",
        """glab api projects/1 | grep -o '"name": "[^"]*"'""",
    ),
    # #83: a job log is plain text. Both commands were denied on 1.9.6.
    (
        "GitLab-Job-Trace mit grep | sed",
        "durch",
        """glab api projects/1/jobs/2/trace | grep -E "scenarios? \\(" | sed 's/\\x1b\\[[0-9;]*m//g'""",
    ),
    (
        "GitHub-Job-Logs mit grep | sed",
        "durch",
        """gh api repos/o/r/actions/jobs/1/logs | grep -E "FAIL" | sed 's/x/y/'""",
    ),
    (
        "Job-Trace mit Variable als ID",
        "durch",
        """glab api "projects/$P/jobs/$JOB/trace" | grep -oE 'took [0-9]+s'""",
    ),
    (
        "GitLab-Artefakt raw als Text",
        "durch",
        """glab api "projects/1/jobs/artifacts/main/raw/build.log?job=test" | grep -o 'FAIL.*'""",
    ),
    # Review of PR 97: a ref can span segments, and one file out of a job's
    # archive is raw too.
    (
        "GitLab-Artefakt raw mit mehrteiliger Ref",
        "durch",
        """glab api "projects/1/jobs/artifacts/refs/merge-requests/12/head/raw/build.log?job=t" | grep -o 'FAIL.*'""",
    ),
    (
        "GitLab-Artefakt per Job-ID",
        "durch",
        """glab api projects/1/jobs/2/artifacts/build.log | grep FAIL | head -1""",
    ),
    (
        "GitLab artifacts/tree bleibt DENY",
        "DENY",
        """glab api projects/1/jobs/2/artifacts/tree | grep -o '"name": "[^"]*"'""",
    ),
    (
        "GitLab artifacts/keep bleibt DENY",
        "DENY",
        """glab api -X POST projects/1/jobs/2/artifacts/keep | grep -o '"status": "[^"]*"'""",
    ),
    (
        "GitLab artifacts ohne Pfad bleibt DENY",
        "DENY",
        """glab api projects/1/jobs/2/artifacts | grep -o '"x": "[^"]*"'""",
    ),
    # Constructed: the job OBJECT answers JSON, a raw artifact with a structured
    # name is still that format, and a log call must not exempt a JSON call.
    (
        "GitHub-Job-Objekt bleibt DENY",
        "DENY",
        """gh api repos/o/r/actions/jobs/1 | grep '"name"' | awk -F'"' '{print $4}'""",
    ),
    (
        "GitLab-Job-Objekt bleibt DENY",
        "DENY",
        """glab api projects/1/jobs/2 | grep -o '"status": "[^"]*"'""",
    ),
    (
        "GitLab-Jobliste bleibt DENY",
        "DENY",
        """glab api projects/1/jobs | grep -o '"name": "[^"]*"'""",
    ),
    (
        "Trace-Suffix mit Wortfortsetzung bleibt DENY",
        "DENY",
        """glab api projects/1/jobs/2/traces | grep -o '"x": "[^"]*"'""",
    ),
    (
        "Artefakt raw .json bleibt DENY",
        "DENY",
        """glab api "projects/1/jobs/artifacts/main/raw/report.json?job=t" | grep -o '"a": "[^"]*"'""",
    ),
    (
        "Trace neben JSON-Aufruf bleibt DENY",
        "DENY",
        """cat <(glab api projects/1/jobs/2/trace) <(glab api projects/1/jobs/2) | grep -o '"name": "[^"]*"'""",
    ),
    (
        "JSON-Aufruf vor Trace bleibt DENY",
        "DENY",
        """cat <(glab api projects/1/jobs/2) <(glab api projects/1/jobs/2/trace) | grep -o '"name": "[^"]*"'""",
    ),
    # #83: a structured name that is only a script's argument says nothing about
    # what the script prints.
    (
        "php-Skript mit .json-Argument vor grep | awk",
        "durch",
        """php probe.php cases.json 2>&1 | grep -v "SomeException" | awk '{print $1}'""",
    ),
    (
        "python3-Skript mit Optionen vor grep -o",
        "durch",
        """FOO=1 python3 -u scripts/run.py --config ci.yaml | grep -o 'took [0-9]*'""",
    ),
    # Review of PR 97: runners with a `run` word, versioned names, quoted paths.
    (
        "uv run Skript mit .json-Argument",
        "durch",
        """uv run probe.py cases.json 2>&1 | grep -v SomeException | awk '{print $1}'""",
    ),
    (
        "deno run Skript mit .json-Argument",
        "durch",
        """deno run probe.ts cases.json | grep -v X | awk '{print $1}'""",
    ),
    (
        "python3.12 Skript mit .json-Argument",
        "durch",
        """python3.12 probe.py cases.json | grep -v X | awk '{print $1}'""",
    ),
    (
        "zitierter Skriptname",
        "durch",
        """php "probe.php" cases.json | grep -o 'took [0-9]*'""",
    ),
    # …but the script must be a script file, and its stdin is still read.
    (
        "Konsole ohne Endung mit .yaml bleibt DENY",
        "DENY",
        """php bin/console debug:config framework config/packages/framework.yaml | grep secret | awk '{print $2}'""",
    ),
    (
        ".json auf stdin des Skripts bleibt DENY",
        "DENY",
        """python3 script.py < data.json | grep -o '"name": "[^"]*"'""",
    ),
    (
        "uv run python -m json.tool bleibt DENY",
        "DENY",
        """uv run python -m json.tool a.json | grep -o '"v": "[^"]*"'""",
    ),
    # Constructed: every way of printing the file itself stays denied.
    (
        "python -m json.tool bleibt DENY",
        "DENY",
        """python3 -m json.tool a.json | grep -o '"v": "[^"]*"'""",
    ),
    (
        "python -c bleibt DENY",
        "DENY",
        """python3 -c "print(open('a.json').read())" | grep -o '"v": "[^"]*"'""",
    ),
    (
        "node -e bleibt DENY",
        "DENY",
        """node -e 'process.stdout.write(require("fs").readFileSync("a.json"))' | grep -o '"v": "[^"]*"'""",
    ),
    (
        "curl auf .json bleibt DENY",
        "DENY",
        """curl -s https://x/a.json | grep -o '"v":"[^"]*"'""",
    ),
    (
        "git show auf package.json bleibt DENY",
        "DENY",
        """git show HEAD:package.json | grep -o '"version": "[^"]*"'""",
    ),
    (
        "unzip -p auf package.json bleibt DENY",
        "DENY",
        """unzip -p a.zip package.json | grep -o '"version": "[^"]*"'""",
    ),
    # #83 asked to ignore --include globs as well. An included glob names the
    # files grep reads, so the extraction through it stays denied; an excluded
    # glob names files grep skips.
    (
        "grep -o ueber --include=composer.json bleibt DENY",
        "DENY",
        """grep -rhoE '"version": *"[^"]+"' --include=composer.json .""",
    ),
    (
        "--exclude=*.json zaehlt nicht als Eingabe",
        "durch",
        """grep -rhoE 'v[0-9.]+' --exclude=*.json --exclude-dir node_modules src""",
    ),
    # Review of PR 97: excluding ONE named file leaves the other .json files in.
    (
        "--exclude=package-lock.json bleibt DENY",
        "DENY",
        """grep -rhoE '"version": *"[^"]+"' --exclude-dir=node_modules --exclude=package-lock.json .""",
    ),
    # Observed 2026-10-23 next to the Dockerfile case: TSV field extraction.
    (
        "awk -F Tab aus .tsv",
        "DENY",
        """awk -F'\\t' '$3=="exists"{print $1}' state.tsv""",
    ),
    # …but only until a parser has consumed the response. After --jq the stream
    # is text, and grepping text is what one does with it.
    (
        "nach --jq ist es Text",
        "durch",
        """gh api repos/o/r/pulls --jq '.[].title' | grep -oE '^[A-Z]+'""",
    ),
    (
        "nach -q ist es Text",
        "durch",
        """gh api repos/o/r/pulls -q '.[].title' | grep -oE '^[A-Z]+'""",
    ),
    (
        "jq nachgeschaltet",
        "durch",
        """gh api repos/o/r/pulls | jq -r '.[].title'""",
    ),
    # The short form must not exempt a plain `grep -q` on a file — that is the
    # case this hook exists for, and a bare `-q` appears in it.
    (
        "grep -q auf .json bleibt unberuehrt",
        "durch",
        "grep -q 'name' pkg.json",
    ),
    (
        "grep -oE auf .json neben einem gh-Aufruf bleibt DENY",
        "DENY",
        """gh pr view 1 -q .title && grep -oE '"a": "[^"]+"' f.json""",
    ),
    # Nothing structured in sight.
    ("grep auf Textdatei", "durch", "grep -oE 'ERROR' app.log | head -3"),
    ("jq ist korrekt", "durch", "jq -r '.name' pkg.json"),
    # The real thing still gets caught when it sits next to prose.
    (
        "echte Extraktion neben Prosa bleibt DENY",
        "DENY",
        """git commit -m "note" && grep -oE '"a": "[^"]+"' f.json""",
    ),
]

# (name, expected advisory?, command)
ADVISORY_CASES = [
    ("cat auf .json warnt", True, "cat package.json"),
    ("grep -c auf .yaml warnt", True, "grep -c TODO ci.yaml"),
    (
        "python -c auf .json warnt",
        True,
        "python3 -c \"import json;print(json.load(open('a.json')))\"",
    ),
    ("Textdatei warnt nicht", False, "cat README.md"),
    ("jq warnt nicht", False, "jq . pkg.json"),
    # #83: the script's output is grepped, not cases.json.
    (
        "Skript-Argument .json warnt nicht",
        False,
        'php probe.php cases.json 2>&1 | grep -v "SomeException"',
    ),
    ("--exclude=*.yml warnt nicht", False, 'grep -rn "X" --exclude=*.yml src'),
    # #83 also listed this one. grep does read the .yml files, so it still warns.
    (
        "--include=*.yml warnt weiter",
        True,
        'grep -rn "SomeClass" --include=*.php --include=*.yml src',
    ),
    ("Kontrolle ohne Glob", False, 'grep -rn "SomeClass" src'),
]


def run(cmd: str, session_id: str | None = None) -> tuple[str, bool, str]:
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}}
    if session_id is not None:
        payload["session_id"] = session_id
    p = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    verdict = "DENY" if '"deny"' in p.stdout else "durch"
    return verdict, "systemMessage" in p.stdout, p.stdout


def run_raw(payload_text: str) -> tuple[int, str]:
    """Run the hook on a literal stdin text; return exit code and stdout."""
    p = subprocess.run(
        [sys.executable, HOOK],
        input=payload_text,
        capture_output=True,
        text=True,
        check=False,
    )
    return p.returncode, p.stdout


HOOK_TIMEOUT = 3  # seconds, hooks/hooks.json
# (name, expected verdict, command): long backslash runs inside and after a
# quoted option value. The hook must answer within its timeout, and the answer
# must still be the right one.
TIMED_CASES = [
    (
        "Extraktion, dann offener --body mit 5000 Backslashes",
        "DENY",
        'grep -oE \'"a": "[^"]+"\' f.json; gh pr create --body "' + "\\" * 5000,
    ),
    (
        "-m '… ohne schliessendes Anfuehrungszeichen",
        "durch",
        "git commit -m '" + "\\" * 5000,
    ),
    (
        "-f body='… ohne schliessendes Anfuehrungszeichen",
        "durch",
        "gh api repos/o/r/issues -f body='" + "\\" * 5000,
    ),
]

# Repeated words in one long command. Each pattern that put `[^|;&]*` between
# two words, and the quoted-heredoc pattern, rescanned the rest of the command
# from every occurrence of its first word: 11 KB of `sed -n` after a .json
# name took 8-11 s. At 100 KB that is minutes, so these cases fail by TIMEOUT
# if any of those scans turns quadratic again.
LONG = 100_000


def repeated(word: str, size: int = LONG) -> str:
    return (word * (size // len(word) + 1))[:size]


TIMED_CASES += [
    ("100 KB sed -n nach .json", "durch", "cat a.json " + repeated("sed -n ")),
    ("100 KB awk -F nach .json", "durch", "cat a.json " + repeated("awk -F ")),
    ("100 KB grep -a nach .json", "durch", "cat a.json " + repeated("grep -a ")),
    # The -n (locate) and -c/-q/-l (count/test) exemptions are judged only for
    # a statement that extracts, so these end in `| cut`.
    (
        "100 KB -nnn…5 vor | cut",
        "DENY",
        "grep -" + repeated("n") + "5 a.json | cut -f1",
    ),
    (
        "100 KB -ccc…5 vor | cut",
        "DENY",
        "grep -" + repeated("c") + "5 a.json | cut -f1",
    ),
    (
        "100 KB Optionsbuchstaben ohne Wortgrenze",
        "durch",
        "cat a.json grep -" + repeated("o") + "1",
    ),
    ("100 KB gh x", "durch", repeated("gh x ")),
    ("100 KB gh api", "durch", repeated("gh api ")),
    ("100 KB gh api x", "durch", repeated("gh api x ")),
    (
        "100 KB glab api files/ ohne raw vor grep -o",
        "DENY",
        "glab api /repository/files/x " * (LONG // 29) + "| grep -o y",
    ),
    (
        "100 KB glab api files/…/raw vor grep -o",
        "durch",
        # Whole calls: repeated() cuts the last one mid-word, which is no
        # longer a raw fetch.
        "glab api /repository/files/x/raw " * (LONG // 33) + "| grep -o y",
    ),
    (
        "100 KB glab api jobs/…/trace vor grep -o",
        "durch",
        "glab api /jobs/1/trace " * (LONG // 23) + "| grep -o y",
    ),
    (
        "100 KB /jobs/ ohne Schraegstrich vor grep -o",
        "DENY",
        "glab api /jobs/" + repeated("x") + " | grep -o y",
    ),
    (
        "100 KB Skriptlaeufe mit .json",
        "durch",
        repeated("php a.php b.json | ") + "grep -o y",
    ),
    (
        "100 KB --exclude vor .json",
        "DENY",
        "grep -o y " + "--exclude=a " * (LONG // 12) + " b.json",
    ),
    (
        "100 KB --exclude= ohne Leerzeichen vor .json",
        "DENY",
        "grep -o y " + repeated("--exclude=") + " b.json",
    ),
    (
        "100 KB < im Skriptlauf",
        "durch",
        "php a.php " + repeated("< ") + "| grep -o y",
    ),
    (
        "100 KB jobs/artifacts/ ohne /raw/",
        "DENY",
        "glab api " + repeated("/jobs/artifacts/") + " | grep -o y",
    ),
    ("100 KB yq", "durch", repeated("yq ")),
    ("100 KB jq >", "durch", repeated("jq > ")),
    ("100 KB offene Heredocs", "durch", repeated("cat <<'A' ")),
    (
        "100 KB Heredocs mit verschiedenen Begrenzern",
        "durch",
        "".join(f"cat <<'D{i}' " for i in range(LONG // 12)),
    ),
    (
        "2 x 100 KB sed -n s/ in vielen Stufen",
        "durch",
        "cat f.json " + repeated("|sed -n s/") + repeated("\\x"),
    ),
    (
        "100 KB grep in Optionsbuendeln vor | cut",
        "DENY",
        "grep " + repeated("-xgrep ") + " a.json | cut -f1",
    ),
    # …and the verdict at the end of such a command is still the right one.
    (
        "100 KB sed -n, dann echte Extraktion",
        "DENY",
        "cat a.json " + repeated("sed -n ") + '\ngrep -oE \'"a": "[^"]+"\' f.json',
    ),
    (
        "100 KB jq >, dann yq -i",
        "DENY",
        repeated("jq > ") + "\nyq -i '.a = 1' c.yaml",
    ),
]


def run_timed(cmd: str) -> tuple[str, float]:
    """Verdict and wall time; TIMEOUT when the hook outlives its timeout."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
    start = time.monotonic()
    try:
        p = subprocess.run(
            [sys.executable, HOOK],
            input=payload,
            capture_output=True,
            text=True,
            check=False,
            timeout=HOOK_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT", time.monotonic() - start
    verdict = "DENY" if '"deny"' in p.stdout else "durch"
    return verdict, time.monotonic() - start


def main() -> int:
    fails = 0
    sid = f"test-{uuid.uuid4()}"
    try:
        # The hook runs on every Bash call; past its timeout the call goes
        # through unchecked. One second leaves room for interpreter start.
        for name, want, cmd in TIMED_CASES:
            got, took = run_timed(cmd)
            ok = got == want and took < 1.0
            fails += 0 if ok else 1
            print(
                f"  {'OK  ' if ok else 'FEHL'} {name:44} erwartet={want:5} "
                f"erhalten={got} in {took:.2f}s"
            )

        for name, want, cmd in VERDICT_CASES:
            got, _, _ = run(cmd)
            ok = got == want
            fails += 0 if ok else 1
            print(
                f"  {'OK  ' if ok else 'FEHL'} {name:44} erwartet={want:5} erhalten={got}"
            )

        for name, want, cmd in ADVISORY_CASES:
            # Fresh session per case so the dedup does not hide a real firing.
            _, got, _ = run(cmd, f"{sid}-{uuid.uuid4()}")
            ok = got == want
            fails += 0 if ok else 1
            print(
                f"  {'OK  ' if ok else 'FEHL'} {name:44} erwartet={want!s:5} erhalten={got}"
            )

        # Dedup: same rule twice in one session warns once; a new session warns again.
        _, first, first_out = run("cat a.json", sid)
        second = run("cat b.json", sid)[1]
        third = run("cat c.json", f"{sid}-other")[1]
        for name, want, got in (
            ("erste Warnung feuert", True, first),
            ("zweite Warnung schweigt", False, second),
            ("neue Session warnt wieder", True, third),
        ):
            ok = got == want
            fails += 0 if ok else 1
            print(
                f"  {'OK  ' if ok else 'FEHL'} {name:44} erwartet={want!s:5} erhalten={got}"
            )

        # The first firing says that the rule now goes quiet (#41): silence
        # after it must not read as "the rule did not match".
        got = SUPPRESSION_NOTICE in first_out
        ok = got
        fails += 0 if ok else 1
        print(
            f"  {'OK  ' if ok else 'FEHL'} "
            f"{'erste Warnung nennt die Unterdrueckung':44} erwartet=True  erhalten={got}"
        )

        # A deny is never deduped — the command must be blocked every time.
        d1 = run("""grep -oE '"a": "[^"]+"' f.json""", sid)[0]
        d2 = run("""grep -oE '"a": "[^"]+"' f.json""", sid)[0]
        for i, got in ((1, d1), (2, d2)):
            ok = got == "DENY"
            fails += 0 if ok else 1
            print(
                f"  {'OK  ' if ok else 'FEHL'} {'Deny bleibt pro Aufruf, Lauf ' + str(i):44} "
                f"erwartet=DENY  erhalten={got}"
            )
        # A session id carrying path separators must not steer the state file
        # out of the temp directory (SonarCloud: path injection).
        evil_sid = "../../../../tmp/evil"
        run("cat a.json", evil_sid)
        escaped = os.path.exists("/tmp/evil") or os.path.exists(
            os.path.join(tempfile.gettempdir(), "..", "evil")
        )
        # The state file must be named after the digest and sit in the temp
        # directory itself; an unhashed id fails this even where the escaped
        # write itself went nowhere.
        digest = hashlib.sha256(evil_sid.encode("utf-8")).hexdigest()[:16]
        in_tmp = os.path.isfile(
            os.path.join(tempfile.gettempdir(), f"data-tools-hook-seen-{digest}.json")
        )
        escaped = escaped or not in_tmp
        ok = not escaped
        fails += 0 if ok else 1
        print(
            f"  {'OK  ' if ok else 'FEHL'} {'Pfad-Traversal in der Session-ID':44} "
            f"erwartet=False erhalten={escaped}"
        )

        # Fail open: payloads of an unexpected shape and a state file with
        # unexpected content end with exit 0 and no output, never a traceback.
        bad_sid = f"{sid}-badstate"
        bad_key = hashlib.sha256(bad_sid.encode("utf-8")).hexdigest()[:16]
        with open(
            os.path.join(tempfile.gettempdir(), f"data-tools-hook-seen-{bad_key}.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            fh.write("[1]")
        bad_state = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "cat a.json"},
                "session_id": bad_sid,
            }
        )
        for name, text in (
            ("Payload ist eine Liste", "[]"),
            (
                "command ist keine Zeichenkette",
                '{"tool_name": "Bash", "tool_input": {"command": 5}}',
            ),
            ("Zustandsdatei mit Zahlen", bad_state),
        ):
            got = run_raw(text)
            ok = got == (0, "")
            fails += 0 if ok else 1
            print(
                f"  {'OK  ' if ok else 'FEHL'} {'exit 0 ohne Ausgabe: ' + name:44} "
                f"erwartet=(0, '') erhalten=({got[0]}, {len(got[1])} Zeichen)"
            )
    finally:
        for stale in os.listdir(tempfile.gettempdir()):
            if stale.startswith("data-tools-hook-seen-"):
                os.unlink(os.path.join(tempfile.gettempdir(), stale))

    print("  ---- Fehlschlaege:", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
