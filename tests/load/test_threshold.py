"""The load floor: 4 processes x 2000 operations, 200 eval keys; fails on any invariant failure or
when tx/s falls below half the value measured for that store on the recording machine.

A floor, not a target. Runs only with ``DAT_LOAD=1`` (about a minute per store). The Postgres case
needs ``DAT_LOAD_PG``, a server URL (``postgresql://user:pw@host:port/db``); it makes and drops its
own schema. The throughput check applies on a host with a recorded floor (``FLOORS``); elsewhere
only the invariants are checked. Source numbers: ``tests/load/README.md``.
"""

import json
import os
import platform
import subprocess
import sys
import uuid
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROCESSES, OPS, KEYS = 4, 2000, 200

#: host -> store -> tx/s floor: half the 4-process tx/s recorded there (tests/load/README.md).
FLOORS = {"dexter": {"sqlite": 143.0, "pg": 63.0}}

pytestmark = pytest.mark.skipif(os.environ.get("DAT_LOAD") != "1", reason="load floor: set DAT_LOAD=1")


def _target(store, tmp_path):
    if store == "sqlite":
        return str(tmp_path / "ledger"), None
    server = os.environ.get("DAT_LOAD_PG")
    if not server:
        pytest.skip("Postgres load floor: set DAT_LOAD_PG to a server URL")
    schema = f"load_{uuid.uuid4().hex[:10]}"
    return f"{server}?options=-csearch_path%3D{schema}&art={tmp_path / 'art'}", (server, schema)


@pytest.mark.parametrize("store", ["sqlite", "pg"])
def test_load_floor(tmp_path, store):
    ledger, pg = _target(store, tmp_path)
    try:
        out = subprocess.run(
            [sys.executable, "-m", "tests.load", "--processes", str(PROCESSES), "--transactions", str(OPS),
             "--keys", str(KEYS), "--ledger", ledger, "--results", str(tmp_path / "results"), "--timeout", "900"],
            cwd=ROOT, capture_output=True, text=True, timeout=1200)
    finally:
        if pg:
            import psycopg

            with psycopg.connect(pg[0], autocommit=True) as c:
                c.execute(f'DROP SCHEMA IF EXISTS "{pg[1]}" CASCADE')
    files = sorted((tmp_path / "results").glob("*.json"))
    assert files, out.stdout + out.stderr
    res = json.loads(files[-1].read_text())
    assert res["invariants"]["failures"] == [], json.dumps(res["invariants"], indent=1)[:4000]
    assert res["errors"] == [] and res["timed_out"] == [], (res["errors"][:5], res["timed_out"])
    assert out.returncode == 0, out.stdout + out.stderr
    host = platform.node().split(".")[0].lower()
    floor = FLOORS.get(host, {}).get(store)
    if floor is None:
        warnings.warn(f"no {store} load floor recorded for {host}: invariants checked, throughput "
                      f"{res['tx_per_s']} tx/s not")
        return
    assert res["tx_per_s"] >= floor, f"{store} on {host}: {res['tx_per_s']} tx/s < floor {floor}"
