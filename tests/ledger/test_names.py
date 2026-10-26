"""Names (F447 Q36, A70) and the control options (Q41): path=, Value(name=), kwargs=."""

import os

import pytest

from dvc_dat.ledger import Dat, Ref, Value
from ledger_kinds import CALLS
from test_memo import world  # noqa: F401  (the fixture)


def seal(L, v, **kw):
    with L.transaction(by="t") as t:
        s = v.seal(t, **kw)
    return s


def test_a_value_has_one_name_and_a_name_one_value(L):
    a = Value.Blob("a", name="x/a")
    s = seal(L, a)
    assert a.name == "x/a" and repr(a) == "<Blob x/a>" and str(a) == "x/a" and Ref(L.at(), "x/a").subject == s
    a.name = "x/b"                                           # renamed: one name at a time
    assert a.name == "x/b" and Ref(L.at(), "x/a").hash is None and Ref(L.at(), "x/b").subject == s
    b = Value.Blob("b")
    seal(L, b, name="x/b")                                  # the name moves to another value
    assert b.name == "x/b" and a.name is None and repr(a) == f"<Blob #{s[:8]}>" and str(a) == "#" + s[:8]
    assert L.at().load(s).obj == "a"                         # still reachable by hash
    with pytest.raises(ValueError):
        Value.Blob("c", name="/abs/name")
    with pytest.raises(ValueError):
        Value.Blob("c", name="a/../b")


def test_the_name_is_not_in_the_hash(L):
    s1 = seal(L, Value.Blob(1, name="n/one"))
    s2 = seal(L, Value.Blob(1, name="n/two"))
    assert s1 == s2 and L.at().load(s1).name == "n/two"     # the same value, renamed


def test_path_names_a_dat_and_its_folder_is_a_view(world):
    rev = world.at()
    d = rev.run("ledger_kinds.folder", game="G1", path="games/one")
    data = world._store.art.root / "dats"
    assert d.name == "games/one" and d.path == data / "games/one" and (d.path / "a.txt").read_text() == "G1"
    assert "path" not in world.at()[d.subject, "db/keys"]   # never hashed
    n = CALLS["folder"]
    e = world.at().run("ledger_kinds.folder", game="G1", path="games/uno")   # a hit, under a new name
    assert CALLS["folder"] == n and e.subject == d.subject
    assert e.name == "games/uno" and Ref(world.at(), "games/one").hash is None
    assert (data / "games/uno/a.txt").read_text() == "G1"
    assert os.path.samefile(data / "games/uno/a.txt", world._store.art.path(Dat(data / "games/uno")._manifest()["a.txt"]))


def test_an_absolute_path_makes_the_folder_there_and_names_nothing(world, tmp_path):
    d = world.at().run("ledger_kinds.folder", game="G2", path=str(tmp_path / "out"))
    assert d.path == tmp_path / "out" and (d.path / "a.txt").read_text() == "G2" and d.name is None


def test_the_path_template_then_the_anonymous_one(world):
    p = world.at().run("ledger_kinds.placed", game="G1")
    assert p.name == "games/G1" and (p.path / "g.txt").read_text() == "G1"
    a = world.at().run("ledger_kinds.folder", game="G1")
    b = world.at().run("ledger_kinds.folder", game="G2")
    assert (a.name, b.name) == ("anonymous/Dat", "anonymous/Dat_2")
    n = CALLS["folder"]
    assert world.at().run("ledger_kinds.folder", game="G1").name == "anonymous/Dat" and CALLS["folder"] == n


def test_a_draft_keeps_the_name_on_the_object(world):
    v = world.at().run("ledger_kinds.cut", game="G1", seal=False, path="cuts/G1")
    assert not v.sealed and v.name == "cuts/G1"
    seal(world, v)
    assert Ref(world.at(), "cuts/G1").subject == v.subject
    n = CALLS["cut"]
    assert world.at().run("ledger_kinds.cut", game="G1").subject == v.subject and CALLS["cut"] == n


def test_kwargs_carries_keys_named_like_control_options(world):
    v = world.at().run("ledger_kinds.controls", kwargs={"seal": 3, "clean": "x", "kwargs": {"k": 1}})
    assert v.obj == {"seal": 3, "clean": "x", "kwargs": {"k": 1}, "n": 0}
    assert world.at()[v.subject, "db/keys"] == {"seal": 3, "clean": "x", "kwargs": {"k": 1}, "n": 0}
    w = world.at().run("ledger_kinds.controls", seal="get", kwargs={"seal": 3, "clean": "x", "kwargs": {"k": 1}})
    assert w.subject == v.subject
    with pytest.raises(TypeError, match="inline or in kwargs="):
        world.at().run("ledger_kinds.controls", n=1, kwargs={"seal": 3, "clean": "x", "kwargs": {}})
    with pytest.raises(TypeError, match="control option"):
        world.at().run("ledger_kinds.folder", kwargs={"game": "G1", "path": "x"})
    f = world.at().resolve("ledger_kinds.cut")
    assert f(kwargs={"game": "G1"}).subject == f(game="G1").subject
