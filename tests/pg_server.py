"""The one place the test suite gets a Postgres server: ``DVC_DAT_TEST_PG``, set explicitly.

There is no default address. Unset, every Postgres case skips, saying how to enable it. Set, the
cases make and drop databases and schemas on that server, so it must be a disposable one (a
docker ``postgres`` container, CI's service). A server that is set and does not answer fails,
so CI's ``postgres`` job never skips green.

Port 5433 is refused unless ``DVC_DAT_TEST_PG_ALLOW_5433=1`` is also set: on the development
laptop 5433 is where the Cloud SQL proxy to the production ledger database listens (SVP 1548).
The port counted is every one the address names (each host of a multi-host URL, a ``port=``
query parameter), and ``PGPORT`` or 5432 for a host that names none, as libpq resolves it.
``tests/conftest.py`` checks this before collection, so a refused address stops the run whole.
"""

import os
import re
from urllib.parse import parse_qs, urlsplit

import pytest

ENV = "DVC_DAT_TEST_PG"
ALLOW_5433 = "DVC_DAT_TEST_PG_ALLOW_5433"
GUARDED_PORT = 5433

HOW = (f"set {ENV} to a disposable server, e.g. "
       f"`docker run -d -p 5432:5432 -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16` and "
       f"{ENV}=postgresql://postgres@localhost:5432/postgres")


def ports(url: str) -> set:
    """Every TCP port a Postgres address names, as libpq would resolve it."""
    default = int(os.environ.get("PGPORT") or 5432)
    if not url.startswith(("postgres://", "postgresql://")):       # key=value conninfo
        found = {int(p) for v in re.findall(r"\bport\s*=\s*'?([\d,]+)", url) for p in v.split(",") if p}
        return found or {default}
    rest = url.partition("://")[2]
    netloc = re.split(r"[/?]", rest, maxsplit=1)[0].rpartition("@")[2]
    query = parse_qs(urlsplit("//x/?" + rest.partition("?")[2]).query)
    qports = [int(p) for v in query.get("port", []) for p in v.split(",") if p]
    found = set(qports)
    for part in netloc.split(","):
        port = urlsplit("//" + part).port if part else None
        found.add(port if port is not None else (qports[0] if qports else default))
    return found


def redact(url: str) -> str:
    """The address without its password, for messages."""
    return re.sub(r"(://[^:/@?]*):[^@/?]*@", r"\1:***@", url)


def refusal(url: str) -> "str | None":
    """Why ``url`` may not be used, or None."""
    if GUARDED_PORT in ports(url) and os.environ.get(ALLOW_5433) != "1":
        return (f"{ENV}={redact(url)} names port {GUARDED_PORT}, where this laptop's Cloud SQL proxy to the "
                f"production ledger listens; the Postgres tests create and drop databases there. Use another "
                f"port, or set {ALLOW_5433}=1 if this server is disposable.")
    return None


def configured() -> "str | None":
    """``DVC_DAT_TEST_PG`` when set and allowed; None when unset. Never connects."""
    url = os.environ.get(ENV)
    if not url:
        return None
    why = refusal(url)
    if why:
        pytest.fail(why, pytrace=False)
    return url


def server() -> str:
    """The server for a Postgres case: skips when ``DVC_DAT_TEST_PG`` is unset, fails when refused."""
    url = configured()
    if url is None:
        pytest.skip(f"Postgres case: {HOW}")
    return url


def check_environment() -> None:
    """Refuse the whole run before collection when ``DVC_DAT_TEST_PG`` names a guarded port."""
    url = os.environ.get(ENV)
    why = url and refusal(url)
    if why:
        raise pytest.UsageError(why)
