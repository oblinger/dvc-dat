"""The example notebooks run top to bottom against the library as it is."""
import json
import subprocess
import sys
from pathlib import Path

EXAMPLES = Path(__file__).parent.parent / "examples"


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
    out = run_notebook("walkthrough.ipynb", tmp_path)
    assert "$ dat catalog.experiment epochs=5\n<Dat: runs/" in out


def test_ledger_walkthrough_runs(tmp_path):
    out = run_notebook("ledger_walkthrough.ipynb", tmp_path)
    assert "-  2  game/G7      court    str:hs-wood-2\n+  2  game/G7      court    str:hs-wood-3" in out
    assert "at 1 {'court': 'hs-wood-2', 'sport': 'bb'}" in out
    assert "+  3  game/G7      run      dat:runs/G7-r1" in out
    assert "{'shots': [12, 40, 77]}" in out
