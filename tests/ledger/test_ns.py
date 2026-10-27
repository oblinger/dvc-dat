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
        with pytest.raises(TypeError, match="repo"):
            t.ns.mount("pkg", root="pkg", repo="")
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


def test_a_transaction_reads_the_previous_revision_not_its_pending_writes(L):
    with L.transaction(by="t", lock=10) as t:
        t["g/1"] = {"home": "a"}
        t.add("g/1", "tag", "x")
    with L.transaction(by="t", lock=10) as t:
        t["g/1", "home"] = "b"                       # pending: not seen until the body closes
        t.add("g/2", "home", "c")
        assert t["g/1", "home"] == "a" and t["g/1"]["home"] == "a"
        assert t.get("g/1", "home") == "a" and t.get("g/2", "home") is None
        assert ("g/1", "home", "a") in t and ("g/1", "home", "b") not in t
        assert t.all("g/1", "home") == ["a"] and t.all("g/2", "home") == []
        assert t.history("g/2") == []
        before = t.previous_rev
    assert t.rev["g/1", "home"] == "b" and t.rev["g/2", "home"] == "c"
    assert before.id + 1 == t.rev.id


def test_a_transaction_read_needs_lock(L):
    from dvc_dat.ledger import Unlocked

    with L.transaction(by="t") as t:
        t.add("g/1", "home", "a")
    with pytest.raises(Unlocked):
        with L.transaction(by="t") as t:
            t["g/1", "home"]


def test_a_transaction_reads_values_at_the_previous_revision(world):
    from ledger_kinds import Video

    with world.transaction(by="t", lock=10) as t:
        videos = t.values(kind=Video)
        assert {v.preds["game"] for v in videos} == {"G1", "G2"}
        assert t.value(kind=Video, game="G1").subject == t.load("video/G1").subject
        assert len(t.refs(kind=Video)) == 2
        assert sorted(t.select(("game",), kind=Video)) == [("G1",), ("G2",)]
        t.add("note/1", "text", "x")


def _project(tmp_path, name, *, git=True):
    import subprocess

    root = tmp_path / "proj"
    (root / "data").mkdir(parents=True)
    (root / ".datconfig.yaml").write_text("dat_folders: data\n")
    (root / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "0.1.0"\n')
    if git:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_t_ns_mount_defaults_repo_to_the_project_repository(L, tmp_path, monkeypatch):
    from dvc_dat import core

    root = _project(tmp_path, "My_Proj")
    monkeypatch.setattr(core, "_default_manager", DatManager.load_dat_config(root))
    with L.transaction(by="t") as t:
        t.ns.mount("pkg", root="pkg")                         # repo: the checkout holding .datconfig.yaml
        t.ns.mount("other", root="o", repo="elsewhere")       # a separate repo still names it
    assert L.at().ns.mounts() == {"pkg": {"root": "pkg", "repo": "my-proj"},
                                  "other": {"root": "o", "repo": "elsewhere"}}


def test_t_ns_mount_without_repo_needs_a_project_in_a_checkout(L, tmp_path, monkeypatch):
    from dvc_dat import core

    (tmp_path / "bare").mkdir()
    monkeypatch.setattr(core, "_default_manager", DatManager(dat_folders=[str(tmp_path / "bare")]))
    with pytest.raises(ValueError, match=r"repo=.*\.datconfig\.yaml"):
        with L.transaction(by="t") as t:
            t.ns.mount("pkg", root="pkg")
    root = _project(tmp_path, "loose", git=False)
    monkeypatch.setattr(core, "_default_manager", DatManager.load_dat_config(root))
    with pytest.raises(ValueError, match="no git checkout"):
        with L.transaction(by="t") as t:
            t.ns.mount("pkg", root="pkg")
    assert L.at().ns.mounts() == {}
