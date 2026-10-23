"""Streaming values: parts by (sha256, source), hardlinked or streamed into the stores, never
held whole; ``decode(name=)``, ``Dat.kind_ok``, ``DAT_WORK``. The 2 GB acceptance run is behind
``DAT_SLOW=1`` (a subprocess, so its RSS is its own)."""

import io
import os
import subprocess
import sys
import textwrap

import pytest

from dvc_dat.ledger import Dat, Ref, Value
from dvc_dat.ledger.codec import sha256
from dvc_dat.ledger.kept import Kept
from dvc_dat.ledger.store import file_sha
from ledger_kinds import CALLS


@pytest.fixture(autouse=True)
def kept_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DAT_KEPT", str(tmp_path / "kept"))
    return tmp_path / "kept"


def folder(path, **files):
    path.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (path / name).write_text(text)
    return path


def test_a_saved_dat_hardlinks_its_files_into_the_art_store(L, tmp_path):
    src = folder(tmp_path / "src", **{"a.txt": "one", "b.txt": "two"})
    ino = (src / "a.txt").stat().st_ino
    d = Dat(src)
    d.seal(L, name="clip/1")
    blob = L._store.art.path(sha256(b"one"))
    if L._store.art.root.stat().st_dev == src.stat().st_dev:
        assert blob.stat().st_ino == ino
    assert (d.path / "b.txt").read_text() == "two"
    assert Ref(L.at(), "clip/1").hash == d.hash


def test_a_kept_dat_copies_its_parts_so_the_source_may_change(L, tmp_path):
    src = folder(tmp_path / "src", **{"a.txt": "one"})
    d = Dat(src)
    d.seal(keep=True)
    blob = Kept().blob(sha256(b"one"))
    assert blob.stat().st_ino != (src / "a.txt").stat().st_ino
    with open(src / "a.txt", "w") as f:                    # an in-place write: the kept copy is apart
        f.write("two")
    d.seal(L)
    assert (d.path / "a.txt").read_text() == "one"


def test_the_hash_follows_a_changed_file(tmp_path):
    src = folder(tmp_path / "src", **{"a.txt": "one"})
    d = Dat(src)
    h = d.hash
    (src / "a.txt").write_text("three")
    assert d.hash != h
    (src / "a.txt").unlink()
    assert d.hash == sha256(b'{"files":{}}')


def test_a_part_from_an_opener_is_streamed_and_checked(L):
    from ledger_kinds import Blobby

    v = Blobby(b"x" * 3_000_000)
    s = v.seal(L)
    assert L.at().load(s).data == v.data
    bad = Blobby(b"y")
    bad._parts = lambda: [(sha256(b"z"), lambda: io.BytesIO(b"y"))]
    with pytest.raises(ValueError, match="source changed"):
        bad.seal(L)
    assert not L._store.art.exists(sha256(b"z"))


def test_a_load_by_alias_lands_under_its_name_and_follows_a_repoint(L, tmp_path):
    a = Dat(folder(tmp_path / "a", **{"x.txt": "1", "y.txt": "2"}))
    a.seal(L, name="game/G1")
    got = L.at().load("game/G1")
    assert got.path == L._store.art.root / "dats" / "game" / "G1"
    assert sorted(p.name for p in got.path.iterdir()) == ["x.txt", "y.txt"]
    b = Dat(folder(tmp_path / "b", **{"x.txt": "3"}))
    b.seal(L, name="game/G1")
    again = L.at().load("game/G1")
    assert again.path == got.path and sorted(p.name for p in again.path.iterdir()) == ["x.txt"]
    assert (again.path / "x.txt").read_text() == "3"
    assert L.at().load(a.subject).path.name == a.hash[:16]          # by subject: the hash folder


def test_decode_without_name_still_loads():
    class Old(Dat):
        @classmethod
        def decode(cls, data, store):
            obj = cls.__new__(cls)
            obj.path = cls._materialise(data, store)
            return obj

    from dvc_dat.ledger.value import takes_name

    assert takes_name(Dat) and not takes_name(Old)


def test_kind_ok_lets_a_class_accept_a_foreign_dat_kind(L, tmp_path):
    import ledger_kinds

    src = folder(tmp_path / "s", **{"_spec_.yaml": "dat:\n  kind: GameDat\n"})
    d = ledger_kinds.Dat2(src)
    d.seal(L, name="g/1")
    with pytest.raises(TypeError, match="dat.kind GameDat"):
        L.at().load("g/1")
    ledger_kinds.Dat2.kinds = ("GameDat",)
    try:
        L._values.clear()
        assert L.at().load("g/1").path.is_dir()
    finally:
        ledger_kinds.Dat2.kinds = ()


def test_dat_work_names_the_work_parent(coded, tmp_path, monkeypatch):
    monkeypatch.setenv("DAT_WORK", str(tmp_path / "work"))
    coded.at().run("ledger_kinds.scratchy", game="G1", memo=False)
    assert CALLS["work"].parent == tmp_path / "work" and CALLS["work"].name.startswith("ledger-work-")


SCRIPT = textwrap.dedent("""
    import json, os, resource, sys
    from pathlib import Path
    from dvc_dat.ledger import Dat, Ledger
    from dvc_dat.ledger.kept import Kept

    root = Path(sys.argv[1])
    src = root / "big"
    src.mkdir()
    for name, size in (("a.bin", 700_000_000), ("b.bin", 700_000_000), ("c.bin", 747_483_648)):
        with open(src / name, "wb") as f:
            f.truncate(size)                       # sparse zeros, plus one distinct byte each
            f.seek(size - 1)
            f.write(name[0].encode())
    L = Ledger(root / "ledger", create=True)
    L.at()
    scale = 1 if sys.platform == "darwin" else 1024
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale
    d = Dat(src)
    d.seal(keep=True)
    s = d.seal(L, name="big/1")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale
    art = L._store.art
    linked = []
    for rel, h in sorted(json.loads(art.get(d.hash))["files"].items()):
        linked.append(os.path.samefile(art.path(h), Kept().blob(h)) and os.path.samefile(art.path(h), d.path / rel))
    print(json.dumps({"growth": peak - before, "before": before, "peak": peak, "linked": linked,
                      "bytes": sum(p.stat().st_size for p in d.path.iterdir())}))
""")


@pytest.mark.skipif(os.environ.get("DAT_SLOW") != "1", reason="2 GB acceptance run: set DAT_SLOW=1")
def test_a_2gb_dat_seals_kept_and_saves_in_bounded_memory(tmp_path):
    import json

    env = dict(os.environ, DAT_KEPT=str(tmp_path / "kept"))
    out = subprocess.run([sys.executable, "-c", SCRIPT, str(tmp_path)], capture_output=True, text=True, env=env,
                         timeout=1200)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    print(r)
    assert r["bytes"] == 2_147_483_648
    assert r["growth"] < 100 * 1024 ** 2, r
    assert all(r["linked"]), r
