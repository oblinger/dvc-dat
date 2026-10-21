"""A seal persists: every ``v.seal()`` writes a record, and a later process saves it as the sealing one would."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dvc_dat.ledger import Dat, Ref, SealBroken
from dvc_dat.ledger.kept import Kept, age
from ledger_kinds import GameDat, Plain

HERE = Path(__file__).parent

CHILD = textwrap.dedent('''
    import sys
    from pathlib import Path
    sys.path.insert(0, {here!r})
    from dvc_dat.ledger import Code, Dat, Env, set_env_provider
    from ledger_kinds import GameDat
    set_env_provider(lambda: Env({{"testrepo": Code(None, "abc1234", False, Path({here!r}))}},
                                 "test-platform"))
    {body}
''')


def in_child(tmp_path, body):
    """Run ``body`` in a fresh interpreter, with the suite's pinned environment and kept folder."""
    code = CHILD.format(here=str(HERE), body=textwrap.indent(textwrap.dedent(body), "").strip())
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "DAT_KEPT": str(tmp_path / "kept")})
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def folder(tmp_path, name, text):
    p = tmp_path / name
    p.mkdir()
    (p / "a.txt").write_text(text)
    return p


def test_a_seal_writes_a_record_kept_or_not(tmp_path):
    src = folder(tmp_path, "src", "one")
    d = GameDat(src)
    d.preds.update(game="G1", take=2)
    h = d.seal(provenance="run:demo")
    p = Plain(b"x")
    p.seal(keep=True)
    rows = Kept().listing()
    assert [r["kept"] for r in rows] == [False, True]
    rec = rows[0]
    assert rec["hash"] == h and rec["path"] == str(src.resolve()) and rec["provenance"] == "run:demo"
    assert rec["kind"].endswith("GameDat") and rec["bytes"] == 3 and rec["env"]["code"]["testrepo"]["commit"] == "abc1234"
    assert rows[1]["path"] is None


def test_a_seal_in_one_process_saves_in_another_as_in_one(L, tmp_path):
    a = folder(tmp_path, "a", "one")
    h = in_child(tmp_path, f'''
        d = GameDat(Path({str(a)!r}))
        d.preds.update(game="G1", take=2)
        print(d.seal(provenance="run:demo"))
    ''')
    v = GameDat.sealed_at_path(a)
    assert v.sealed and v.subject is None and v.hash == h and dict(v.preds) == {"game": "G1", "take": 2}
    s = v.seal(L, alias="game/G1")
    assert Kept().listing() == []                    # saved: the record goes at commit
    b = folder(tmp_path, "b", "one")                 # the same bytes, sealed and saved in this process
    w = GameDat(b)
    w.preds.update(game="G1", take=2)
    w.seal(provenance="run:demo")
    assert w.seal(L) == s
    assert L.at()[s, "db/sealed-at"] == v.sealed_at


def test_changed_bytes_break_a_reopened_seal_unless_kept(L, tmp_path):
    a = folder(tmp_path, "a", "one")
    k = folder(tmp_path, "k", "kept")
    in_child(tmp_path, f'''
        GameDat(Path({str(a)!r})).seal()
        GameDat(Path({str(k)!r})).seal(keep=True)
    ''')
    (a / "a.txt").write_text("two")
    (k / "a.txt").write_text("changed")
    with pytest.raises(SealBroken, match="changed"):
        GameDat.sealed_at_path(a).seal(L)
    v = GameDat.sealed_at_path(k)
    v.seal(L, alias="k/1")
    assert (Ref(L.at(), "k/1").load().path / "a.txt").read_text() == "kept"


def test_a_dep_sealed_before_it_is_saved_binds_by_its_name(L, tmp_path):
    a = folder(tmp_path, "a", "input")
    b = folder(tmp_path, "b", "output")
    in_child(tmp_path, f'''
        GameDat(Path({str(a)!r})).seal()
        GameDat(Path({str(b)!r})).seal(deps=[GameDat.sealed_at_path(Path({str(a)!r}), name="in/A")])
    ''')
    with pytest.raises(ValueError, match="saved nowhere"):
        GameDat.sealed_at_path(b).seal(L)
    GameDat.sealed_at_path(a).seal(L, alias="in/A")
    s = GameDat.sealed_at_path(b).seal(L, alias="out/B")
    c = folder(tmp_path, "c", "output")
    w = GameDat(c)
    w.seal(deps=[Ref(L.at(), "in/A")])
    assert w.seal(L) == s
    assert "in/A db/alias" in Ref(L.at(), "out/B").load().trace


def test_a_new_seal_of_a_folder_replaces_its_unkept_record(tmp_path):
    a = folder(tmp_path, "a", "one")
    GameDat(a).seal()
    GameDat(a).seal(keep=True)
    (a / "a.txt").write_text("two")
    GameDat(a).seal()
    rows = Kept().listing()
    assert [r["kept"] for r in rows] == [True, False]
    assert GameDat.sealed_at_path(a).hash == rows[1]["hash"]
    assert GameDat.sealed_at_path(tmp_path / "nowhere") is None
    with pytest.raises(TypeError, match="not a"):
        type("Other", (Dat,), {}).sealed_at_path(a)


def test_purge_drops_records_kept_or_not(tmp_path, kept_folder):
    GameDat(folder(tmp_path, "a", "one")).seal()
    Plain(b"old").seal(keep=True)
    assert len(Kept().listing()) == 2 and len(list((kept_folder / "blobs").iterdir())) == 1
    assert Kept().purge(age("1d")) == []
    assert len(Kept().purge(age("0m"))) == 2 and Kept().listing() == []
    assert len(list((kept_folder / "blobs").iterdir())) == 1      # a blob younger than an hour stays


def test_the_load_cache_rechecks_a_dat_folder(L, tmp_path):
    a = folder(tmp_path, "a", "one")
    GameDat(a).seal(L, alias="g/1")
    first = Ref(L.at(), "g/1").load()
    assert Ref(L.at(), "g/1").load() is first
    first.path.rename(tmp_path / "moved")
    again = Ref(L.at(), "g/1").load()
    assert again is not first and (again.path / "a.txt").read_text() == "one"


def test_a_kept_part_is_a_clone_where_the_filesystem_can(tmp_path, kept_folder):
    import shutil
    import sys

    from dvc_dat.ledger import store

    src = tmp_path / "big"
    src.mkdir()
    blob = src / "a.bin"
    gib = 1 << 30
    with open(blob, "wb") as f:
        block = os.urandom(1 << 20)
        for _ in range(gib >> 20):
            f.write(block)
    probe = tmp_path / "probe"
    if not store.clone(blob, probe):
        pytest.skip(f"no copy-on-write clone on this filesystem ({sys.platform})")
    probe.unlink()
    before, n = shutil.disk_usage(tmp_path).free, store.CLONES[0]
    d = Dat(src)
    d.seal(keep=True)
    assert store.CLONES[0] == n + 1
    assert before - shutil.disk_usage(tmp_path).free < gib // 4     # a clone costs (almost) no disk
    kept = next(p for p in (kept_folder / "blobs").iterdir() if p.stat().st_size == gib)
    with open(kept, "rb") as f:
        head = f.read(16)
    with open(blob, "r+b") as f:                                    # an in-place edit of the source
        f.write(b"\0" * 16)
    with open(kept, "rb") as f:
        assert f.read(16) == head != b"\0" * 16
