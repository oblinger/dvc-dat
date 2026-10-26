"""Contracts of functions and run unsandboxed: ledger_fn, load_fn, the memo, the dependencies, NotEvaluated."""

import re

import pytest

import ledger_kinds
from dvc_dat.ledger import Dat, NotClean, NotEvaluated, Ref, Value, ledger_fn
from ledger_kinds import CALLS, Cut, Video


@pytest.fixture
def world(coded):
    L = coded
    with L.transaction(by="t", lock=10) as t:
        t.add("db/pred/video", "db/type", "ledger_kinds.Video")
        t["game/G1"] = {"home": "G4", "away": "G5"}
        t["game/G2"] = {"home": "G1", "away": "G3"}
    for g in ("G1", "G2"):
        v = Video(f"{g} frames".encode())
        v.preds.update(game=g)
        with L.transaction(by="t") as t:
            v.seal(t, name=f"video/{g}")
    CALLS.clear()
    return L


def test_ledger_fn_needs_an_annotation_and_stays_callable(world):
    with pytest.raises(TypeError):
        @ledger_fn
        def f(rev, *, a):
            return a
    v = ledger_kinds.cut(world.at(), game="G1")
    assert isinstance(v, Cut) and not v.sealed and v.dependencies == {} and world.at().id == 4


def f_code(world):
    return world.at().load_fn("ledger_kinds.cut").code.subject


def test_load_fn_fields(world):
    f = world.at().load_fn("ledger_kinds.cut")
    assert f.code.sandboxed is False and f.mount is None and str(f.signature) == "(*, game: str, version: str = '1.0.0')"
    assert f.name == "ledger_kinds.cut" and re.fullmatch(r"db/code/[0-9a-f]{16}", f.code.subject)
    assert not hasattr(f, "subject") and not hasattr(f, "sha")
    with pytest.raises(TypeError):
        world.at().load_fn("ledger_kinds.Video")


def test_eval_seals_once_and_hits(world):
    rev = world.at()
    a = rev.run("ledger_kinds.cut", game="G1")
    assert a.sealed and a.rev.id == rev.id + 1 and CALLS["cut"] == 1
    top = world.at().id
    b = world.at().run("ledger_kinds.cut", game="G1", version="1.0.0")      # defaults bound in
    assert b.subject == a.subject and CALLS["cut"] == 1 and world.at().id == top and b.rev.id == a.rev.id
    r = world.at()
    assert r[a.subject, "db/keys"] == {"game": "G1", "version": "1.0.0"}
    assert r[a.subject, "db/fn"] == "ledger_kinds.cut" and r[a.subject, "db/provenance"] == "eval:unsandboxed"
    assert a.dependencies["fn"] == "ledger_kinds.cut" and a.dependencies["code"] == f_code(world)
    assert r[a.subject, "db/returns"] == "Cut" and r[a.dependencies["code"], "db/mounts"] == "none" and "ledger_kinds.py" in r[a.dependencies["code"], "db/modules"]
    assert [x.subject for x in r.refs(fn="ledger_kinds.cut")] == [a.subject]


def test_dependency_items(world):
    a = world.at().run("ledger_kinds.cut", game="G1")
    t = dict(a.dependencies)
    assert t["game/G1 home"] == "G4" and t["code/testrepo"] == "abc1234"
    q = [k for k in t if k.startswith("q:")]
    assert q == ['q:{"game":"G1","kind":"ledger_kinds.Video"}']
    vid = world.at().load("video/G1")
    assert t[f"ref:ledger_kinds.Video:{vid.hash}"].startswith("ref:")
    assert set(t) >= {"fn", "platform"} and "uv.lock" not in t




def test_a_read_change_misses_and_diff_names_it(world):
    a = world.at().run("ledger_kinds.cut", game="G1")
    with world.transaction(by="t") as t:
        t["game/G1", "away"] = "G9"                 # not read
    assert a.matches(world.at())
    with world.transaction(by="t") as t:
        t["game/G1", "home"] = "G6"
    assert not a.matches(world.at())
    b = world.at().run("ledger_kinds.cut", game="G1")
    assert b.subject != a.subject and a.diff(b) == {"game/G1 home": ("G4", "G6")}


def test_code_commit_pins_the_version_and_the_env_commit_decides(world, envbox):
    a = world.at().run("ledger_kinds.cut", game="G1")
    assert a.dependencies["code/testrepo"] == "abc1234"
    with world.transaction(by="t") as t:
        t.add("db/repo/testrepo/ledger_kinds", "version", "1.0.1")   # version moves, commit does not
    assert a.matches(world.at())
    envbox.code(commit="def5678")                          # a later commit: the row no longer gates (Q7 (C))
    assert not a.matches(world.at())                       # a hit holds at the commit it ran at
    b = world.at().run("ledger_kinds.cut", game="G2")
    assert b.dependencies["code/testrepo"] == "def5678"           # the environment's commit; the version is the row's
    assert world.at().run("ledger_kinds.cut", game="G2", seal="get").subject == b.subject
    envbox.code(commit="abc1234")
    assert world.at().run("ledger_kinds.cut", game="G1", seal="get").subject == a.subject
    envbox.code(dirty=True)
    with pytest.raises(NotEvaluated):
        world.at().run("ledger_kinds.cut", game="G3")


def test_clean_requires_a_clean_checkout_at_the_revs_commit(world, envbox):
    a = world.at().run("ledger_kinds.cut", game="G1", clean=True)      # clean, at the row's commit
    assert world.at().run("ledger_kinds.cut", game="G1", clean=True).subject == a.subject
    envbox.code(commit="def5678")
    with pytest.raises(NotClean, match="binds db/repo/testrepo to abc1234"):
        world.at().run("ledger_kinds.cut", game="G1", clean=True)        # refused before the lookup
    envbox.code(dirty=True)
    with pytest.raises(NotClean, match="uncommitted changes") as e:
        world.at().run("ledger_kinds.cut", game="G1", clean=True, seal=False)
    assert isinstance(e.value, NotEvaluated)                               # catchable as either
    with pytest.raises(TypeError):
        world.at().run("ledger_kinds.cut", game="G1", clean="yes")


def test_clean_needs_a_code_row(L):
    with L.transaction(by="t", lock=10) as t:
        t["game/G1"] = {"home": "G4"}
        t.add("db/pred/video", "db/type", "ledger_kinds.Video")
    v = Video(b"x")
    v.preds.update(game="G1")
    with L.transaction(by="t") as t:
        v.seal(t)
    with pytest.raises(NotClean, match="names no db/repo/testrepo commit"):
        L.at().run("ledger_kinds.cut", game="G1", clean=True)


def test_no_code_row_runs_with_the_env_commit(L):
    with L.transaction(by="t", lock=10) as t:
        t["game/G1"] = {"home": "G4"}
        t.add("db/pred/video", "db/type", "ledger_kinds.Video")
    v = Video(b"x")
    v.preds.update(game="G1")
    with L.transaction(by="t") as t:
        v.seal(t)
    a = L.at().run("ledger_kinds.cut", game="G1")
    assert a.dependencies["code/testrepo"] == "abc1234"


def test_keys_by_bytes_and_bare_return_pickled(world):
    a = world.at().run("ledger_kinds.cut", game="G1")
    th = world.at().run("ledger_kinds.thumb", clip=Ref(world.at(), a.subject))
    assert isinstance(th, Value.Blob) and th.obj == {"n": len(a.clip)}
    assert world.at()[th.subject, "db/keys"] == {"clip": f"ref:ledger_kinds.Cut:{a.hash}"}
    assert world.at()[th.subject, "db/returns"] == "dict"
    assert th.dependencies["fn"] == "ledger_kinds.thumb" and th.dependencies["code"] == a.dependencies["code"]
    with pytest.raises(TypeError):
        world.at().run("ledger_kinds.thumb", clip={"x": Ref(world.at(), a.subject)})


def test_wrong_return_type_refused(world):
    with pytest.raises(TypeError):
        world.at().run("ledger_kinds.wrong", game="G1")


def test_alias_binding_and_nested_eval(world):
    a = world.at().run("ledger_kinds.cut", game="G1")
    with world.transaction(by="t") as t:
        t.add("game/G1", "db/alias", a.subject)
    p = world.at().run("ledger_kinds.poster", game="G1")
    assert p.dependencies["game/G1 db/alias"] == f"ref:ledger_kinds.Cut:{a.hash}"
    ch = world.at().run("ledger_kinds.chain", game="G1")
    item = 'eval:ledger_kinds.cut{"game":"G1","version":"1.0.0"}'
    assert ch.dependencies[item] == f"ref:ledger_kinds.Cut:{a.hash}"
    assert ch.matches(world.at())
    with world.transaction(by="t") as t:
        t["game/G1", "home"] = "G7"
    assert not ch.matches(world.at())                 # the nested lookup misses; nothing runs
    n = CALLS["cut"]
    assert not ch.matches(world.at()) and CALLS["cut"] == n


def test_work_folder_dat(world):
    d = world.at().run("ledger_kinds.folder", game="G1")
    assert isinstance(d, Dat) and (d.path / "a.txt").read_text() == "G1"
    assert "work" not in world.at()[d.subject, "db/keys"]
    with pytest.raises(TypeError):
        world.at().run("ledger_kinds.folder", game="G1", work="x")


def test_racing_entries_both_kept_latest_wins(world):
    import threading
    out = []

    def go():
        out.append(world.at().run("ledger_kinds.cut", game="G2"))
    ts = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len({v.subject for v in out}) == 1           # deterministic: one subject
