"""Leg 7: the review's holes, one test each."""

import pytest

import dvc_dat.ledger as ledger
from dvc_dat.ledger import Ref
from ledger_kinds import CALLS, Plain, Video


def seal(L, v, **kw):
    with L.transaction(by="t") as t:
        s = v.seal(t, **kw)
    return s


def test_1_a_ref_made_in_a_body_keeps_the_recorder(coded):
    L = coded
    a = Plain(b"aaa")
    seal(L, a, name="model/x")
    v = L.at().run("ledger_kinds.via_ref", name="model/x")
    assert v.trace["model/x db/alias"] == f"ref:ledger_kinds.Plain:{a.hash}"
    assert v.trace[f"ref:ledger_kinds.Plain:{a.hash}"]
    b = Plain(b"bbbbb")
    seal(L, b)
    with L.transaction(by="t") as t:
        t.add("model/x", "db/alias", b.subject)
    assert L.at().run("ledger_kinds.via_ref", name="model/x", memo="get") is None   # no stale hit
    assert L.at().run("ledger_kinds.via_ref", name="model/x").obj == {"n": 10}


def test_1_ref_preds_and_ref_rev_reads_are_traced(coded):
    L = coded
    v = Video(b"v")
    v.preds["game"] = "G1"
    seal(L, v, name="vid")
    p = L.at().run("ledger_kinds.via_ref_preds", name="vid")
    assert any(k.startswith('q:{"__call__":"preds"') for k in p.trace)
    with L.transaction(by="t") as t:
        t.add(v.subject, "note", "hi")
    assert not p.matches(L.at())                       # an annotation moved the preds read
    r = L.at().run("ledger_kinds.via_refs_rev", game="G1")
    assert r.obj == {"note": "hi"} and f"{v.subject} note" in r.trace


def test_2_an_alias_row_on_a_sealed_subject_is_refused(L):
    a, b = seal(L, Plain(b"a")), seal(L, Plain(b"b"))
    with pytest.raises(TypeError, match="own db/value"):
        with L.transaction(by="t") as t:
            t.add(a, "db/alias", b)
    assert L.at().load(a).data == b"a"


def test_3_preds_freeze_at_seal_and_unfreeze_on_refusal(L):
    v = Video(b"v")
    v.preds["game"] = "G1"
    with L.transaction(by="t") as t:
        s = v.seal(t)
        assert v.sealed and v.subject == s and v.rev is None
        with pytest.raises(TypeError):
            v.preds["game"] = "G2"
    assert v.rev.id == 1 and L.at()[s, "game"] == "G1"
    w = Video(b"w")
    w.preds["game"] = "G1"
    with pytest.raises(TypeError):
        with L.transaction(by="t") as t:
            w.seal(t)
            t.add("x", "db/alias", "nothing")              # refused at commit
    assert not w.sealed and w.subject is None and isinstance(w.preds, dict)
    w.preds["game"] = "G3"                                # mutable again


def test_4_a_refused_commit_leaves_no_bytes(L):
    art = L._store.art
    v = Plain(b"never stored")
    with pytest.raises(TypeError):
        with L.transaction(by="t") as t:
            v.seal(t)
            t.add("x", "db/alias", "nothing")
    assert not art.path(Plain(b"never stored").hash).exists()
    with pytest.raises(RuntimeError):
        with L.transaction(by="t") as t:
            Plain(b"body raised").seal(t)
            raise RuntimeError
    assert not art.path(Plain(b"body raised").hash).exists()


def test_5_db_format_and_db_index(L):
    with L.transaction(by="t") as t:
        t.add("g", "home", "G4")
        t.add("db/pred/home", "db/index", "true")
        t.add("db/pred/home", "db/doc", "the home team")
    rev = L.at()
    assert rev["db", "db/format"] == "dvc-dat-ledger/1"
    names = L._store.index_names()
    assert any(n.startswith("pred_") for n in names)
    assert rev["db/pred/home"] == {"db/index": "true", "db/doc": "the home team"}
    assert [r.subject for r in rev.refs(home="G4")] == ["g"]


def test_6_verbs_outside_with_raise(L):
    t = L.transaction(by="t")
    with pytest.raises(RuntimeError):
        t.add("s", "p", "o")
    with pytest.raises(RuntimeError):
        t["s", "p"] = "o"
    with L.transaction(by="t") as t2:
        t2.add("s", "p", "o")
    with pytest.raises(RuntimeError):
        t2.add("s", "p", "o2")


def test_7_a_recorded_miss_holds_while_still_missing(coded):
    L = coded
    m = L.at().run("ledger_kinds.maybe", game="G1")
    assert m.trace['eval:ledger_kinds.cut{"game":"G1","version":"1.0.0"}'] == "<none>"
    n = CALLS.get("maybe", 0)
    assert L.at().run("ledger_kinds.maybe", game="G1").subject == m.subject and CALLS.get("maybe", 0) == n


def test_8_base_fn_hashes_the_static_closure(coded):
    f = coded.at().load_fn("ledger_kinds.via_ref")
    assert set(f._modules) == {"ledger_kinds.py", "ledger_helper.py"}
    v = Plain(b"x")
    seal(coded, v, name="n")
    e = coded.at().run("ledger_kinds.via_ref", name="n")
    assert sorted(coded.at()[e.trace["fn"], "db/modules"]) == ["ledger_helper.py", "ledger_kinds.py"]


def test_9_salt_item_is_named_salt():
    """Covered with a real mount in test_sandbox.test_salt_item (needs a worker)."""
    from test_sandbox import test_salt_item  # noqa: F401


def test_10_refs_equal_by_subject_not_bytes(L):
    a = Video(b"same")
    a.preds["game"] = "G1"
    b = Video(b"same")
    b.preds["game"] = "G2"
    sa, sb = seal(L, a), seal(L, b)
    ra, rb = Ref(L.at(), sa), Ref(L.at(), sb)
    assert ra != rb and ra.hash == rb.hash and ra == Ref(L.at(), sa) and len({ra, rb}) == 2


def test_11_the_test_seam_is_not_in_all():
    assert not {"set_env_provider", "Env", "Code"} & set(ledger.__all__)
    from dvc_dat.ledger import Code, Env, set_env_provider  # noqa: F401  importable by name
