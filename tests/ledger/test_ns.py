"""DAT 1051: `ns`, one namespace object on `Dat`, on a revision and on a transaction."""
import os

import pytest

from dvc_dat import DatManager, Namespace
from dvc_dat.ledger import Fn, LedgerNamespace, Rev
from test_memo import world  # noqa: F401  (the fixture)


def test_rev_ns_load_is_the_dotted_name_at_the_revision(world):
    ns = world.at().ns
    assert isinstance(ns, LedgerNamespace)
    f = ns.load("ledger_kinds.cut")
    assert isinstance(f, Fn) and f.name == "ledger_kinds.cut" and f.kind == "ledger"
    assert ns.load("os.path.join") is os.path.join
    assert ns.load("not_a_module_anywhere", default=None) is None
    with pytest.raises(ImportError):
        ns.load("not_a_module_anywhere")
    assert not hasattr(Rev, "resolve")


def test_t_ns_mount_writes_the_db_mount_rows_and_rev_ns_mounts_shows_them(L):
    with L.transaction(by="t") as t:
        t.ns.mount("pkg", root="pkg", repo="r")
    assert L.at()["db/mount/pkg"] == {"db/root": "pkg", "db/repo": "r"}
    assert L.at().ns.mounts() == {"pkg": {"root": "pkg", "repo": "r"}}


def test_mount_is_refused_off_a_transaction_and_without_its_rows(L):
    with pytest.raises(TypeError, match=r"t\.ns\.mount"):
        L.at().ns.mount("pkg", root="pkg", repo="r")
    with L.transaction(by="t") as t:
        with pytest.raises(TypeError, match="root"):
            t.ns.mount("pkg", repo="r")
        with pytest.raises(TypeError, match="folder"):
            t.ns.mount(at="pkg", folder="pkg")
        t.add("x", "y", "z")
    assert L.at().ns.mounts() == {}


def test_plain_ns_mounts_is_the_mount_table(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "cfg.yaml").write_text("a: 1\n")
    ns = DatManager(dat_folders=[str(tmp_path / "data")]).ns
    assert type(ns) is Namespace
    ns.mount(file=str(tmp_path / "cfg.yaml"), at="cfg")
    ns.mount(value={"b": 2}, at="consts")
    table = ns.mounts()
    assert table["cfg"] == str(tmp_path / "cfg.yaml")
    assert table["dt"] == "dvc_dat.dat_tools"                     # the world's own names
    assert "consts" not in table                                  # a value has no location
    assert ns.load("cfg.a") == 1 and ns.load("consts.b") == 2
