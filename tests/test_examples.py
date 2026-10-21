"""The walkthrough notebooks (doc/DAT Demos) run top to bottom against the library as it is, and print what they promise."""
import json
import subprocess
import sys
from pathlib import Path

EXAMPLES = Path(__file__).parent.parent / "doc" / "DAT Demos"


def run_notebook(name, tmp_path):
    cells = json.loads((EXAMPLES / name).read_text())["cells"]
    source = "\n\n".join("".join(c["source"]) for c in cells if c["cell_type"] == "code")
    script = tmp_path / (Path(name).stem + ".py")
    script.write_text(source)
    done = subprocess.run([sys.executable, str(script)], cwd=tmp_path,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_walkthrough_runs(tmp_path):
    out = run_notebook("demo-walkthrough.ipynb", tmp_path)
    assert "$ x catalog.experiment epochs=5\n<Dat: runs/" in out

