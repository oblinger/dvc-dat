"""v.seal() with no target: identity fixed now, saved later by v.seal(t) or v.seal(L) (T543 Q4 (D))."""

import pytest

from dvc_dat.ledger import Dat, Ref, SealBroken
from dvc_dat.ledger.kept import Kept, age
from ledger_kinds import Cut, Plain, Video


@pytest.fixture(autouse=True)
def kept_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DAT_KEPT", str(tmp_path / "kept"))
    return tmp_path / "kept"


def test_seal_fixes_identity_and_writes_nothing(L):
    top = L.at().id
    v = Plain(b"clip")
    h = v.seal()
    assert v.sealed and v.subject is None and v.sealed_at and h == v.hash
    assert L.at().id == top
    with pytest.raises(TypeError, match="sealed"):
        v.preds["x"] = "y"
    with pytest.raises(ValueError, match="sealed already"):
        v.seal()


def test_a_save_carries_the_environment_of_the_seal(L, envbox):
    v = Plain(b"clip")
    v.seal(provenance="human:dan")
    envbox.code(commit="later99")
    s = v.seal(L, alias="clip/1")
    held = Ref(L.at(), "clip/1")
    assert held.subject == s == v.subject and v.rev is not None
    assert v.trace["code/testrepo"] == "+abc1234"
    assert L.at()[s, "db/provenance"] == "human:dan"
    assert L.at()[s, "db/sealed-at"] == v.sealed_at
    assert L.at()[L.at().tx, "db/by"] == "human:dan"


def test_changed_bytes_break_the_seal_unless_kept(L):
    v = Plain(b"before")
    v.seal()
    v.data = b"after"
    with pytest.raises(SealBroken, match="changed"):
        v.seal(L)
    k = Plain(b"before")
    k.seal(keep=True)
    k.data = b"after"
    s = k.seal(L)
    assert L.at().load(s).data == b"before"
    assert [e["kept"] for e in Kept().listing()] == [False]   # saved: k's record goes at commit; v's stays


def test_a_kept_dat_saves_the_folder_as_it_was_sealed(L, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("one")
    d = Dat(src)
    d.seal(keep=True)
    (src / "a.txt").write_text("two")
    d.seal(L)
    assert (d.path / "a.txt").read_text() == "one"


def test_the_seal_fixes_deps_and_provenance(L):
    v = Plain(b"x")
    v.seal()
    with pytest.raises(TypeError, match="fixed by v.seal"):
        v.seal(L, provenance="other")
    with pytest.raises(TypeError, match="keep="):
        Plain(b"y").seal(L, keep=True)
    with pytest.raises(TypeError, match="alias="):
        Plain(b"z").seal(alias="n/1")


def test_an_abandoned_save_leaves_the_value_sealed(L):
    v = Plain(b"x")
    v.seal()
    with pytest.raises(RuntimeError):
        with L.transaction(by="t") as t:
            v.seal(t)
            raise RuntimeError("body")
    assert v.sealed and v.subject is None
    assert v.seal(L)


def test_a_dep_must_be_saved_first(L):
    raw = Plain(b"raw")
    raw.seal()
    cut = Plain(b"cut")
    cut.seal(deps=[raw])
    with pytest.raises(ValueError, match="saved nowhere"):
        cut.seal(L)
    with L.transaction(by="t") as t:
        r = raw.seal(t)
        c = cut.seal(t)
    assert L.at()[c, f"db/trace/ref:{Plain.__module__}.Plain:{raw.hash}"]
    assert r != c


def test_purge_drops_what_was_kept_and_never_saved(L):
    Plain(b"old").seal(keep=True)
    rows = Kept().listing()
    assert len(rows) == 1 and rows[0]["bytes"] == 3
    assert Kept().purge(age("1d")) == []
    assert len(Kept().purge(age("0m"))) == 1 and Kept().listing() == []


def test_a_kept_value_keeps_the_hash_of_its_stored_bytes(L):
    with L.transaction(by="t") as t:
        t.add("db/pred/video", "db/type", "ledger_kinds.Video")
    a = Video(b"a")
    a.seal(keep=True)
    a.frames = b"mutated"
    a.seal(L)
    assert a.hash == Ref(L.at(), a.subject).hash
    b = Cut(b"b")
    b.preds["video"] = a
    b.seal(L)
    assert L.at()[b.subject, "video"].load().frames == b"a"


def test_two_equal_kept_values_each_save(L):
    a, b = Plain(b"x"), Plain(b"x")
    a.seal(keep=True)
    b.seal(keep=True, provenance="human:b")
    assert len(Kept().listing()) == 2
    a.seal(L)
    b.seal(L)
    assert Kept().listing() == []


def test_a_bad_entry_file_neither_breaks_a_save_nor_the_listing(L, kept_root):
    v = Plain(b"x")
    v.seal(keep=True)
    (kept_root / "sealed" / "junk.json").write_text("{trunc")
    assert v.seal(L)
    assert [e["kind"] for e in Kept().listing()] == ["<unreadable>"]
    Kept().purge(age("0m"))
    assert Kept().listing() == []


def test_purged_bytes_fall_back_to_the_source_only_when_unchanged(L):
    v = Plain(b"x")
    v.seal(keep=True)
    w = Plain(b"y")
    w.seal(keep=True)
    w.data = b"changed"
    Kept().purge(age("0m"))
    assert v.seal(L)
    with pytest.raises(SealBroken, match="purged"):
        w.seal(L)


def test_sealed_at_is_frozen(L):
    from dvc_dat.ledger import Exists

    v = Plain(b"x")
    v.seal()
    s = v.seal(L)
    with pytest.raises(Exists):
        with L.transaction(by="t") as t:
            t.remove(s, "db/sealed-at", v.sealed_at)


def test_eval_refuses_a_result_sealed_early(coded):
    with pytest.raises(TypeError, match="eval seals its own"):
        coded.at().eval("ledger_kinds.sealed_early", game="G1")
