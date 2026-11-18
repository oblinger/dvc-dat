"""Streaming values: parts by (sha256, source), cloned or streamed into the stores (never linked), never
held whole; ``decode(name=)``, ``Dat.kind_ok``, ``DAT_WORK``. The 2 GB acceptance run is behind
``DAT_SLOW=1`` (a subprocess, so its RSS is its own)."""

import io
import json
import os
import subprocess
import sys
import textwrap

import pytest

from dvc_dat import Dat
from dvc_dat.ledger import Ref, Value
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


def test_a_write_through_a_working_or_materialised_file_never_reaches_a_sealed_blob(L, tmp_path):
    """SVP 1780: a document sealed from its working folder, loaded by name, then each file rewritten in place (as a
    rolling save rewrites ``_result_.yaml``, or an editor its page): every blob still hashes to its name."""
    src = folder(tmp_path / "src", **{"page.md": "one", "_result_.yaml": "rev: 4\n"})
    d = Dat(src)
    d.seal(L, name="pub/D1")
    art = L._store.art
    view = Ref(L.at(), "pub/D1").load().path
    for f in (src / "page.md", src / "_result_.yaml", view / "page.md", view / "_result_.yaml"):
        with open(f, "w") as out:                          # an in-place write, the inode kept
            out.write("rev: 6\n")
    for h in Dat._stored_manifest(art, d.hash).values():
        assert file_sha(art.path(h)) == h
    assert art.mismatched() == []
    assert (view / "page.md").read_text() == "rev: 6\n"
    assert Ref(L.at(), "pub/D1").hash == d.hash


# -- SVP 1780, the review's probes: each reloads through a fresh handle, so the view is checked again -----------------

def _fresh(tmp_path):
    from dvc_dat.ledger import Ledger

    return Ledger(str(tmp_path / "ledger"))


def _blob(L, d, rel):
    art = L._store.art
    return art.path(Dat._stored_manifest(art, d.hash)[rel])


@pytest.mark.parametrize("atomic", [False, True])
def test_a_view_edited_same_size_with_its_mtime_restored_is_placed_anew(tmp_path, atomic):
    from dvc_dat.ledger import Ledger

    L = Ledger(str(tmp_path / "ledger"), create=True)
    d = Dat(folder(tmp_path / "src", **{"w.bin": "AAAA"}))
    d.seal(L, name="m/1")
    f = Ref(L.at(), "m/1").load().path / "w.bin"
    st = f.stat()
    if atomic:                                             # rsync -t, cp -p: a new file, the mtime set back
        (f.parent / "w.new").write_text("BBBB")
        os.replace(f.parent / "w.new", f)
    else:
        with open(f, "r+") as out:
            out.write("BBBB")
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    w = Ref(_fresh(tmp_path).at(), "m/1").load()
    assert (w.path / "w.bin").read_text() == "AAAA" and w.hash == d.hash


def test_a_source_rewritten_after_its_bytes_were_checked_is_not_trusted_on_reload(tmp_path, monkeypatch):
    """The working folder is the view's own place; it is rewritten (same size) right after the seal copied it."""
    from dvc_dat.ledger import Ledger
    from dvc_dat.ledger import store

    L = Ledger(str(tmp_path / "ledger"), create=True)
    src = folder(L._store.art.dats / "roll" / "1", **{"_result_.yaml": "rev: 4\n"})
    real_sha, real_copy, fired = store.file_sha, store._copy, []

    def after(path):
        if not fired and ".tmp-" in str(path) and "sha256" in str(path):
            fired.append(1)
            with open(src / "_result_.yaml", "r+") as out:
                out.write("rev: 6\n")

    store.file_sha = lambda p: (real_sha(p), after(p))[0]
    store._copy = lambda f, dest, h: (real_copy(f, dest, h), after(dest))[0]
    try:
        d = Dat(src)
        d.seal(L, name="roll/1")
    finally:
        store.file_sha, store._copy = real_sha, real_copy
    assert fired
    w = Ref(_fresh(tmp_path).at(), "roll/1").load()
    assert (w.path / "_result_.yaml").read_text() == "rev: 4\n" and w.hash == d.hash


@pytest.mark.parametrize("cloned", [True, False])
def test_the_executable_bit_survives_a_seal_and_a_load(tmp_path, monkeypatch, cloned):
    import stat

    from dvc_dat.ledger import Ledger
    from dvc_dat.ledger import store

    if not cloned:
        monkeypatch.setattr(store, "clone", lambda a, b: False)
    L = Ledger(str(tmp_path / "ledger"), create=True)
    src = folder(tmp_path / "src", **{"run.sh": "#!/bin/sh\n"})
    os.chmod(src / "run.sh", 0o755)
    Dat(src).seal(L, name="x/1")
    w = Ref(_fresh(tmp_path).at(), "x/1").load()
    assert stat.S_IMODE((w.path / "run.sh").stat().st_mode) == 0o755


def test_a_view_hardlinked_before_the_fix_is_placed_anew_on_load(tmp_path):
    from dvc_dat.ledger import Ledger

    L = Ledger(str(tmp_path / "ledger"), create=True)
    d = Dat(folder(tmp_path / "src", **{"a.txt": "one!"}))
    d.seal(L, name="old/1")
    blob, view = _blob(L, d, "a.txt"), d.path
    (view / "a.txt").unlink()
    os.link(blob, view / "a.txt")                          # what get_to made before SVP 1780
    w = Ref(_fresh(tmp_path).at(), "old/1").load()
    assert not os.path.samefile(w.path / "a.txt", blob)
    with open(w.path / "a.txt", "r+") as out:
        out.write("two!")
    assert file_sha(blob) == blob.name


def test_detach_gives_every_linked_blob_its_own_inode_and_keeps_its_bytes(tmp_path):
    from dvc_dat.ledger import Ledger

    L = Ledger(str(tmp_path / "ledger"), create=True)
    d = Dat(folder(tmp_path / "src", **{"a.txt": "one!", "b.txt": "two!"}))
    d.seal(L, name="old/1")
    art, blob = L._store.art, _blob(L, d, "a.txt")
    os.chmod(blob, 0o755)
    os.link(blob, tmp_path / "alias")                      # a working file linked to it before SVP 1780
    before = blob.stat()
    assert art.detach(dry_run=True) == 1 and os.path.samefile(blob, tmp_path / "alias")
    assert art.detach() == 1 and art.detach(dry_run=True) == 0
    after = blob.stat()
    assert after.st_nlink == 1 and (after.st_mtime_ns, after.st_mode) == (before.st_mtime_ns, before.st_mode)
    with open(tmp_path / "alias", "r+") as out:
        out.write("XXXX")
    assert art.mismatched() == []


def test_a_corrupt_blob_loaded_into_a_fresh_view_is_named_as_corrupt(tmp_path):
    import shutil

    from dvc_dat.ledger import Ledger

    L = Ledger(str(tmp_path / "ledger"), create=True)
    d = Dat(folder(tmp_path / "src", **{"a.txt": "one!"}))
    d.seal(L, name="c/1")
    blob = _blob(L, d, "a.txt")
    with open(blob, "r+") as out:
        out.write("XXXX")
    shutil.rmtree(L._store.art.dats / "c")
    with pytest.raises(ValueError, match=f"blob {blob} is corrupt"):
        Ref(_fresh(tmp_path).at(), "c/1").load()


def test_mismatched_on_a_read_only_handle_reads_its_overlay_too(tmp_path):
    from dvc_dat.ledger.store import ReadOnlyArt

    art = ReadOnlyArt(tmp_path / "root", tmp_path / "overlay")
    for root, body in ((art.root, b"root"), (art.overlay, b"overlay")):
        p = root / "sha256" / "ab" / ("ab" + "0" * 62)
        p.parent.mkdir(parents=True)
        p.write_bytes(body)
    assert [n for n, _got in art.mismatched()] == ["ab" + "0" * 62] * 2


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
        def decode(cls, src, store):
            data = src.read()
            obj = cls.__new__(cls)
            obj.path = cls._materialise(sha256(data), json.loads(data)["files"], store)
            return obj

    from dvc_dat.ledger.value import takes_name

    assert takes_name(Dat) and not takes_name(Old)


def test_kind_ok_lets_a_class_accept_a_foreign_dat_kind(L, tmp_path):
    import ledger_kinds

    src = folder(tmp_path / "s", **{"_spec_.yaml": "dat:\n  kind: GameDat\n",
                                    "_result_.yaml": "dat:\n  standing: sealed\n"})
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
    coded.at().run("ledger_kinds.scratchy", game="G1", seal=False)
    assert CALLS["work"].parent == tmp_path / "work" and CALLS["work"].name.startswith("ledger-work-")


SCRIPT = textwrap.dedent("""
    import json, os, resource, sys
    from pathlib import Path
    from dvc_dat import Dat
    from dvc_dat.ledger import Ledger
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
    apart = []
    for rel, h in sorted(Dat._stored_manifest(art, d.hash).items()):
        apart.append(not os.path.samefile(art.path(h), Kept().blob(h)) and not os.path.samefile(art.path(h), d.path / rel))
    print(json.dumps({"growth": peak - before, "before": before, "peak": peak, "apart": apart,
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
    assert all(r["apart"]), r
