"""The four ledger notebooks (doc/DAT Demos/ledger-*.py) execute top to bottom, as the acceptance test.

Each runs in a fresh kernel from this venv, in a temp copy of what it needs (the
script and the `demo_game` stand-in), so its scratch
folders never land in the checkout. The just notebook needs `just` on PATH.
"""

import os
import shutil
import sys
from pathlib import Path

import jupytext
import pytest
from nbclient import NotebookClient

DEMOS = Path(__file__).parent.parent.parent / "doc" / "DAT Demos"
NAMES = ["ledger-triples", "ledger-values", "ledger-dats", "ledger-just"]


@pytest.mark.parametrize("name", NAMES)
def test_the_ledger_notebook_runs(name, tmp_path, monkeypatch):
    if name == "ledger-just" and shutil.which("just") is None:
        pytest.skip("just is not installed")
    shutil.copytree(DEMOS / "demo_game", tmp_path / "demo_game", ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setenv("JUPYTER_PATH", str(Path(sys.prefix) / "share" / "jupyter"))
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    nb = jupytext.read(DEMOS / f"{name}.py")
    NotebookClient(nb, timeout=300, kernel_name="python3", resources={"metadata": {"path": str(tmp_path)}}).execute()
    errors = [o for c in nb.cells for o in c.get("outputs", []) if o.get("output_type") == "error"]
    assert not errors
