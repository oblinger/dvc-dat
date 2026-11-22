"""Put a contents cell at the top of each tutorial: its title, then a link to each section.

`python add_contents.py` rewrites the first cell of every tutorial script (`<stem>.py`, the source) and of its
notebook (`<stem>.ipynb`, outputs kept) so both open on the same contents cell: the notebook's title (its `#`
heading, which otherwise first appears below the setup code) and one link per `##` section, plus the `####
Setup` cell. Run again, it replaces the cell it wrote (found by its first line) and changes nothing else; the
notebook is not re-executed, and every other cell keeps its id.

A link targets the anchor the docs site gives the heading: Python-Markdown's `slugify`. The site renders each
notebook cell on its own, so a repeated heading gets the same id again; only its first is listed.
"""
import sys
from pathlib import Path

import jupytext
import nbformat
from markdown.extensions.toc import slugify

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from build_notebook import stable_ids  # noqa: E402

STEMS = ["api-walkthrough", "cli-walkthrough", "demo-walkthrough", "demo-dats", "demo-etl", "demo-rerunning",
         "ledger-triples", "ledger-values", "ledger-dats", "ledger-just"]
MARK = "<!-- contents: written by add_contents.py -->"


def headings(cells: list) -> list:
    """Every markdown heading in the cells, in order: (level, text)."""
    out = []
    for cell in cells:
        if cell.cell_type != "markdown" or cell.source.startswith(MARK):
            continue
        for line in cell.source.splitlines():
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                out.append((level, line[level:].strip()))
    return out


def contents(cells: list) -> str:
    """The contents cell's markdown: the title, then a link per section."""
    seen: set = set()
    title, entries = None, []
    for level, text in headings(cells):
        anchor = slugify(text, "-")
        if level == 1 and title is None:
            title = text
        elif (level == 2 or (level == 4 and text == "Setup")) and anchor not in seen:
            entries.append(f"- [{text}](#{anchor})")
            seen.add(anchor)
    head = f"**{title}**" if title else "**Contents**"
    return "\n".join([MARK, head, "", "Contents:", "", *entries])


def with_contents(cells: list, make_cell) -> list:
    """The cells with the contents cell first: replaced when there, inserted when not."""
    rest = [c for c in cells if not (c.cell_type == "markdown" and c.source.startswith(MARK))]
    return [make_cell(contents(rest)), *rest]


def run(stem: str) -> None:
    script_path, nb_path = HERE / f"{stem}.py", HERE / f"{stem}.ipynb"
    script = jupytext.read(script_path)
    script.cells = with_contents(script.cells, nbformat.v4.new_markdown_cell)
    jupytext.write(script, script_path, fmt="py:percent")
    notebook = nbformat.read(nb_path, as_version=4)
    notebook.cells = with_contents(notebook.cells, nbformat.v4.new_markdown_cell)
    for cell, cell_id in zip(notebook.cells, stable_ids(notebook.cells)):
        cell["id"] = cell_id
    nbformat.write(notebook, nb_path)
    print(stem, len(headings(script.cells)), "headings")


if __name__ == "__main__":
    for name in sys.argv[1:] or STEMS:
        run(name)
