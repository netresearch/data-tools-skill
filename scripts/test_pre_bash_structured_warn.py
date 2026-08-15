#!/usr/bin/env python3
"""Cases for scripts/pre_bash_structured_warn.py — run it, read its verdict.

Every case is a command shape that actually occurred in a session; the
comments name what each one protects against.
"""

import json
import os
import subprocess
import sys
import tempfile
import uuid

HOOK = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "pre_bash_structured_warn.py"
)

# (name, expected verdict, command)
VERDICT_CASES = [
    # Extraction — denied.
    ("grep -oE aus .json", "DENY", """grep -oE '"name": "[^"]+"' pkg.json"""),
    (
        "grep | awk aus .jsonl",
        "DENY",
        """grep '"shape"' /tmp/x.jsonl | awk '{print $2}'""",
    ),
    ("awk -F print aus .yaml", "DENY", "awk -F: '{print $2}' config.yaml"),
    ("grep | cut aus .csv", "DENY", "grep foo data.csv | cut -d, -f2"),
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
]


def run(cmd: str, session_id: str | None = None) -> tuple[str, bool]:
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
    return verdict, "systemMessage" in p.stdout


def main() -> int:
    fails = 0
    sid = f"test-{uuid.uuid4()}"
    try:
        for name, want, cmd in VERDICT_CASES:
            got, _ = run(cmd)
            ok = got == want
            fails += 0 if ok else 1
            print(
                f"  {'OK  ' if ok else 'FEHL'} {name:44} erwartet={want:5} erhalten={got}"
            )

        for name, want, cmd in ADVISORY_CASES:
            # Fresh session per case so the dedup does not hide a real firing.
            _, got = run(cmd, f"{sid}-{uuid.uuid4()}")
            ok = got == want
            fails += 0 if ok else 1
            print(
                f"  {'OK  ' if ok else 'FEHL'} {name:44} erwartet={want!s:5} erhalten={got}"
            )

        # Dedup: same rule twice in one session warns once; a new session warns again.
        first = run("cat a.json", sid)[1]
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
        run("cat a.json", "../../../../tmp/evil")
        escaped = os.path.exists("/tmp/evil") or os.path.exists(
            os.path.join(tempfile.gettempdir(), "..", "evil")
        )
        ok = not escaped
        fails += 0 if ok else 1
        print(
            f"  {'OK  ' if ok else 'FEHL'} {'Pfad-Traversal in der Session-ID':44} "
            f"erwartet=False erhalten={escaped}"
        )
    finally:
        for stale in os.listdir(tempfile.gettempdir()):
            if stale.startswith("data-tools-hook-seen-"):
                os.unlink(os.path.join(tempfile.gettempdir(), stale))

    print("  ---- Fehlschlaege:", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
