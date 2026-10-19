"""A small run of the load harness in subprocesses; every invariant must hold."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.load
@pytest.mark.parametrize("processes", [1, 4])
def test_load_invariants(tmp_path, processes):
    out = subprocess.run(
        [sys.executable, "-m", "tests.load", "--processes", str(processes), "--transactions", "150",
         "--ledger", str(tmp_path / "ledger"), "--results", str(tmp_path / "results"), "--timeout", "600"],
        cwd=ROOT, capture_output=True, text=True, timeout=900)
    files = sorted((tmp_path / "results").glob("*.json"))
    assert files, out.stdout + out.stderr
    res = json.loads(files[-1].read_text())
    assert res["invariants"]["failures"] == [], json.dumps(res["invariants"], indent=1)[:4000]
    assert res["errors"] == [], res["errors"][:5]
    assert out.returncode == 0, out.stdout + out.stderr
    assert res["ops"]["eval"]["hits"] > 0 and res["ops"]["eval"]["misses"] > 0
