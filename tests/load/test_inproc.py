"""A small run of the in-process leg (``inproc.py``) in a subprocess: N handles x M threads on one
ledger and a flipper; every invariant must hold. The Postgres case needs ``DVC_DAT_TEST_PG``
(``tests/pg_server.py``): skips when unset, fails when set and unreachable."""

import os
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pg_server
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _pg_target(tmp_path):
    pg = pg_server.server()         # skips when unset, fails when refused: before any connection
    try:
        import psycopg

        with psycopg.connect(pg, autocommit=True, connect_timeout=2):
            pass
    except Exception as e:      # named and not there fails: CI's pg job never skips green
        pytest.fail(f"no Postgres at {pg_server.redact(pg)}: {pg_server.redact(str(e))}", pytrace=False)
    schema = f"inproc_{uuid.uuid4().hex[:10]}"
    return f"{pg}?options=-csearch_path%3D{schema}", (pg, schema)


def _drop(target):
    import psycopg

    pg, schema = target
    with psycopg.connect(pg, autocommit=True) as c:
        c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.mark.parametrize("store,lock", [("sqlite", 10.0), ("sqlite", 0.02), ("pg", 10.0)])
def test_inproc_invariants(tmp_path, store, lock):
    schema = None
    target = str(tmp_path / "ledger")
    if store == "pg":
        target, schema = _pg_target(tmp_path)   # schema: (server, name), dropped on that server only
    try:
        out = subprocess.run(
            [sys.executable, "-m", "tests.load.inproc", "--handles", "3", "--threads", "6", "--transactions",
             "60", "--flips", "24", "--lock", str(lock), "--ledger", target, "--results",
             str(tmp_path / "results"), "--timeout", "300"],
            cwd=ROOT, capture_output=True, text=True, env={**os.environ, "DAT_CACHE": str(tmp_path / "cache")},
            timeout=600)
    finally:
        if schema:
            _drop(schema)
    files = sorted((tmp_path / "results").glob("*.json"))
    assert files, out.stdout + out.stderr
    res = json.loads(files[-1].read_text())
    assert res["invariants"]["failures"] == [], json.dumps(res["invariants"], indent=1)[:4000]
    assert res["errors"] == [] and res["hung"] == [], (res["errors"][:3], res["hung"])
    assert out.returncode == 0, out.stdout + out.stderr
    assert res["flips"] > 0 and res["reads"] > 0 and res["invariants"]["checked"]["committed"] > 0
