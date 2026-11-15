"""Generate a demo notebook from its py:percent script, with cell ids that do not churn.

`python build_notebook.py api-walkthrough` writes `api-walkthrough.ipynb` from `api-walkthrough.py`, outputs
empty (`just walkthrough` then executes it). A cell's id is the hash of its type and source, so a re-run
leaves every id alone and an edit changes only the edited cell's; the Nth copy of an identical cell gets its
own id, since ids must be unique.
"""
import hashlib
import sys
from collections import Counter
from pathlib import Path

import jupytext
import nbformat

HERE = Path(__file__).parent


def stable_ids(cells: list) -> list:
    """Each cell's id: 8 hex of the hash of its type, source and how many identical cells precede it."""
    seen: Counter = Counter()
    ids = []
    for cell in cells:
        content = (cell.cell_type, cell.source)
        ids.append(hashlib.sha256(repr((*content, seen[content])).encode()).hexdigest()[:8])
        seen[content] += 1
    return ids


def build(stem: str) -> Path:
    """Write `<stem>.ipynb` from `<stem>.py`; its path."""
    notebook = jupytext.read(HERE / f"{stem}.py")
    notebook.nbformat, notebook.nbformat_minor = 4, 5
    for cell, cell_id in zip(notebook.cells, stable_ids(notebook.cells)):
        cell["id"] = cell_id
    path = HERE / f"{stem}.ipynb"
    nbformat.write(notebook, path)
    return path


if __name__ == "__main__":
    print(build(sys.argv[1]))
