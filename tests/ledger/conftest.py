"""Fixtures for the ledger suite: a fresh ledger per test, once per store (``backends``), and a pinned environment.

The environment provider (the test seam, A51) is pinned so ``run`` is
deterministic: one repo, ``testrepo``, at commit ``abc1234``, clean, its
checkout this folder; ``coded`` writes the matching ``db/repo/testrepo`` clocks.
"""

import dataclasses
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import backends  # noqa: E402
from dvc_dat.ledger import Checkout, Env, set_env_provider  # noqa: E402

ENV = Env({"testrepo": Checkout(None, "abc1234", False, HERE)}, "test-platform")


class EnvBox:
    """The pinned environment; a test calls ``code``/``set`` to move the commit or platform."""

    def __init__(self):
        self.env = ENV

    def __call__(self):
        return self.env

    def code(self, commit="abc1234", dirty=False):
        self.env = dataclasses.replace(self.env, code={"testrepo": Checkout(None, commit, dirty, HERE)})

    def set(self, **kw):
        fields = {"code": self.env.code, "platform": self.env.platform, "record": self.env.record}
        fields.update(kw)
        self.env = Env(**fields)


@pytest.fixture(autouse=True)
def envbox():
    box = EnvBox()
    old = set_env_provider(box)
    yield box
    set_env_provider(old)


@pytest.fixture(autouse=True)
def kept_folder(tmp_path, monkeypatch):
    """Every ``v.seal()`` writes a seal record: into the test's own folder, never ~/.cache."""
    monkeypatch.setenv("DAT_KEPT", str(tmp_path / "kept"))
    return tmp_path / "kept"


@pytest.fixture(params=backends.BACKENDS)
def backend(request):
    """``sqlite`` or ``pg``: every test taking a ledger fixture runs once per store."""
    return request.param


@pytest.fixture
def L(tmp_path, backend):
    return backends.make(backend, tmp_path / "ledger")


def pytest_sessionfinish(session, exitstatus):
    backends.drop()


@pytest.fixture
def coded(L):
    with L.transaction(by="test") as t:
        t.add("db/repo/testrepo/ledger_kinds", "db/version", "1.0.0")
        t.add("db/repo/testrepo", "db/commit", "abc1234")
    return L
