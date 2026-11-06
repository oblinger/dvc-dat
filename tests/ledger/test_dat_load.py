"""``dat.at`` and ``dat.load``: the global reference resolves across ledgers (SVP 248)."""

from __future__ import annotations

import pytest

from dvc_dat import Dat, DatManager, dat
from dvc_dat.ledger import Ledger, Rev, Value


def _ledger(tmp_path, name):
    return Ledger(tmp_path / name, create=True)


def _sealed(L, obj, name):
    v = Value.Blob(obj)
    with L.transaction(by="test") as t:
        v.seal(t, name=name)
    return v


def test_at_names_a_revision_on_any_open_ledger(tmp_path):
    a, b = _ledger(tmp_path, "aa"), _ledger(tmp_path, "bb")
    _sealed(a, 1, "x")
    _sealed(b, 2, "y")
    rev = dat.at(f"bb@{b.at().id}")
    assert isinstance(rev, Rev) and rev.ledger is b
    assert dat.at(a.at().id, a).ledger is a                     # a bare revision takes the default
    assert dat.at(str(a.at().id), "aa").ledger is a             # by name too
    with pytest.raises(ValueError):
        dat.at("nope")


def test_load_by_name_and_by_sha(tmp_path):
    a, b = _ledger(tmp_path, "aa"), _ledger(tmp_path, "bb")
    va = _sealed(a, "alpha", "x")
    _sealed(b, "beta", "x")
    rev = a.at().id
    assert dat.load(f"aa@{rev}:x").obj == "alpha"
    assert dat.load(f"aa@{rev}:sha256:{va.hash}").obj == "alpha"
    assert dat.load("x", b).obj == "beta"                       # a bare name reads the default at its head
    assert dat.load(f"sha256:{va.hash}", "aa").obj == "alpha"
    assert dat.load("x", "aa").subject == va.subject


def test_load_reads_the_revision_named(tmp_path):
    a = _ledger(tmp_path, "aa")
    _sealed(a, 1, "first")
    rev = a.at().id
    late = _sealed(a, 2, "second")
    with pytest.raises(KeyError):
        dat.load(f"aa@{rev}:sha256:{late.hash}")                # not yet sealed at that revision
    assert dat.load(f"aa@{a.at().id}:sha256:{late.hash}").obj == 2


def test_a_sha_no_value_has_is_a_key_error(tmp_path):
    a = _ledger(tmp_path, "aa")
    _sealed(a, 1, "x")
    with pytest.raises(KeyError, match="no value"):
        dat.load(f"aa@{a.at().id}:sha256:{'0' * 64}")


def test_no_ledger_is_the_managers_load(tmp_path, monkeypatch):
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    monkeypatch.chdir(tmp_path)
    Dat.manager = DatManager(dat_folders=[str(tmp_path / "dats")])
    try:
        made = Dat.manager.create({"dat": {"do": "builtins.print"}}, path="one/two")
        assert dat.load("one/two").get_path() == made.get_path()
    finally:
        Dat.manager = None


def test_a_project_with_a_ledger_never_falls_through(tmp_path, monkeypatch):
    a = _ledger(tmp_path, "aa")
    monkeypatch.setenv("DAT_LEDGER", str(a.path))
    with pytest.raises(KeyError):
        dat.load("no/such/name")
