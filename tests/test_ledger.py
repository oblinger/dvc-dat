"""dvc_dat.ledger: the example, one test per commitment, one per error, on SQLite."""

from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from dvc_dat import Dat
from dvc_dat.ledger import BLOB_BYTES, Artifact, Batch, Event, Ledger, LedgerError, Node, Ref, SqliteLedger
from dvc_dat.ledger import core as ledger_core
from dvc_dat.ledger.shelf import LocalShelf
from dvc_dat.ledger.types import ART_TYPES, ckpt, file, json, video


@pytest.fixture(autouse=True)
def _no_default(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    Ledger.default = None
    yield
    Ledger.default = None


@pytest.fixture
def L(tmp_path: Path) -> Iterator[Ledger]:
    led = SqliteLedger(tmp_path / "ledger.db")
    Ledger.default = led
    yield led
    led.close()


@pytest.fixture
def S(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Ledger]:
    """A SQLite ledger through ``Ledger.open``, as a caller gets one."""
    monkeypatch.setenv("DAT_LEDGER", str(tmp_path / "ledger.db"))
    led = Ledger.open()
    yield led
    led.close()  # type: ignore[attr-defined]


def rows(path: Path) -> list[tuple[Any, ...]]:
    with sqlite3.connect(path) as c:
        return list(c.execute("SELECT id, ord, subject, predicate, object, added FROM events ORDER BY id, ord"))


# -- the example, end to end ------------------------------------------------------------------------


def test_example_end_to_end(S: Ledger, tmp_path: Path) -> None:
    L = S
    assert L.rev() == 0
    with L.transaction(by="juan") as tx:
        tx.assign("version", "bb", "1.0.0")
        tx.assign("game/G7", "sport", "bb")
        tx.assign("game/G7", "court", "hs-wood-1")
        tx.add("gameset", "NORM", Ref("game/G3"))
        tx.add("gameset", "NORM", Ref("game/G7"))
    vid = tmp_path / "G7.mp4"
    vid.write_bytes(b"\x00mp4" * 100)
    L.assign("game/G7", "video", L.save(vid, type=video, name="video/G7"), by="juan")
    old = L.rev()
    L.assign("game/G7", "court", "hs-wood-2", by="juan")
    r = L.rev()

    assert L.last("version", "bb", rev=r) == "1.0.0"
    assert L.last("game/G7", "court", rev=r) == "hs-wood-2"
    assert L.last("game/G7", "court", rev=old) == "hs-wood-1"
    v = L.last("game/G7", "video", rev=r)
    assert isinstance(v, Ref) and v.kind == "art" and v.type is video
    assert L.objects("gameset", "NORM", rev=r) == [Ref("game/G3"), Ref("game/G7")]
    spec = L.get_spec("game/G7", rev=r)
    assert spec["sport"] == "bb" and spec["court"] == "hs-wood-2" and spec["video"] == v
    held = L.held(predicate="court", object="hs-wood-2", rev=r)
    assert held == [Event(r, "game/G7", "court", "hs-wood-2", True)]

    with L.transaction(by="dan") as tx:
        tx.assign("version", "bb", "1.0.1")
        tx.assign("version", "date", "2026-10-02")
    assert tx.rev == r + 1

    assert L.add("gameset", "NORM", Ref("game/G9"), by="dan") == r + 2
    assert L.remove("gameset", "NORM", Ref("game/G3"), by="dan") == r + 3
    assert L.objects("gameset", "NORM") == [Ref("game/G7"), Ref("game/G9")]
    L.assign("gameset", "SMALL", ["game/G5", "game/G7"], by="dan")
    assert L.last("gameset", "SMALL") == ["game/G5", "game/G7"]

    shots_file = tmp_path / "shots.json"
    shots_file.write_text('{"shots": [1, 2, 3]}')
    shots = L.save(shots_file, type=json)
    assert shots.type is json and shots.hash is not None and shots.hash.startswith("sha256:")
    assert shots.size == len(shots_file.read_bytes())
    L.assign("game/G7", "annot:shots", shots, by="dan")
    assert L.last("game/G7", "annot:shots").load() == {"shots": [1, 2, 3]}

    hist = L.history("version", "bb")
    assert [(e.object, e.added) for e in hist] == [("1.0.0", True), ("1.0.0", False), ("1.0.1", True)]
    one = L.query(tx=r)
    assert [(e.subject, e.predicate) for e in one][-2:] == [(f"tx/{r}", "by"), (f"tx/{r}", "date")]
    assert all(e.rev == r for e in one)

    n = L.set_spec("game/G7", {"court": "hs-wood-3"}, by="dan")
    assert L.get_spec("game/G7")["court"] == "hs-wood-3"
    assert L.get_spec("game/G7", rev=r)["court"] == "hs-wood-2"
    assert n == L.rev()
    assert Ledger.encode(shots) == f"art:json:{shots.hash}"
    assert L.date(r) == Ledger._today()
    assert L.last(f"tx/{r}", "by") == "juan"


# -- commitments ------------------------------------------------------------------------------------


def test_append_only(S: Ledger) -> None:
    db = S.path  # type: ignore[attr-defined]
    S.assign("a", "p", "1", by="t")
    before = rows(db)
    S.assign("a", "p", "2", by="t")
    S.remove("a", "p", "2", by="t")
    after = rows(db)
    assert after[: len(before)] == before and len(after) > len(before)
    # set is removals plus an addition, each an event with the transaction's rev
    r2 = [x for x in after if x[0] == 2 and x[2] == "a"]
    assert [(x[4], x[5]) for x in r2] == [("str:1", 0), ("str:2", 1)]


def test_one_sequence_commit_order(L: Ledger) -> None:
    revs = [L.add("s", "p", str(i), by="t") for i in range(5)]
    assert revs == [1, 2, 3, 4, 5]
    with L.transaction(by="t") as tx:
        tx.add("s", "q", "x")
        tx.add("s", "q", "y")
    assert {e.rev for e in L.query(tx=tx.rev)} == {6}


def test_reads_are_functions_of_a_rev(L: Ledger) -> None:
    L.assign("g", "court", "a", by="t")
    L.add("set", "N", "x", by="t")
    r = L.rev()
    before = (L.get_spec("g", rev=r), L.objects("set", "N", rev=r), L.held(rev=r), L.query(rev=r))
    L.assign("g", "court", "b", by="t")
    L.remove("set", "N", "x", by="t")
    L.add("set", "N", "y", by="t")
    assert (L.get_spec("g", rev=r), L.objects("set", "N", rev=r), L.held(rev=r), L.query(rev=r)) == before
    assert L.last("g", "court") == "b" and L.objects("set", "N") == ["y"]


def test_typed_objects_decoded_at_the_surface(S: Ledger) -> None:
    S.assign("g", "p", "hs-wood", by="t")
    S.assign("g", "q", {"a": 1}, by="t")
    assert all(":" in r[4] for r in rows(S.path))  # type: ignore[attr-defined]
    assert S.last("g", "p") == "hs-wood" and S.last("g", "q") == {"a": 1}
    with pytest.raises(ValueError):
        S.add("g", "p", 7, by="t")
    with pytest.raises(ValueError):
        Ledger.decode("hs-wood")


def test_provenance_is_triples(S: Ledger) -> None:
    r = S.assign("g", "p", "v", by="dan")
    assert S.last(f"tx/{r}", "by") == "dan"
    assert S.date(r) == Ledger._today()
    with sqlite3.connect(S.path) as c:  # type: ignore[attr-defined]
        cols = [row[1] for row in c.execute("PRAGMA table_info(events)")]
    assert cols == ["id", "ord", "subject", "predicate", "object", "added"]
    # confirmation is one more triple on tx/<rev>, written by the layer above
    S.add(f"tx/{r}", "confirmed_by", "juan", by="juan")
    assert S.last(f"tx/{r}", "confirmed_by") == "juan"


def test_same_evidence_date_from_rows(L: Ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Ledger, "_today", staticmethod(lambda: dt.date(2026, 9, 25)))
    r = L.assign("g", "p", "v", by="t")
    assert L.date(r) == dt.date(2026, 9, 25)
    assert L.last(f"tx/{r}", "date") == "2026-09-25"


def test_side_effects_events_only(S: Ledger, tmp_path: Path) -> None:
    S.add("s", "p", "a", by="t")
    S.add("s", "p", "b", by="t")
    n = len(rows(S.path))  # type: ignore[attr-defined]
    S.assign("s", "p", "c", by="t")  # two removals + one addition + by + date
    assert len(rows(S.path)) - n == 5  # type: ignore[attr-defined]
    S.set_spec("s", {"x": "1", "y": "2"}, by="t")  # two additions + by + date
    assert len(rows(S.path)) - n == 9  # type: ignore[attr-defined]
    with sqlite3.connect(S.path) as c:  # type: ignore[attr-defined]
        tables = sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    assert tables == ["events", "whereabouts"]


def _twin(L: Ledger) -> Ledger:
    """A second connection to the same store, as a second writer has."""
    assert isinstance(L, SqliteLedger)
    return SqliteLedger(L.path, shelf=L._shelf)


def test_concurrency_writers_serialize(L: Ledger) -> None:
    errors: list[BaseException] = []

    def writer(k: int) -> None:
        led = _twin(L)
        try:
            for i in range(10):
                with led.transaction(by=f"w{k}") as tx:
                    tx.add("s", f"p{k}", str(i))
                    tx.add("s", f"q{k}", str(i))
        except BaseException as e:  # pragma: no cover - reported below
            errors.append(e)
        finally:
            led.close()  # type: ignore[attr-defined]

    threads = [threading.Thread(target=writer, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert L.rev() == 40
    for r in range(1, 41):  # dense, commit-ordered, and every transaction whole
        evs = L.query(tx=r)
        assert len(evs) == 4 and len({e.predicate[1:] for e in evs if e.subject == "s"}) == 1
    for k in range(4):
        assert L.objects("s", f"p{k}") == [str(i) for i in range(10)]


def test_typed_by_value_never_schema(L: Ledger) -> None:
    L.assign("g", "court", "hs-wood", by="t")
    r = L.rev()
    L.assign("g", "court", {"name": "hs-wood", "v": 2}, by="t")  # the predicate retyped
    assert L.last("g", "court", rev=r) == "hs-wood"
    assert L.last("g", "court") == {"name": "hs-wood", "v": 2}


def test_reads_are_decoded_refs_not_strings(L: Ledger) -> None:
    ref = Ref("sha256:" + "c0" * 32, hash="sha256:" + "c0" * 32, type=json)
    L.assign("g", "annot", ref, by="t")
    L.add("g", "dat", Ref("game/G7/r4812", type=Dat), by="t")
    out = L.last("g", "annot")
    assert isinstance(out, Ref) and out == ref
    assert L.last("g", "dat") == Ref("game/G7/r4812", type=Dat)


def test_a_reference_is_plain_data(L: Ledger, tmp_path: Path) -> None:
    r = L.save({"k": 1}, type=json)
    L.assign("g", "a", r, by="t")
    got = L.last("g", "a")
    assert (got.name, got.hash, got.type, got.size) == (r.hash, r.hash, json, r.size)
    assert {got, r} == {r}  # hashable, equal by what it points at
    Ledger.default = None  # nothing a read returned fetched anything, and loading needs the default
    with pytest.raises(FileNotFoundError):
        got.load()


def test_artifacts_cost_the_ledger_nothing(S: Ledger) -> None:
    n = S.rev()
    r = S.save({"big": list(range(10))}, type=json, name="asset/x")
    assert S.rev() == n and rows(S.path) == []  # type: ignore[attr-defined]
    assert S.ref("asset/x") == r and S.ref(r.hash or "") == r


def test_store_is_write_once(S: Ledger, tmp_path: Path) -> None:
    a = S.save({"v": 1}, type=json, name="asset/a")
    again = S.save({"v": 1}, type=json)
    assert again == a  # same bytes twice are one artifact
    with pytest.raises(FileExistsError):
        S.save({"v": 2}, type=json, name="asset/a")
    assert S.load("asset/a") == {"v": 1}


def test_location_is_status_not_history(L: Ledger) -> None:
    h = "sha256:" + "ab" * 32
    n = L.rev()
    L._set_whereabouts(h, "azure-westus")
    L._set_whereabouts(h, "azure-westus")
    L._set_whereabouts(h, "gcp-us-central1")
    assert L._whereabouts(h) == ["azure-westus", "gcp-us-central1"]
    assert L.rev() == n  # no event, no rev


def test_no_validation_in_the_ledger(L: Ledger) -> None:
    L.assign("version", "bb", "not-a-version", by="t")
    L.add("gameset", "NORM", "anything", by="t")
    L.remove("gameset", "NORM", "never-held", by="t")  # not an error: the row means nothing yet
    assert L.objects("gameset", "NORM") == ["anything"]


def test_exception_inside_transaction_writes_nothing(L: Ledger) -> None:
    L.assign("g", "p", "a", by="t")
    n = len(L.query())
    with pytest.raises(RuntimeError):
        with L.transaction(by="t") as tx:
            tx.assign("g", "p", "b")
            tx.add("g", "q", "c")
            raise RuntimeError("boom")
    assert len(L.query()) == n and L.rev() == 1 and L.last("g", "p") == "a"
    with pytest.raises(ValueError):
        with L.transaction(by="t") as tx:
            tx.assign("g", "p", "b")
            tx.add("g", "q", 3)  # no encodable kind: refused inside the block, so nothing lands
    assert L.rev() == 1


def test_set_already_held_makes_a_rev(L: Ledger) -> None:
    L.assign("g", "p", "a", by="t")
    r = L.assign("g", "p", "a", by="t")
    assert r == 2 and L.objects("g", "p") == ["a"] and L.exists("g", "p", "a")


def test_remove_and_readd_in_one_transaction(L: Ledger) -> None:
    L.add("s", "p", "x", by="t")
    with L.transaction(by="t") as tx:
        tx.remove("s", "p", "x")
        tx.add("s", "p", "x")
        tx.add("s", "p", "y")
        tx.assign("s", "q", "1")
        tx.assign("s", "q", "2")  # the second set sees the first
    assert L.objects("s", "p") == ["x", "y"]
    assert L.objects("s", "q") == ["2"]


def test_held_and_exists(L: Ledger) -> None:
    L.assign("game/G7", "court", "hs", by="t")
    L.assign("game/G8", "court", "hs", by="t")
    L.assign("game/G9", "court", "other", by="t")
    assert [e.subject for e in L.held(predicate="court", object="hs")] == ["game/G7", "game/G8"]
    assert [e.object for e in L.held(subject="game/G7", predicate="court")] == ["hs"]
    assert len(L.held()) == 3 + 3 * 2  # three triples, plus each transaction's by and date
    assert L.exists("game/G9", "court", "other") and not L.exists("game/G9", "court", "hs")
    assert L.get_spec("nobody") == {} and L.last("nobody", "p") is None and L.objects("nobody", "p") == []


def test_set_spec_get_spec_symmetry(L: Ledger) -> None:
    m = {"sport": "bb", "court": "hs-wood-2", "teams": ["a", "b"], "meta": {"k": 1}, "ref": Ref("game/G1")}
    L.set_spec("game/G7", {"untouched": "keep"}, by="t")
    L.set_spec("game/G7", m, by="t")
    got = L.get_spec("game/G7")
    assert {k: got[k] for k in m} == m and got["untouched"] == "keep"
    r = L.set_spec("game/G7", {"court": "x"}, by="t")
    evs = L.query(tx=r)
    assert [(e.predicate, e.object, e.added) for e in evs if e.subject == "game/G7"] == [
        ("court", "hs-wood-2", False), ("court", "x", True)]


# -- encodings ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("value, text", [
    ("hs-wood", "str:hs-wood"),
    ("", "str:"),
    ("a:b", "str:a:b"),
    ({"b": 1, "a": [1, 2]}, 'json:{"a":[1,2],"b":1}'),
    (["game/G5", "game/G7"], 'json:["game/G5","game/G7"]'),
    (Ref("game/G7"), "node:game/G7"),
    (Ref("game/G7/r4812", type=Dat), "dat:game/G7/r4812"),
    (Ref("sha256:" + "c0" * 32, hash="sha256:" + "c0" * 32, type=json), "art:json:sha256:" + "c0" * 32),
    (Ref("video/G7", type=video), "art:video:video/G7"),
    (Ref("x", hash="sha256:" + "11" * 32, type=ckpt), "art:ckpt:sha256:" + "11" * 32),
    (Ref("x", hash="sha256:" + "22" * 32, type=file), "art:file:sha256:" + "22" * 32),
])
def test_encoding_round_trip(value: Any, text: str) -> None:
    assert Ledger.encode(value) == text
    assert Ledger.decode(text) == value


def test_encoded_rows_round_trip_through_the_store(L: Ledger) -> None:
    values = ["s", {"a": 1}, [1, "x", None, True], Ref("n"), Ref("d/x", type=Dat), Ref("v/1", type=video)]
    for i, v in enumerate(values):
        L.assign("s", f"p{i}", v, by="t")
    assert [L.last("s", f"p{i}") for i in range(len(values))] == values


def test_blob_spill_both_ways(L: Ledger) -> None:
    big = {"annotations": [{"i": i, "label": "x" * 20} for i in range(200)]}
    small = {"k": "v"}
    assert Ledger.encode(big).startswith("blob:sha256:") and Ledger.encode(small).startswith("json:")
    L.assign("g", "big", big, by="t")
    L.assign("g", "small", small, by="t")
    assert L.last("g", "big") == big and L.last("g", "small") == small
    assert L.query("g", "big")[0].object == big
    assert L.exists("g", "big", big) and L.held(predicate="big", object=big)[0].subject == "g"
    assert Ledger.decode(Ledger.encode(big)) == big
    edge = ["x" * (BLOB_BYTES - 4)]  # '["' + … + '"]' is exactly BLOB_BYTES: stays a row
    assert Ledger.encode(edge).startswith("json:")
    assert Ledger.encode(["x" * (BLOB_BYTES - 3)]).startswith("blob:")


def test_blob_is_not_an_art_ref(L: Ledger) -> None:
    big = ["y" * 5000]
    L.assign("g", "big", big, by="t")
    assert isinstance(L.last("g", "big"), list)


# -- the art/ shelf and Ref access --------------------------------------------------------------------


def test_shelf_layout_and_index(S: Ledger) -> None:
    r = S.save(b"hello", type=file, name="blob/hello")
    shelf = S._shelf
    assert isinstance(shelf, LocalShelf)
    hexd = (r.hash or "")[len("sha256:"):]
    assert (shelf.root / "sha256" / hexd[:2] / hexd[2:]).read_bytes() == b"hello"
    (shelf.root / "_index_.json").unlink()
    assert S.ref("blob/hello") is None
    assert shelf.reindex() == {"blob/hello": r.hash}
    assert S.ref("blob/hello") == r


def test_save_and_load_every_type(S: Ledger, tmp_path: Path) -> None:
    f = tmp_path / "x.bin"
    f.write_bytes(b"\x01\x02")
    folder = tmp_path / "ck"
    (folder / "sub").mkdir(parents=True)
    (folder / "w.pt").write_bytes(b"w" * 10)
    (folder / "sub" / "c.json").write_text("{}")
    mp4 = tmp_path / "g.mp4"
    mp4.write_bytes(b"mp4" * 7)
    assert S.save([1, 2], type=json).load() == [1, 2]
    assert S.save(b"raw", type=file).load() == b"raw"
    assert S.save(f, type=file).load() == b"\x01\x02"
    ck = S.save(folder, type=ckpt)
    assert ck.size == 12 and (ck.load() / "w.pt").read_bytes() == b"w" * 10
    v = S.save(mp4, type=video, name="video/G7")
    assert v.load().read_bytes() == b"mp4" * 7 and v.size == 21
    assert S.ref("video/G7") == v and S.load("video/G7").read_bytes() == b"mp4" * 7
    with pytest.raises(ValueError):
        S.save({"a": 1}, type=ckpt)


def test_ref_load_path(S: Ledger, tmp_path: Path) -> None:
    mp4 = tmp_path / "g.mp4"
    mp4.write_bytes(b"frames")
    v = S.save(mp4, type=video)
    own = v.load_path()
    assert own.read_bytes() == b"frames" and S._shelf.root in own.parents  # type: ignore[attr-defined]
    dest = v.load_path(tmp_path / "out" / "copy.mp4")
    assert dest.read_bytes() == b"frames"
    folder = tmp_path / "ck"
    folder.mkdir()
    (folder / "a").write_text("1")
    ck = S.save(folder, type=ckpt)
    assert (ck.load_path(tmp_path / "ck2") / "a").read_text() == "1"
    with pytest.raises(ValueError):
        Ref("game/G7").load_path()


def test_node_ref_loads_its_spec(S: Ledger) -> None:
    S.set_spec("game/G7", {"sport": "bb"}, by="t")
    assert Ref("game/G7").load() == {"sport": "bb"}


def test_ref_read_from_a_row_fills_size(S: Ledger) -> None:
    r = S.save({"a": 1}, type=json)
    S.assign("g", "a", r, by="t")
    assert S.last("g", "a").size == r.size


# -- Ledger.open --------------------------------------------------------------------------------------


def test_open_sets_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAT_LEDGER", str(tmp_path / "new" / "l.db"))
    led = Ledger.open()
    assert isinstance(led, SqliteLedger) and Ledger.default is led and (tmp_path / "new" / "l.db").is_file()
    monkeypatch.setenv("DAT_LEDGER", str(tmp_path))
    assert Ledger.open().path == tmp_path / "ledger.db"  # type: ignore[attr-defined]


def test_open_from_profile(tmp_path: Path) -> None:
    prof = tmp_path / "ledger.profile.yaml"
    prof.write_text(yaml.safe_dump({"backend": "sqlite", "path": str(tmp_path / "p.db"), "art": str(tmp_path / "a")}))
    led = Ledger.open(prof)
    assert isinstance(led, SqliteLedger) and led.path == tmp_path / "p.db"
    assert led.save(b"x", type=file).load_path().is_relative_to(tmp_path / "a")


# -- errors -------------------------------------------------------------------------------------------


def test_error_value_malformed_name(L: Ledger) -> None:
    for bad in ("", None):
        with pytest.raises(ValueError):
            L.add(bad, "p", "x", by="t")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            L.assign("s", bad, "x", by="t")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        L.last("", "p")
    assert L.rev() == 0


def test_error_value_unencodable_object(L: Ledger) -> None:
    for bad in (3, 1.5, True, dt.date(2026, 1, 1), ("a",), {"a": {1, 2}}, [Ref("x")]):
        with pytest.raises(ValueError):
            L.add("s", "p", bad, by="t")
    assert L.rev() == 0


def test_error_value_rev_above_current(L: Ledger) -> None:
    L.add("s", "p", "x", by="t")
    for call in (lambda: L.last("s", "p", rev=2), lambda: L.query(rev=5), lambda: L.query(tx=2),
                 lambda: L.held(rev=-1), lambda: L.date(9)):
        with pytest.raises(ValueError):
            call()


@pytest.mark.parametrize("text", ["hs-wood", "", "int:3", "Str:x", "art:mp4:sha256:" + "0" * 64,
                                  "art:json", "blob:nothash", "node:", "json:{bad"])
def test_error_value_decode_prefix(text: str) -> None:
    with pytest.raises(ValueError):
        Ledger.decode(text)


def test_error_key_query_rev_no_transaction(L: Ledger) -> None:
    with pytest.raises(KeyError):
        L.query(tx=0)
    L.add("s", "p", "x", by="t")
    assert L.query(tx=1)


def test_error_file_not_found_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger_core, "profile_path", lambda: None)
    with pytest.raises(FileNotFoundError, match="DAT_LEDGER") as e:
        Ledger.open()
    with pytest.raises(FileNotFoundError):
        Ledger.open(tmp_path / "missing.yaml")


def test_error_file_not_found_load(S: Ledger, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        S.load("asset/none")
    assert S.ref("asset/none") is None
    orphan = Ref("sha256:" + "ee" * 32, hash="sha256:" + "ee" * 32, type=json)
    with pytest.raises(FileNotFoundError):
        orphan.load()
    with pytest.raises(FileNotFoundError):
        Ledger.decode("blob:sha256:" + "ee" * 32)  # a blob this store does not hold


def test_error_file_exists_save(S: Ledger) -> None:
    S.save(b"a", type=file, name="n")
    S.save(b"a", type=file, name="n")  # same bytes: fine
    with pytest.raises(FileExistsError):
        S.save(b"b", type=file, name="n")


def test_error_ledger_error_corrupt_file(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    db.write_bytes(b"this is not a sqlite database" * 100)
    with pytest.raises(LedgerError, match="sqlite"):
        SqliteLedger(db)


def test_error_ledger_error_lock(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    led = SqliteLedger(db)
    other = sqlite3.connect(db, isolation_level=None, timeout=0)
    other.execute("BEGIN IMMEDIATE")  # another writer holds the lock
    led._conn.execute("PRAGMA busy_timeout = 50")
    with pytest.raises(LedgerError, match="sqlite ledger refused"):
        led.add("s", "p", "x", by="t")
    other.execute("ROLLBACK")
    assert led.add("s", "p", "x", by="t") == 1


def test_batch_is_the_context_manager(L: Ledger) -> None:
    tx = L.transaction(by="t")
    assert isinstance(tx, Batch)
    with pytest.raises(RuntimeError):
        tx.rev
    with pytest.raises(RuntimeError):
        tx.add("s", "p", "x")  # outside the block
    with tx:
        tx.add("s", "p", "x")
    assert tx.rev == 1
    with pytest.raises(ValueError):
        L.transaction(by="")


def test_node_is_default_ref_type() -> None:
    assert Ref("game/G7").type is Node and Ref("game/G7").kind == "node"


# -- the T195 names -----------------------------------------------------------------------------------


def test_subjects_is_the_reverse_lookup(L: Ledger) -> None:
    L.assign("game/G7", "court", "hs", by="t")
    L.assign("game/G8", "court", "hs", by="t")
    r = L.rev()
    L.assign("game/G7", "court", "other", by="t")
    L.add("gameset", "NORM", Ref("game/G8"), by="t")
    assert L.subjects("court", "hs") == ["game/G8"]
    assert L.subjects("court", "hs", rev=r) == ["game/G7", "game/G8"]
    assert L.subjects("NORM", Ref("game/G8")) == ["gameset"]
    assert L.subjects("court", "nowhere") == []


def test_query_rev_is_as_of_and_tx_is_one_transaction(L: Ledger) -> None:
    L.assign("s", "p", "a", by="t")
    L.assign("s", "p", "b", by="t")
    L.assign("s", "p", "c", by="t")
    assert [e.rev for e in L.query("s", "p", rev=2)] == [1, 2, 2]
    assert [(e.object, e.added) for e in L.query("s", "p", tx=2)] == [("a", False), ("b", True)]
    assert L.query("s", "p", rev=1, tx=1) == L.query("s", "p", tx=1)
    assert [e.object for e in L.history("s", "p", rev=1)] == ["a"]


def test_no_set_on_the_surface(L: Ledger) -> None:
    assert not hasattr(L, "set") and not hasattr(L.transaction(by="t"), "set")


# -- profiles and backends by dotted name -------------------------------------------------------------


def test_profile_paths_are_relative_to_the_profile(tmp_path: Path) -> None:
    (tmp_path / "proj").mkdir()
    prof = tmp_path / "proj" / "ledger.profile.yaml"
    prof.write_text(yaml.safe_dump({"backend": "sqlite", "path": "state/l.db", "art": "state/art"}))
    led = Ledger.open(prof)
    assert led.path == tmp_path / "proj" / "state" / "l.db"  # type: ignore[attr-defined]
    assert led._shelf.root == tmp_path / "proj" / "state" / "art"  # type: ignore[attr-defined]


def test_profile_is_found_from_the_working_directory_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "ledger.profile.yaml").write_text(yaml.safe_dump({"path": "l.db"}))  # backend defaults to sqlite
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    assert ledger_core.profile_path() == tmp_path / "ledger.profile.yaml"
    led = Ledger.open()
    assert led.path == tmp_path / "l.db" and Ledger.default is led  # type: ignore[attr-defined]


class Tagged(SqliteLedger):
    """A consumer's backend, named in a profile by its dotted name."""

    @classmethod
    def from_profile(cls, profile: dict, folder: Path, shelf: Any) -> "Tagged":
        return cls(folder / str(profile["file"]), shelf=shelf)


def test_backend_by_dotted_name(tmp_path: Path) -> None:
    prof = tmp_path / "ledger.profile.yaml"
    prof.write_text(yaml.safe_dump({"backend": f"{__name__}.Tagged", "file": "t.db"}))
    led = Ledger.open(prof)
    assert type(led).__name__ == "Tagged" and led.path == tmp_path / "t.db"  # type: ignore[attr-defined]
    for bad in ("mysql", "no.such.module.Ledger", "dvc_dat.Dat"):
        prof.write_text(yaml.safe_dump({"backend": bad, "path": "x.db"}))
        with pytest.raises(ValueError):
            Ledger.open(prof)


def test_an_artifact_type_registers_by_its_token(L: Ledger) -> None:
    class text(Artifact):  # noqa: N801
        token = "text"

        @classmethod
        def source(cls, obj: Any) -> bytes:
            return str(obj).encode()

        @classmethod
        def decode(cls, payload: Path) -> Any:
            return payload.read_text()

    try:
        r = L.save("hello", type=text, name="greeting")
        L.assign("g", "t", r, by="t")
        assert Ledger.encode(r).startswith("art:text:sha256:") and L.last("g", "t").load() == "hello"
        assert L.ref("greeting") == r
    finally:
        ART_TYPES.pop("text", None)


def test_a_dat_ref_loads_through_the_dat_manager(tmp_path: Path) -> None:
    d = Dat.create(path=str(tmp_path / "d1"), spec={"main": {"note": "x"}})
    r = Ref(str(tmp_path / "d1"), type=Dat)
    assert Ledger.encode(r) == f"dat:{tmp_path / 'd1'}"
    assert r.load_path() == Path(d.get_path_name())
