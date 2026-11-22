"""Fail when a tracked file refers to a private workspace: its notes links, paths, people, tracking ids or employer.

This repository is public. A reference to a private notes vault, a home-directory path, a colleague's name, an
internal ticket number or an internal codebase means nothing to a reader here and leaks what should stay private,
so every tracked text file is scanned for those shapes and any hit fails the run.

    python scripts/check_public.py            # every file `git ls-files` lists
    python scripts/check_public.py FILE ...   # just these

Exit 0 clean, 1 on any hit (each printed as path:line: kind: text).
"""
import re
import subprocess
import sys
from pathlib import Path


PATTERNS = {
    "vault link": re.compile(r"\b(?:ha|hook)://"),
    "wiki link": re.compile(r"\[\[[A-Za-z@][^\]\[\n\"'`]*\]\]"),
    "private path": re.compile(r"~/ob\b|/Users/[A-Za-z]|-Users-[A-Za-z]|\bkmr\b|\bclaude-\d+/"),
    "person": re.compile(r"\b(?:Dan|Juan|Martin)\b|\bhuman:dan\b"),
    "tracking id": re.compile(r"\bSVP(?![a-z])|\bDAT ?\d{3,4}\b|\b\d{3,4} [QAR]\d+\b|\bF\d{3,4}\b|\bT\d{3,4}\b"
                              r"|\bTink\b|\brows? \d{3,4}\b|\bR0\d{3}\b|\b\d{4} decision \d|\bQ\d{1,2} \((?:[A-E]|i+)\)"),
    "organization": re.compile(r"sv-pipe|sportsvisio|\bALG2\b|svisio|algorithms2", re.IGNORECASE),
}

NOQA = re.compile(r"noqa:[\s\w,]*")

# The one file that defines the patterns is skipped. The docs builder converts vault links and wiki links into
# site links, so it and its test name those two shapes on purpose.
ALLOW = {
    "scripts/check_public.py": set(PATTERNS),
    "dvc_dat/docs/vault.py": {"vault link", "wiki link"},
    "tests/test_docs_site.py": {"vault link", "wiki link"},
    # the author's credit and the copyright holder, which a license must name
    "LICENSE": {"person"},
    "doc/about.md": {"person"},
}


def tracked() -> list:
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode().split("\0") if p]


def hits(path: str):
    skip = ALLOW.get(path, set())
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
        return
    if path.endswith((".toml", ".lock")):
        skip = skip | {"wiki link"}          # TOML's `[[table]]` arrays
    for n, line in enumerate(text.splitlines(), 1):
        line = NOQA.sub("", line)            # a linter code (`noqa: F401`) is not a tracking id
        for kind, pattern in PATTERNS.items():
            if kind not in skip and pattern.search(line):
                yield n, kind, line.strip()


def main(argv: list) -> int:
    paths = argv or tracked()
    found = 0
    for path in paths:
        for n, kind, line in hits(path):
            found += 1
            print(f"{path}:{n}: {kind}: {line[:200]}")
    if found:
        print(f"check_public: {found} reference(s) to a private workspace", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
