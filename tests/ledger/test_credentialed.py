"""A credentialed ledger: ``?credential=VAR`` on a Postgres URI opens it with the password in ``VAR`` and nothing else.

The pure cases need no server. The server cases make two login roles and a database the first owns, with ``CONNECT``
revoked from ``PUBLIC``: the owner opens it through its variable, the other role is refused by the server, and an
unset variable is refused before any connection, whatever ``PGPASSWORD`` holds."""

import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest

import pg_server
from dvc_dat.ledger import Ledger, LedgerError
from dvc_dat.ledger.pgstore import conninfo, credential_of

VAR = "DVC_DAT_TEST_CREDENTIAL"
SECRET = "s3cret-not-in-any-message"


def test_a_uri_without_credential_is_opened_as_before(monkeypatch):
    monkeypatch.setenv(VAR, SECRET)
    uri = "postgresql://u@h:5432/db?options=-csearch_path%3Dx"
    assert credential_of(uri) is None
    assert conninfo(uri) == (uri, {})


def test_credential_names_the_variable_and_is_not_sent_to_the_server(monkeypatch):
    monkeypatch.setenv(VAR, SECRET)
    uri = f"postgresql://u@h:5432/db?options=-csearch_path%3Dx&credential={VAR}"
    assert credential_of(uri) == VAR
    info, kw = conninfo(uri)
    assert "credential" not in info and "options=-csearch_path%3Dx" in info
    assert kw == {"password": SECRET, "passfile": os.devnull}


def test_an_unset_variable_is_refused_naming_it_never_a_value(monkeypatch):
    monkeypatch.delenv(VAR, raising=False)
    monkeypatch.setenv("PGPASSWORD", SECRET)            # libpq's own source does not stand in for it
    with pytest.raises(LedgerError, match=f"{VAR}, which is not set") as e:
        conninfo(f"postgresql://u@h/db?credential={VAR}")
    assert SECRET not in str(e.value)
    monkeypatch.setenv(VAR, "")
    with pytest.raises(LedgerError, match="not set"):
        conninfo(f"postgresql://u@h/db?credential={VAR}")


def test_a_password_in_the_uri_or_a_second_credential_is_refused(monkeypatch):
    monkeypatch.setenv(VAR, SECRET)
    with pytest.raises(LedgerError, match="carries no password") as e:
        conninfo(f"postgresql://u:pw@h/db?credential={VAR}")
    assert ":pw@" not in str(e.value)
    with pytest.raises(LedgerError, match="one environment variable"):
        credential_of(f"postgresql://u@h/db?credential={VAR}&credential=OTHER")
    with pytest.raises(LedgerError, match="one environment variable"):
        credential_of("postgresql://u@h/db?credential=")


@pytest.fixture
def closed_db():
    """``(server URL, owner, owner's password, other, other's password, database)``: a database only its owner may
    connect to; the roles and the database are dropped after."""
    import psycopg

    server = pg_server.server()
    tag = uuid.uuid4().hex[:8]
    owner, other, db = f"dvcdat_owner_{tag}", f"dvcdat_other_{tag}", f"dvcdat_cred_{tag}"
    pw_owner, pw_other = f"o-{uuid.uuid4().hex}", f"x-{uuid.uuid4().hex}"
    with psycopg.connect(server, autocommit=True, connect_timeout=5) as c:
        c.execute(f"CREATE ROLE {owner} LOGIN PASSWORD '{pw_owner}'")
        c.execute(f"CREATE ROLE {other} LOGIN PASSWORD '{pw_other}'")
        c.execute(f'CREATE DATABASE "{db}" OWNER {owner}')
        c.execute(f'REVOKE CONNECT, TEMPORARY ON DATABASE "{db}" FROM PUBLIC')
        trusted = c.execute("SELECT count(*) FROM pg_hba_file_rules WHERE auth_method = 'trust' AND type = 'host'"
                            ).fetchone()[0] > 0 if _can_read_hba(c) else None
    try:
        yield server, owner, pw_owner, other, pw_other, db, trusted
    finally:
        with psycopg.connect(server, autocommit=True, connect_timeout=5) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
            c.execute(f"DROP ROLE IF EXISTS {owner}")
            c.execute(f"DROP ROLE IF EXISTS {other}")


def _can_read_hba(c) -> bool:
    try:
        c.execute("SELECT 1 FROM pg_hba_file_rules LIMIT 1")
        return True
    except Exception:
        return False


def _uri(server: str, user: str, db: str, query: str = "") -> str:
    p = urlsplit(server)
    host = p.netloc.rpartition("@")[2]
    return urlunsplit((p.scheme, f"{user}@{host}", "/" + db, query, ""))


def test_the_owner_opens_it_through_its_variable_and_another_login_is_refused(closed_db, monkeypatch, tmp_path):
    server, owner, pw_owner, other, pw_other, db, trusted = closed_db
    monkeypatch.setenv("DAT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv(VAR, pw_owner)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    L = Ledger(_uri(server, owner, db, f"credential={VAR}"), create=True)
    with L.transaction(by="t") as t:
        t.add("run/1", "metric", "0.5")
    L.close()
    assert Ledger(_uri(server, owner, db, f"credential={VAR}")).at().get("run/1", "metric") == "0.5"
    assert pw_owner not in repr(L) and pw_owner not in L.path

    monkeypatch.setenv("PGPASSWORD", pw_other)          # the other login, with its own right password
    with pytest.raises(LedgerError, match="permission denied|not have CONNECT"):
        Ledger(_uri(server, other, db))

    monkeypatch.delenv(VAR)
    monkeypatch.setenv("PGPASSWORD", pw_owner)          # the right password, but not where the ledger says
    with pytest.raises(LedgerError, match=f"{VAR}, which is not set"):
        Ledger(_uri(server, owner, db, f"credential={VAR}"))

    if trusted is False:                                # the server checks passwords: a wrong one is refused
        monkeypatch.setenv(VAR, "wrong")
        with pytest.raises(LedgerError, match="password authentication failed"):
            Ledger(_uri(server, owner, db, f"credential={VAR}"))
