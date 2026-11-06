"""The two stores the ledger suite runs over: SQLite in a folder, Postgres by DSN.

``make(backend, folder)`` opens a fresh ledger. Postgres: one schema per ledger in a
database made for this test session (dropped at its end), the art store in
``folder/art``. The server is ``DVC_DAT_TEST_PG``, read by ``tests/pg_server.py``: no
default address; unset, the ``pg`` cases skip; set and unreachable, they fail; port 5433
refused without ``DVC_DAT_TEST_PG_ALLOW_5433=1``.
"""

import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

import pg_server
from dvc_dat.ledger import Ledger

BACKENDS = ["sqlite", "pg"]
SERVER = None                   # DVC_DAT_TEST_PG, set by database(); never a default

_db = {"url": None, "why": None, "name": None}


def _admin():
    import psycopg

    assert SERVER and not pg_server.refusal(SERVER), "only the server DVC_DAT_TEST_PG names, via database()"
    return psycopg.connect(SERVER, autocommit=True, connect_timeout=2)


def database() -> str:
    """The session's database URL (made on first use); skips when ``DVC_DAT_TEST_PG`` is unset."""
    global SERVER
    SERVER = pg_server.server()     # skips when unset, fails when refused: before any connection
    if _db["url"] is None and _db["why"] is None:
        try:
            with _admin() as c:
                name = f"dvcdat_test_{uuid.uuid4().hex[:10]}"
                c.execute(f'CREATE DATABASE "{name}"')
            parts = urlsplit(SERVER)
            _db["name"] = name
            _db["url"] = urlunsplit((parts.scheme, parts.netloc, "/" + name, "", ""))
        except Exception as e:          # no psycopg, no server: named and not there fails (CI's pg job never skips green)
            _db["why"] = f"no Postgres at {pg_server.redact(SERVER)}: {pg_server.redact(str(e))}"
    if _db["url"] is None:
        pytest.fail(_db["why"], pytrace=False)
    return _db["url"]


def drop() -> None:
    if _db["name"]:
        with _admin() as c:
            c.execute(f'DROP DATABASE IF EXISTS "{_db["name"]}" WITH (FORCE)')
        _db["name"] = _db["url"] = None


def dsn(folder: Path) -> str:
    """A fresh schema in the session database, as a ledger DSN with its art in ``folder/art``."""
    import psycopg

    url = database()
    schema = f"l_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(f'CREATE SCHEMA "{schema}"')
    return f"{url}?options=-csearch_path%3D{schema}&art={Path(folder) / 'art'}"


def make(backend: str, folder: Path) -> Ledger:
    if backend == "sqlite":
        return Ledger(folder, create=True)
    return Ledger(dsn(folder), create=True)
