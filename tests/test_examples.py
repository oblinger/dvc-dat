"""The walkthrough notebook runs top to bottom against the library as it is."""
import json
import subprocess
import sys
from pathlib import Path

NOTEBOOK = Path(__file__).parent.parent / "examples" / "walkthrough.ipynb"


def test_walkthrough_runs(tmp_path):
    cells = json.loads(NOTEBOOK.read_text())["cells"]
    source = "\n\n".join("".join(c["source"]) for c in cells if c["cell_type"] == "code")
    script = tmp_path / "walkthrough.py"
    script.write_text(source)
    done = subprocess.run([sys.executable, str(script)], cwd=tmp_path,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "$ dat catalog.experiment epochs=5\n<Dat: runs/" in done.stdout
