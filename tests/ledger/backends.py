"""The two stores the ledger suite runs over: SQLite in a folder, Postgres by DSN.

``make(backend, folder)`` opens a fresh ledger. Postgres: one schema per ledger in a
database made for this test session (dropped at its end), the art store in
``folder/art``. The server is ``DVC_DAT_TEST_PG`` (default the docker one,
``postgresql://postgres:dvcdat@localhost:5433/postgres``); unreachable, the ``pg``
cases skip.
"""

import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

from dvc_dat.ledger import Ledger

BACKENDS = ["sqlite", "pg"]
SERVER = os.environ.get("DVC_DAT_TEST_PG", "postgresql://postgres:dvcdat@localhost:5433/postgres")

_db = {"url": None, "why": None, "name": None}


def _admin():
    import psycopg

    return psycopg.connect(SERVER, autocommit=True, connect_timeout=2)


def database() -> str:
    """The session's database URL (made on first use); skips when no server is reachable."""
    if _db["url"] is None and _db["why"] is None:
        try:
            with _admin() as c:
                name = f"dvcdat_test_{uuid.uuid4().hex[:10]}"
                c.execute(f'CREATE DATABASE "{name}"')
            parts = urlsplit(SERVER)
            _db["name"] = name
            _db["url"] = urlunsplit((parts.scheme, parts.netloc, "/" + name, "", ""))
        except Exception as e:          # no psycopg, no server: the pg cases skip, saying why
            _db["why"] = f"no Postgres at {SERVER}: {e}"
    if _db["url"] is None:
        pytest.skip(_db["why"])
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
