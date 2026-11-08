"""Values stream to and from the store, never whole in RAM (DAT 240): ``encode(out)`` writes to a sink the
store opens, ``decode(src, store)`` reads a stream; the hashes of 2.52.0 do not move (a Table's moved once, by
SVP 1543); a save encodes once."""

import io
import tracemalloc

import pyarrow as pa
import pytest

from dvc_dat import Dat
from dvc_dat.ledger import Value
from dvc_dat.ledger.codec import hash_sink, sha256
from ledger_kinds import ENCODES, MIB, Streamed

#: Measured on dvc-dat 2.52.0 (before streaming) and pinned: every existing ledger names these.
BLOB = "6d1832bcc06409395ea3fa6544b93cec31e35382784b998fefe8f35b21f5a2b3"
DAT = "70da370b78f1d35bbf71d78b92f2d0596ddf5134dec0bc7ce1c12ce53e82bf6c"
#: Moved by SVP 1543 (a Table encodes its columns, its footer naming no pyarrow version) and pinned: the same
#: under pyarrow 25.0.1 and 26.0.0.
TABLE = "e922dfa5d01d3b50a8ce1bf767073ee06876933d7db7242943302ebeb99b6481"


def encoded(v: Value) -> bytes:
    out = io.BytesIO()
    v.encode(out)
    return out.getvalue()


def golden_dat(root):
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("one")
    (root / "sub" / "b.txt").write_text("two")
    return Dat(root)


def test_the_hashes_of_2_52_0_do_not_move(tmp_path):
    blob = Value.Blob({"a": 1, "b": [1, 2, 3]})
    table = Value.Table(pa.table({"x": [1, 2, 3]}))
    dat = golden_dat(tmp_path / "d")
    assert blob.hash == BLOB == sha256(encoded(blob))
    assert dat.hash == DAT == sha256(encoded(dat))
    assert table.hash == TABLE == sha256(encoded(table))


def test_a_sealed_value_keeps_its_hash_and_loads_back_from_a_stream(L, tmp_path):
    blob = Value.Blob({"a": 1, "b": [1, 2, 3]})
    table = Value.Table(pa.table({"x": [1, 2, 3]}))
    dat = golden_dat(tmp_path / "d")
    want = {"blob": BLOB, "dat": DAT, "table": table.hash}
    for name, v in (("blob", blob), ("table", table), ("dat", dat)):
        v.seal(L, name=f"golden/{name}")
        assert v.hash == want[name]
        assert sha256(L._store.art.path(v.hash).read_bytes()) == want[name]     # the stored bytes, by name
    L._values.clear()
    head = L.at()
    assert head.load("golden/blob").obj == {"a": 1, "b": [1, 2, 3]}
    assert head.load("golden/table").table.column("x").to_pylist() == [1, 2, 3]
    got = head.load("golden/dat")
    assert got.hash == DAT and (got.path / "sub" / "b.txt").read_text() == "two"


def test_a_sink_is_forward_only():
    s = hash_sink()
    s.write(b"abc")
    with pytest.raises(io.UnsupportedOperation, match="forward-only"):
        s.seek(0)
    assert (s.hash, s.size, s.tell()) == (sha256(b"abc"), 3, 3)


def test_a_save_encodes_once(L):
    ENCODES.clear()
    Streamed(2).seal(L, name="s/one")
    assert ENCODES == {"Streamed": 1}
    ENCODES.clear()
    v = Streamed(3)
    v.seal()
    v.seal(L, name="s/two")
    assert ENCODES == {"Streamed": 2}


def test_a_large_value_seals_and_loads_without_its_bytes_in_memory(L):
    blocks = 256
    tracemalloc.start()
    try:
        v = Streamed(blocks)
        tracemalloc.reset_peak()
        v.seal(L, name="s/big")
        _, seal_peak = tracemalloc.get_traced_memory()
        L._values.clear()
        tracemalloc.reset_peak()
        got = L.at().load("s/big")
        _, load_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert got.blocks == blocks
    assert L._store.art.path(v.hash).stat().st_size == blocks * len(MIB)
    assert seal_peak < 64 * len(MIB) and load_peak < 64 * len(MIB), (seal_peak, load_peak)
