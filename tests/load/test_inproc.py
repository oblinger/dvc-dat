"""A small run of the in-process leg (``inproc.py``) in a subprocess: N handles x M threads on one
ledger and a flipper; every invariant must hold. The Postgres case needs ``DVC_DAT_TEST_PG``'s server."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PG = os.environ.get("DVC_DAT_TEST_PG", "postgresql://postgres:dvcdat@localhost:5433/postgres")


def _pg_target(tmp_path):
    try:
        import psycopg

        with psycopg.connect(PG, autocommit=True, connect_timeout=2):
            pass
    except Exception as e:      # no psycopg, no server: skip, saying why
        pytest.skip(f"no Postgres at {PG}: {e}")
    schema = f"inproc_{uuid.uuid4().hex[:10]}"
    return f"{PG}?options=-csearch_path%3D{schema}&art={tmp_path / 'art'}", schema


def _drop(schema):
    import psycopg

    with psycopg.connect(PG, autocommit=True) as c:
        c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.mark.parametrize("store,lock", [("sqlite", 10.0), ("sqlite", 0.02), ("pg", 10.0)])
def test_inproc_invariants(tmp_path, store, lock):
    schema = None
    target = str(tmp_path / "ledger")
    if store == "pg":
        target, schema = _pg_target(tmp_path)
    try:
        out = subprocess.run(
            [sys.executable, "-m", "tests.load.inproc", "--handles", "3", "--threads", "6", "--transactions",
             "60", "--flips", "24", "--lock", str(lock), "--ledger", target, "--results",
             str(tmp_path / "results"), "--timeout", "300"],
            cwd=ROOT, capture_output=True, text=True, timeout=600)
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
