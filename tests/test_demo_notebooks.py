"""Every demo notebook (doc/DAT Demos/demo-*.ipynb, and api-walkthrough) runs top to bottom, and matches its paired script.

Each is executed in a fresh kernel from this venv, in memory: the committed
.ipynb (outputs kept) is not rewritten here; ``just demo`` does that (``just walkthrough`` for api-walkthrough,
whose notebook build_notebook.py generates from the script, with cell ids a re-run leaves alone).

Each notebook is paired by jupytext with a ``py:percent`` script beside it
(``doc/DAT Demos/jupytext.toml``): the script is the reviewable source, the notebook
keeps the outputs, and an edit to either is carried to the other by
``jupytext --sync`` (``just demo`` runs it first). The pairing test refuses a
pair that has drifted.
"""

import importlib.util
import os
import sys
from pathlib import Path

import jupytext
import nbformat
import pytest
from nbclient import NotebookClient

HERE = Path(__file__).parent.parent / "doc" / "DAT Demos"
DEMOS = sorted(p.name for p in HERE.glob("demo-*.ipynb"))
NOTEBOOKS = [*DEMOS, "api-walkthrough.ipynb"]


def test_every_notebook_has_its_script():
    assert DEMOS
    assert sorted(p.name for p in HERE.glob("demo-*.py")) == [Path(n).with_suffix(".py").name for n in DEMOS]


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_the_notebook_runs(name, monkeypatch):
    # This venv's kernel ahead of any user-level ``python3`` kernelspec, and its python first on PATH.
    monkeypatch.setenv("JUPYTER_PATH", str(Path(sys.prefix) / "share" / "jupyter"))
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    nb = nbformat.read(HERE / name, as_version=4)
    NotebookClient(nb, timeout=120, kernel_name="python3", resources={"metadata": {"path": str(HERE)}}).execute()
    errors = [o for c in nb.cells for o in c.get("outputs", []) if o.get("output_type") == "error"]
    assert not errors


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_the_notebook_matches_its_paired_script(name):
    nb = nbformat.read(HERE / name, as_version=4)
    script = jupytext.read(HERE / Path(name).with_suffix(".py").name)
    cells = [(c.cell_type, c.source) for c in nb.cells]
    paired = [(c.cell_type, c.source) for c in script.cells]
    assert cells == paired, f"{name}: the .py and the .ipynb have drifted; run `just demo` (jupytext --sync)"


def test_a_generated_notebooks_cell_ids_come_from_its_cells():
    spec = importlib.util.spec_from_file_location("build_notebook", HERE / "build_notebook.py")
    build_notebook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_notebook)
    nb = nbformat.read(HERE / "api-walkthrough.ipynb", as_version=4)
    ids = [c.id for c in nb.cells]
    assert ids == build_notebook.stable_ids(nb.cells), "edit the .py and run `just walkthrough`"
    assert len(set(ids)) == len(ids)
