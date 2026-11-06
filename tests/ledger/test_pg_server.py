"""How the suite gets its Postgres server (``tests/pg_server.py``, SVP 1548): only from ``DVC_DAT_TEST_PG``;
unset skips; port 5433 refused unless ``DVC_DAT_TEST_PG_ALLOW_5433=1``.

No test here connects to anything: every refused address is on ``refused.invalid``, a name that never
resolves, so even a broken guard could not reach the proxy on this laptop's 5433.
"""

import os
import subprocess
import sys
from pathlib import Path

import backends
import pg_server
import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARDED = "postgresql://u:secretpw@refused.invalid:5433/postgres"


@pytest.fixture
def env(monkeypatch):
    for var in (pg_server.ENV, pg_server.ALLOW_5433, "PGPORT"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.mark.parametrize("url,expected", [
    ("postgresql://u@h/db", {5432}),
    ("postgresql://u@h:5433/db", {5433}),
    ("postgres://u:pw@h:6000/db?art=/a", {6000}),
    ("postgresql://u@h1:5432,h2:5433/db", {5432, 5433}),
    ("postgresql://u@h/db?port=5433", {5433}),
    ("postgresql://u@/db?host=/tmp&port=5433", {5433}),
    ("host=h port=5433 dbname=d", {5433}),
    ("host=h dbname=d", {5432}),
])
def test_ports_counts_every_port_the_address_names(env, url, expected):
    assert pg_server.ports(url) == expected


def test_a_host_with_no_port_counts_pgport(env):
    env.setenv("PGPORT", "5433")
    assert pg_server.ports("postgresql://u@h/db") == {5433}
    assert pg_server.refusal("postgresql://u@h/db")


def test_unset_skips_saying_how_to_enable(env):
    with pytest.raises(pytest.skip.Exception, match=pg_server.ENV):
        pg_server.server()
    with pytest.raises(pytest.skip.Exception, match=pg_server.ENV):
        backends.database()


def test_port_5433_is_refused_before_any_connection(env):
    env.setenv(pg_server.ENV, GUARDED)
    for get in (pg_server.server, backends.database):
        with pytest.raises(pytest.fail.Exception, match=pg_server.ALLOW_5433) as e:
            get()
        assert "secretpw" not in str(e.value)


@pytest.mark.parametrize("allow", ["0", "", "yes"])
def test_only_allow_1_lifts_the_refusal(env, allow):
    env.setenv(pg_server.ENV, GUARDED)
    env.setenv(pg_server.ALLOW_5433, allow)
    with pytest.raises(pytest.fail.Exception):
        pg_server.server()


def test_allow_1_lifts_it(env):
    env.setenv(pg_server.ENV, GUARDED)
    env.setenv(pg_server.ALLOW_5433, "1")
    assert pg_server.server() == GUARDED            # returned, not connected to


def test_another_port_is_used_as_given(env):
    env.setenv(pg_server.ENV, "postgresql://u@refused.invalid:5432/postgres")
    assert pg_server.server() == "postgresql://u@refused.invalid:5432/postgres"


def test_a_refused_address_stops_the_whole_run_before_collection():
    run_env = {k: v for k, v in os.environ.items() if k not in (pg_server.ALLOW_5433, "PGPORT")}
    run_env[pg_server.ENV] = GUARDED
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:xdist",
                          "-p", "no:cacheprovider", str(Path(__file__))],
                         cwd=ROOT, env=run_env, capture_output=True, text=True, timeout=300)
    text = out.stdout + out.stderr
    assert out.returncode == pytest.ExitCode.USAGE_ERROR, text
    assert pg_server.ALLOW_5433 in text and "secretpw" not in text
