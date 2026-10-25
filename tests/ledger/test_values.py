"""Contracts of values: seal, preds, aliases, Ref, the seal's refusals, typed and many preds."""

import pytest

from dvc_dat.ledger import AliasLoop, Exists, Multiple, Ref, Undeclared, Value, ledger_class
from ledger_kinds import Cut, Plain, Video


def seal(L, v, **kw):
    with L.transaction(by="t") as t:
        s = v.seal(t, **kw)
    return s


@pytest.fixture
def decl(L):
    with L.transaction(by="t") as t:
        t.add("db/pred/team", "db/cardinality", "many")
        t.add("db/pred/video", "db/type", "ledger_kinds.Video")
        t.add("db/pred/span", "db/type", "json")
    return L


def test_seal_returns_a_content_subject_and_loads_back(L):
    v = Plain(b"abc")
    s = seal(L, v)
    assert len(s) == 64 and v.sealed and v.subject == s and v.rev.id == 1
    r = Ref(L.at(), s)
    assert r.type is Plain and r.hash == v.hash and repr(r) == f"<Ref #{s[:8]}>" and str(r) == "#" + s[:8]
    back = L.at().load(s)
    assert back.data == b"abc" and back.subject == s and back is L.at().load(s)
    assert L.at()[s, "db/kind"] == "ledger_kinds.Plain" and L.at()[s, "db/provenance"] == "seal"


def test_idempotent_same_bytes_deps_preds(L):
    assert seal(L, Plain(b"x")) == seal(L, Plain(b"x"))


def test_preds_frozen_by_the_seal_and_in_the_hash(L, decl):
    a = Video(b"f")
    a.preds.update(game="G1", camera="wide", span=[0, 9])
    sa = seal(L, a)
    with pytest.raises(TypeError):
        a.preds["camera"] = "tele"
    b = Video(b"f")
    b.preds.update(game="G2")
    assert seal(L, b) != sa
    assert a.preds == {"game": "G1", "camera": "wide", "span": [0, 9]}
    assert L.at()[sa, "db/preds"] == ["game", "camera", "span"]


def test_undeclared_and_refused_seal_leaves_value_untouched(L):
    v = Video(b"f")
    v.preds.update(game="G1", team="x")
    with pytest.raises(Undeclared):
        seal(L, v)
    assert not v.sealed and isinstance(v.preds, dict)
    del v.preds["team"]
    v.preds["camera"] = ["a", "b"]           # a list under an untyped one pred
    with pytest.raises(TypeError):
        seal(L, v)
    assert not v.sealed and L.at().id == 0


def test_numbers_coerced_and_eval_provenance_refused(L):
    v = Video(b"f")
    v.preds.update(game=5)
    with pytest.raises(ValueError):
        seal(L, v, provenance="eval:unsandboxed")
    seal(L, v, provenance="import:x")
    assert L.at()[v.subject, "game"] == "5" and L.at()[v.subject, "db/provenance"] == "import:x"


def test_exists_on_frozen_preds_absent_ones_too_annotation_allowed(L):
    v = Video(b"f")
    v.preds.update(game="G1")
    s = seal(L, v)
    for p, o in (("game", "G2"), ("camera", "tele"), ("db/kind", "x")):
        with pytest.raises(Exists):
            with L.transaction(by="t") as t:
                t.add(s, p, o)
    with pytest.raises(Exists):
        with L.transaction(by="t") as t:
            t.remove(s, "game", "G1")
    with L.transaction(by="t") as t:
        t.add(s, "note", "fine")
    assert Ref(L.at(), s).preds == {"game": "G1", "note": "fine"}


def test_add_refuses_a_value(L):
    with pytest.raises(TypeError, match="seal"):
        with L.transaction(by="t") as t:
            t.add("x", "y", Plain(b"1"))


def test_alias_chain_repr_and_aliases(L):
    s = seal(L, Plain(b"1"), name="video/G1")
    with L.transaction(by="t") as t:
        t.add("raw/G1/long-name", "db/alias", s)
    rev = L.at()
    r = Ref(rev, "raw/G1/long-name")
    assert r.subject == s and r.name == "raw/G1/long-name" and str(r) == "raw/G1/long-name"   # its name: the latest (Q36)
    assert sorted(r.aliases) == ["raw/G1/long-name", "video/G1"]
    assert rev["video/G1"] == {"db/alias": s}           # literal
    assert rev.load("video/G1").subject == s


def test_alias_target_must_hold_a_value_at_commit(L):
    with pytest.raises(TypeError):
        with L.transaction(by="t") as t:
            t.add("name", "db/alias", "nothing-here")


def test_alias_hop_limit(L):
    s = seal(L, Plain(b"1"))
    with L.transaction(by="t") as t:
        t.add("h/1", "db/alias", s)
        for i in range(2, 10):
            t.add(f"h/{i}", "db/alias", f"h/{i - 1}")
    assert Ref(L.at(), "h/8").subject == s
    with pytest.raises(AliasLoop):
        Ref(L.at(), "h/9")


def test_typed_and_many_preds(L, decl):
    raw = Video(b"frames")
    raw.preds.update(game="G1", span=[0, 3])
    seal(L, raw)
    c = Cut(b"clip")
    c.preds.update(game="G1", team=["G5", "G4", "G5"], video=raw)
    s = seal(L, c, deps=[raw])
    assert isinstance(c.preds["video"], Ref) and c.preds["video"].subject == raw.subject
    assert sorted(c.preds["team"]) == ["G4", "G5"]
    rev = L.at()
    assert [x.subject for x in rev.refs(team="G4")] == [s]
    assert [v.subject for v in rev.values(video=raw)] == [s]
    loaded = rev.load(s)
    assert isinstance(loaded.preds["video"], Ref) and loaded.preds["video"].load().frames == b"frames"
    bad = Cut(b"other")
    bad.preds["video"] = Plain(b"zz")
    with pytest.raises(ValueError):            # unsealed
        seal(L, bad)
    seal(L, Plain(b"zz"))
    p = L.at().load(Ref(L.at(), L.at().refs(kind=Plain)[0].subject).subject)
    bad.preds["video"] = p
    with pytest.raises(TypeError):             # not a Video
        seal(L, bad)


def test_value_values_refs_select_kind(L):
    for g in ("G1", "G2"):
        v = Video(g.encode())
        v.preds.update(game=g, camera="wide")
        seal(L, v, name=f"video/{g}")
    rev = L.at()
    assert [repr(v) for v in rev.values(kind=Video)] == ["<Video video/G1>", "<Video video/G2>"]
    assert str(rev.value(game="G1")) == "video/G1"
    with pytest.raises(Multiple):
        rev.value(kind=Video)
    with pytest.raises(KeyError):
        rev.value(game="G9")
    assert rev.select(("game",), kind="ledger_kinds.Video") == [("G1",), ("G2",)]
    refs = rev.refs(camera="wide")
    assert max(refs, key=lambda r: r.sealed_at.id).subject == refs[1].subject


def test_kind_follows_db_moved(L):
    v = Plain(b"1")
    seal(L, v)
    with L.transaction(by="t") as t:
        t.add("db/kind/ledger_kinds.Plain", "db/moved", "ledger_kinds.Cut")
    rev = L.at()
    assert len(rev.refs(kind=Cut)) == 1 and Ref(rev, v.subject).type is Cut


def test_deps_dependencies_and_alias_binding(L):
    raw = Plain(b"raw")
    seal(L, raw, name="data/raw")
    loaded = L.at().load("data/raw")
    out = Value.Blob({"a": 1})
    seal(L, out, deps=[loaded])
    t = out.dependencies
    key = f"ref:ledger_kinds.Plain:{raw.hash}"
    assert t[key] == key and t["data/raw db/alias"] == key
    assert t["code/testrepo"] == "abc1234" and "uv.lock" not in t


def test_a_row_may_point_at_a_value(L):
    s = seal(L, Plain(b"1"), name="p")
    with L.transaction(by="t") as t:
        t.add("review", "pick", Ref(t.base, s))
    got = L.at()["review", "pick"]
    assert isinstance(got, Ref) and got.subject == s and repr(got) == "<Ref p>"


def test_ledger_class_rejects_non_values():
    with pytest.raises(TypeError):
        ledger_class(preds=("a",))(dict)
    assert issubclass(Value, object)


def test_seal_on_a_ledger_commits_its_own_transaction(L):
    top = L.at().id
    s = Plain(b"alone").seal(L, name="note/alone", provenance="human:dan")
    now = L.at()
    assert now.id == top + 1
    assert Ref(now, "note/alone").subject == s
    assert now[now.tx, "db/by"] == "human:dan"


def test_seal_on_a_transaction_joins_it(L):
    top = L.at().id
    with L.transaction(by="t") as t:
        a = Plain(b"one").seal(t)
        b = Plain(b"two").seal(t)
    assert L.at().id == top + 1 and a != b


def test_seal_refuses_by_on_an_open_transaction_and_a_bad_target(L):
    with pytest.raises(TypeError, match="open already"):
        with L.transaction(by="t") as t:
            Plain(b"x").seal(t, by="someone")
    with pytest.raises(TypeError, match="Transaction or a Ledger"):
        Plain(b"x").seal("ledger")
