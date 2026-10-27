"""What a value, a ref and a fn print as (DAT 1036, option A): ``repr`` is ``<Type label>``, ``str`` the
bare label; the label is the name at the head, else ``#`` + the hash's first 8. A fn's label is its name
``@`` its code's version (DAT 1037)."""

import pytest

from dvc_dat.ledger import Ref, Value
from dvc_dat.ledger.codec import ref_text
from ledger_kinds import Plain
from test_memo import world  # noqa: F401  (the fixture)


@pytest.fixture(autouse=True)
def kept_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DAT_KEPT", str(tmp_path / "kept"))


def save(L, v, **kw):
    with L.transaction(by="t") as t:
        return v.seal(t, **kw)


def test_a_saved_named_value_prints_its_name(L):
    v = Plain(b"clip")
    save(L, v, name="clip/G1")
    assert repr(v) == "<Plain clip/G1>" and str(v) == "clip/G1" and f"{v}" == "clip/G1"


def test_a_saved_unnamed_value_prints_a_short_hash(L):
    v = Plain(b"clip")
    s = save(L, v)
    assert repr(v) == f"<Plain #{s[:8]}>" and str(v) == "#" + s[:8]


def test_a_locally_sealed_value_says_sealed(L):
    v = Plain(b"clip")
    h = v.seal()
    assert repr(v) == f"<Plain sealed #{h[:8]}>" and str(v) == "#" + h[:8]


def test_a_draft_has_no_label():
    v = Plain(b"clip")
    assert repr(v) == "<Plain draft>" and str(v) == "<Plain draft>"


def test_a_draft_blob_prints_like_any_draft(L):
    b = Value.Blob(3)
    assert repr(b) == "<Blob draft>" and str(b) == "<Blob draft>"
    s = save(L, b)
    assert repr(b) == f"<Blob #{s[:8]}>" and str(b) == "#" + s[:8]


def test_a_ref_prints_its_name_or_a_short_hash(L):
    s = save(L, Plain(b"clip"), name="clip/G1")
    named = Ref(L.at(), "clip/G1")
    assert repr(named) == "<Ref clip/G1>" and str(named) == "clip/G1" and named.name == "clip/G1"
    t = save(L, Plain(b"other"))
    bare = Ref(L.at(), t)
    assert repr(bare) == f"<Ref #{t[:8]}>" and str(bare) == "#" + t[:8]
    assert s != t


def test_an_unresolved_ref_prints_its_short_hash(L):
    h = "ab" * 32
    r = Ref._from_text(L.at(), ref_text("ledger_kinds.Plain", h))
    assert r.subject is None
    assert repr(r) == "<Ref #abababab>" and str(r) == "#abababab"


def test_a_fn_prints_its_name_and_version(world):  # noqa: F811
    f = world.at().ns.load("ledger_kinds.cut")
    version = f.code.version            # the pinned testrepo checkout's commit: abc1234
    assert version == "abc1234"
    assert repr(f) == "<Fn ledger_kinds.cut@abc1234>" and str(f) == "ledger_kinds.cut@abc1234"
    assert repr(f.code) == "<Code ledger_kinds@abc1234>" and str(f.code) == "ledger_kinds@abc1234"
