"""Rewrite `cli.md`'s usage block from `just --list` over `dvc_dat/dvc_dat.just`; `--check` writes nothing.

The block sits between the `<!-- usage -->` and `<!-- /usage -->` comments. The recipes' `#` comment lines are
the descriptions `just --list` prints, so a recipe added to the justfile reaches the page, or `just docs check`
fails. Run by `just docs`.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PAGE = REPO / "doc" / "cli.md"
BLOCK = re.compile(r"(<!-- usage -->\n```\n).*?(```\n<!-- /usage -->)", re.DOTALL)


def usage() -> str:
    """The recipes, in file order, one per line."""
    out = subprocess.run(["just", "--justfile", "dvc_dat/dvc_dat.just", "--list", "--unsorted",
                          "--list-heading", "", "--list-prefix", ""],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout
    return "\n".join(line.rstrip() for line in out.splitlines() if line.strip()) + "\n"


def main(argv: list) -> int:
    text = PAGE.read_text()
    if not BLOCK.search(text):
        print(f"{PAGE}: no usage block", file=sys.stderr)
        return 1
    new = BLOCK.sub(lambda m: m.group(1) + usage() + m.group(2), text)
    if new == text:
        return 0
    if "--check" in argv:
        print("doc/cli.md: the usage block is stale; run `just docs`", file=sys.stderr)
        return 1
    PAGE.write_text(new)
    print("doc/cli.md: usage block rewritten")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
