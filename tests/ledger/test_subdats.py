"""SVP 241: a dat in a dat is a repo in a repo. The subdat is out of its parent's bytes and hashes, seals with
the parent as a value of its own, named ``<parent>/<relpath>`` and reached by that name alone."""

import json
import shutil
import time
from pathlib import Path

import pytest

import dvc_dat.ledger.copying as copying
import dvc_dat.ledger.backends as backends_mod
from dvc_dat import Dat, DatManager, core, dat
from dvc_dat.ledger import Exists, Ledger, Ref, register_values
from dvc_dat.ledger.txn import declined_by
import backends
from ledger_kinds import NumberedDat
from test_backends import FolderValues, store


@pytest.fixture(autouse=True)
def world(tmp_path):
    before = core._default_manager
    Dat.manager = DatManager(dat_folders=[str(tmp_path / "data")])
    yield Dat.manager
    core._default_manager = before
    if before is not None:
        Dat.manager = before


def child(path: Path, text: str = "frames", name: str = "clip.bin") -> Dat:
    """A saved subdat at ``path``."""
    made = Dat.create({"dat": {"kwargs": {}}}, path=str(path))
    (made.path / name).write_text(text)
    made.save()
    return made


def parent(path: Path, result: str = '{"score": 1}', gallery: str = "frames") -> Dat:
    """A saved dat at ``path`` holding ``result.json`` and the subdat ``viz/``."""
    made = Dat.create({"dat": {"kwargs": {}}}, path=str(path))
    (made.path / "result.json").write_text(result)
    child(made.path / "viz", gallery)
    made.save()
    return made


def row(L, s, rel):
    return L.at()[s, f"db/subdat/{rel}"]


def test_a_subdat_is_out_of_both_hashes(tmp_path):
    a, b = parent(tmp_path / "a", gallery="one"), parent(tmp_path / "b", gallery="two and more")
    assert a.get_results()["dat"]["sha256"] == b.get_results()["dat"]["sha256"]
    assert sorted(a._manifest()) == sorted(b._manifest())
    assert not any(rel.startswith("viz/") for rel in a._manifest())
    assert Dat(a.path).hash == Dat(b.path).hash
    assert a.verify() and b.verify()


def test_a_plain_folder_stays_in_the_parent(tmp_path):
    """249: a folder of segments is no dat, so it stays in the manifest; a subdat's own folder holds its own."""
    a = parent(tmp_path / "a")
    (a.path / "segments").mkdir()
    (a.path / "segments" / "000.mp4").write_text("seg")
    (a.path / "other").mkdir()
    (a.path / "other" / "_spec_.yaml").write_text("dat: {}\n")      # a spec that names no kind is no dat
    assert "segments/000.mp4" in a._manifest() and "other/_spec_.yaml" in a._manifest()
    (a.path / "viz" / "segments").mkdir()
    (a.path / "viz" / "segments" / "000.mp4").write_text("seg")
    assert "segments/000.mp4" in Dat(a.path / "viz")._manifest()


def test_the_seal_writes_the_child_and_its_row(L, tmp_path):
    run = parent(tmp_path / "a")
    subject = run.seal(L, name="run/G1")
    ref = row(L, subject, "viz")
    assert isinstance(ref, Ref) and ref.hash == Dat(tmp_path / "a" / "viz").hash
    assert ref.aliases == ["run/G1/viz"]
    head = L.at()
    deps = [p for p, _o in head[ref.subject].items() if p.startswith("db/deps/ref:")]
    assert deps == [f"db/deps/ref:dvc_dat.core.Dat:{run.hash}"]
    assert head[ref.subject]["db/provenance"] == head[subject]["db/provenance"]


def test_one_transaction_and_a_refused_child_writes_nothing(L, tmp_path):
    run = parent(tmp_path / "a")
    opened = Dat.create({"dat": {"kwargs": {}}}, path=str(run.path / "open"))    # never saved
    before = L.at().id
    with pytest.raises(ValueError, match="open"):
        run.seal(L, name="run/G1")
    assert L.at().id == before and run.subject is None and not run.sealed
    shutil.rmtree(opened.path)
    run.seal(L, name="run/G1")
    assert L.at().id == before + 1


def test_a_child_seals_with_a_provenance_and_a_run_keeps_its_own(L, tmp_path):
    run = parent(tmp_path / "a")
    subject = run.seal(L, name="run/G1", provenance="hand")
    assert L.at()[row(L, subject, "viz").subject]["db/provenance"] == "hand"


def test_skip_declines_and_stores_no_byte(L, tmp_path):
    run = parent(tmp_path / "a", gallery="DECLINED BYTES")
    clip = Dat(run.path / "viz")._manifest()["clip.bin"]
    subject = run.seal(L, name="run/G1", skip=("viz",))
    assert row(L, subject, "viz") == "declined"
    assert not L._store.art.exists(clip)
    assert (tmp_path / "a" / "viz" / "clip.bin").read_text() == "DECLINED BYTES"     # on disk, outside every hash
    assert Ref(L.at(), "run/G1/viz").hash is None


@pytest.mark.parametrize("rel,entry,hit", [
    ("viz", "viz", True), ("run/viz", "viz", True), ("run/viz", "run/viz", True), ("viz", "run/viz", False),
    ("galleries/a", "galleries", True), ("galleries/deep/a", "galleries", True), ("x/galleries/a", "galleries", True),
    ("myviz", "viz", False), ("viz/inner", "viz", True), ("a/b", "b/a", False)])
def test_skip_entries_are_path_suffixes(rel, entry, hit):
    assert declined_by(rel, (entry,)) is hit


def test_a_plain_folder_named_in_skip_declines_every_subdat_under_it(L, tmp_path):
    run = parent(tmp_path / "a")
    child(run.path / "galleries" / "a", "aa")
    child(run.path / "galleries" / "deep" / "b", "bb")
    subject = run.seal(L, name="run/G1", skip=["galleries"])
    assert row(L, subject, "galleries/a") == row(L, subject, "galleries/deep/b") == "declined"
    assert isinstance(row(L, subject, "viz"), Ref)


def test_a_grandchild_seals_under_its_child_and_skip_reaches_it(L, tmp_path):
    run = parent(tmp_path / "a")
    child(run.path / "viz" / "thumbs", "tt")
    child(run.path / "other", "oo")
    child(run.path / "other" / "thumbs", "tt2")
    subject = run.seal(L, name="run/G1", skip=("other/thumbs",))
    viz = row(L, subject, "viz")
    assert L.at()[viz.subject, "db/subdat/thumbs"].aliases == ["run/G1/viz/thumbs"]
    assert L.at()[row(L, subject, "other").subject, "db/subdat/thumbs"] == "declined"


def test_a_class_default_and_skip_empty(L, tmp_path):
    a, b, c = parent(tmp_path / "a"), parent(tmp_path / "b", gallery="b"), parent(tmp_path / "c", gallery="c")
    child(c.path / "extra", "e")
    for d in (a, b, c):
        d.__class__ = type("Skipping", (Dat,), {"skip_subdats": ("viz",), "__module__": __name__})
    subject = a.seal(L)                     # the default: the class's
    assert row(L, subject, "viz") == "declined"
    subject = b.seal(L, skip=())            # declines nothing
    assert isinstance(row(L, subject, "viz"), Ref)
    subject = c.seal(L, skip=("extra",))    # on top of the class's
    assert row(L, subject, "viz") == row(L, subject, "extra") == "declined"


def test_skip_is_a_ledger_write_and_never_a_bare_str(L, tmp_path):
    run = parent(tmp_path / "a")
    with pytest.raises(TypeError, match="skip="):
        run.seal(skip=("viz",))
    with pytest.raises(TypeError, match="a tuple or list"):
        run.seal(L, skip="viz")


def test_a_run_folder_seals_by_default(L, tmp_path):
    made = Dat.manager.run({"dat": {"do": "ledger_kinds.build_table", "name": "t/1", "kwargs": {"n": 2, "start": 1}}})
    assert not any(rel.startswith("run/") for rel in made._manifest())
    subject = made.seal(L, name="table/1")
    ref = row(L, subject, "run")
    assert ref.aliases == ["table/1/run"]
    L._values.clear()
    back = L.at().load("table/1/run")
    assert back.get_results()["dat"]["content"] == made.get_results()["dat"]["sha256"]


def test_a_rerun_of_a_recipe_hashes_the_same_though_its_run_differs():
    spec = {"dat": {"do": "ledger_kinds.build_table", "kwargs": {"n": 2, "start": 1}}}
    a, b = (Dat.manager.run({"dat": {**spec["dat"], "name": n}}) for n in ("t/a", "t/b"))
    assert a.get_results()["dat"]["sha256"] == b.get_results()["dat"]["sha256"]
    assert a.run.get_results()["dat"]["run_at"] and a.run.path != b.run.path


def test_a_child_made_by_a_nested_run_is_no_dependency(tmp_path):
    outer = Dat.manager.run({"dat": {"do": "ledger_kinds.makes_a_subdat", "name": "t/outer"}})
    inner = outer.path / "viz"
    assert (inner / "table.csv").exists()
    assert outer.get_results()["dat"].get("dependencies", {}) == {}


def test_a_ledger_run_seals_its_subdats_under_its_trace(coded):
    spec = {"dat": {"do": "ledger_kinds.makes_a_subdat"}}
    v = coded.at().run(spec, path="t/outer")
    head = coded.at()
    viz = head[v.subject, "db/subdat/viz"]
    assert head[viz.subject]["db/provenance"] == head[v.subject]["db/provenance"]
    assert viz.aliases == ["t/outer/viz"] and head.load("t/outer/viz").hash == viz.hash


def test_the_kept_seal_path(L, tmp_path):
    run = parent(tmp_path / "a")
    run.seal()
    assert Ref(L.at(), "run/G1").hash is None
    subject = run.seal(L, name="run/G1", skip=())
    assert row(L, subject, "viz").aliases == ["run/G1/viz"]


def test_a_kept_child_keeps_what_it_was_sealed_with(L, tmp_path):
    run = parent(tmp_path / "a")
    kept = Dat(run.path / "viz")
    kept.seal(provenance="drawn")
    subject = run.seal(L, name="run/G1")
    viz = row(L, subject, "viz")
    assert L.at()[viz.subject]["db/provenance"] == "drawn"
    assert not [p for p in L.at()[viz.subject] if p.startswith("db/deps/ref:")]
    assert Dat.sealed_at_path(run.path) is None


def test_a_kept_child_sealed_against_its_kept_parent_saves_with_it(L, tmp_path):
    run = parent(tmp_path / "a")
    run.seal()
    viz = Dat(run.path / "viz")
    viz.seal(deps=[run])
    subject = run.seal(L, name="run/G1")
    ref = row(L, subject, "viz")
    assert f"db/deps/ref:dvc_dat.core.Dat:{run.hash}" in L.at()[ref.subject]


def test_reached_by_its_alias_alone(L, tmp_path):
    run = parent(tmp_path / "a", gallery="GALLERY")
    subject = run.seal(L, name="run/G1")
    viz_subject = row(L, subject, "viz").subject
    L._values.clear()
    by_name = L.at().load("run/G1")
    by_subject = L.at().load(subject)
    for loaded in (by_name, by_subject):
        assert not hasattr(loaded, "subdats") and not hasattr(loaded, "viz")
    viz = L.at().load("run/G1/viz")
    assert viz.subject == viz_subject and (viz.path / "clip.bin").read_text() == "GALLERY"
    assert viz.path == by_name.path / "viz"                 # placed inside the parent's folder, which prunes it
    assert Dat(by_name.path).hash == run.hash


def test_a_child_placed_first_survives_the_parents_load(L, tmp_path):
    run = parent(tmp_path / "a")
    run.seal(L, name="run/G1")
    shutil.rmtree(L._store.art.root / "dats")
    L._values.clear()
    viz = L.at().load("run/G1/viz")
    back = L.at().load("run/G1")
    assert (back.path / "result.json").exists() and (viz.path / "clip.bin").exists()
    L._values.clear()
    assert L.at().load("run/G1").path == back.path and (viz.path / "clip.bin").exists()


def test_a_re_seal_re_points_the_row(L, tmp_path):
    a, b = parent(tmp_path / "a", gallery="one"), parent(tmp_path / "b", gallery="two")
    first = a.seal(L, name="run/G1")
    rev_a = L.at().id
    second = b.seal(L, name="run/G1")
    assert first == second
    assert row(L, first, "viz").hash == Dat(tmp_path / "b" / "viz").hash
    assert L.at(rev_a)[first, "db/subdat/viz"].hash == Dat(tmp_path / "a" / "viz").hash
    assert len(L.at().history(first, "db/subdat/viz")) == 2
    assert Ref(L.at(), "run/G1/viz").hash == Dat(tmp_path / "b" / "viz").hash


def test_a_child_added_after_the_fact(L, tmp_path):
    run = parent(tmp_path / "a")
    subject = run.seal(L, name="run/G1", skip=("viz",))
    late = Dat(tmp_path / "a" / "viz")
    with L.transaction(by="viz") as t:
        late.seal(t, name="run/G1/viz", deps=[Ref(L.at(), "run/G1")])
        t.add(subject, "db/subdat/viz", late)
    assert row(L, subject, "viz").hash == late.hash and row(L, subject, "viz").aliases == ["run/G1/viz"]


def test_a_run_is_reached_by_its_alias_and_is_not_placed_by_the_parents_load(coded):
    coded.at().run({"dat": {"do": "ledger_kinds.build_table", "kwargs": {"n": 2, "start": 1}}}, path="t/x")
    shutil.rmtree(coded._store.art.root / "dats")
    coded._values.clear()
    back = coded.at().load("t/x")
    assert not (back.path / "run").exists() and back.run is None
    assert coded.at().load("t/x/run").path == back.path / "run"
    assert Dat.get(coded.at().load("t/x/run").get_results(), "dat.run_at")


def test_a_seal_predicate_stays_refused_beside_the_row(L, tmp_path):
    subject = parent(tmp_path / "a").seal(L, name="run/G1")
    with pytest.raises(Exists):
        with L.transaction(by="t") as t:
            t.add(subject, "db/fn", "x")


def test_a_rename_moves_the_alias_tree(L, tmp_path):
    run = parent(tmp_path / "a")
    child(run.path / "viz" / "thumbs", "tt")
    run.seal(L, name="run/G1")
    viz = Ref(L.at(), "run/G1/viz").hash
    rev = L.at().id
    run.name = "run/G2"
    head = L.at()
    assert head.id == rev + 1
    assert Ref(head, "run/G2/viz").hash == viz and Ref(head, "run/G2/viz/thumbs").hash
    assert Ref(head, "run/G1/viz").hash is None and Ref(head, "run/G1").hash is None
    assert head.load("run/G2/viz").hash == viz


def test_naming_an_unnamed_parent_names_its_tree_and_unnaming_unnames_it(L, tmp_path):
    run = parent(tmp_path / "a")
    child(run.path / "viz" / "thumbs", "tt")
    run.seal(L)
    run.name = "run/G1"
    assert Ref(L.at(), "run/G1/viz").hash and Ref(L.at(), "run/G1/viz/thumbs").hash
    run.name = None
    assert Ref(L.at(), "run/G1/viz").hash is None


# -- copy follows the subdats (SVP 252) ---------------------------------------------------------------------------

def published(path: Path) -> Dat:
    """A saved dat at ``path`` holding ``result.json``, a ``run/`` subdat and the ``viz/`` subdat."""
    made = parent(path, gallery="GALLERY")
    child(made.path / "run", "LOG", "log.txt")
    return made


def dest_of(backend, tmp_path):
    return backends.make(backend, tmp_path / "dest")


def held(L, subject):
    return bool(L.at()._held(subject, "db/value"))


def test_a_copy_brings_the_dependent_and_refers_to_the_run_on_its_ledger(L, backend, tmp_path):
    """252 § Success Criteria: the default skip gives one revision holding the value and the dependent, and a
    cross-ledger reference for the run; the parent's hash is unchanged by what happens to its subdats."""
    made = published(tmp_path / "a")
    subject = made.seal(L, name="res/G1")
    run_ref, viz = row(L, subject, "run"), row(L, subject, "viz")
    source = L.at().id
    dest = dest_of(backend, tmp_path)
    before = dest.at().id
    with dest.transaction(by="t") as t:
        assert t.copy(made, safe=False) == [subject]
    top = dest.at()
    assert top.id == before + 1
    assert top._held(subject, "db/value")[0].rev == top._held(viz.subject, "db/value")[0].rev == top.id
    assert dest._store.art.exists(viz.hash) and top.load("res/G1/viz").hash == viz.hash
    assert not held(dest, run_ref.subject) and not dest._store.art.exists(run_ref.hash)
    assert row(dest, subject, "run") == f"{L._store.name}@{source}:{run_ref.subject}"
    at, _, rest = row(dest, subject, "run").partition(":")
    assert L.at(int(at.rpartition("@")[2])).load(rest).hash == run_ref.hash     # the run, read on its own ledger
    if backend == "sqlite":     # the pg cases' ledgers are schemas of one database, so they share one name
        assert dat.load(row(dest, subject, "run")).hash == run_ref.hash
    assert top.load("res/G1").hash == made.hash == L.at().load("res/G1").hash


def test_a_copy_that_fails_midway_leaves_the_destination_at_its_prior_revision(L, backend, tmp_path, monkeypatch):
    made = published(tmp_path / "a")
    subject = made.seal(L, name="res/G1")
    viz = row(L, subject, "viz")
    dest = dest_of(backend, tmp_path)
    before = dest.at().id
    real, calls = copying._write, []

    def second_fails(t, item):
        calls.append(item.subject)
        if len(calls) == 2:
            raise OSError("the store went away")
        real(t, item)

    monkeypatch.setattr(copying, "_write", second_fails)
    with pytest.raises(OSError, match="went away"):
        with dest.transaction(by="t") as t:
            t.copy(made, safe=False)
    with pytest.raises(OSError, match="went away"):
        calls.clear()
        dest.at().copy(made, safe=False)
    assert dest.at().id == before
    assert not held(dest, subject) and not held(dest, viz.subject)
    assert not dest._store.art.exists(made.hash) and not dest._store.art.exists(viz.hash)


def test_a_subdat_of_a_subdat_is_followed_and_skip_reaches_it(L, backend, tmp_path):
    made = published(tmp_path / "a")
    child(made.path / "viz" / "thumbs", "THUMBS")
    subject = made.seal(L, name="res/G1")
    viz = row(L, subject, "viz")
    thumbs = L.at()[viz.subject, "db/subdat/thumbs"]
    dest = dest_of(backend, tmp_path)
    dest.at().copy(made, safe=False)
    assert dest.at().load("res/G1/viz/thumbs").hash == thumbs.hash
    again = dest_of(backend, tmp_path / "again")
    again.at().copy(made, safe=False, skip=("viz/thumbs",))
    assert held(again, viz.subject) and not held(again, thumbs.subject)
    assert again.at()[viz.subject, "db/subdat/thumbs"] == f"{L._store.name}@{L.at().id}:{thumbs.subject}"


def test_skip_empty_copies_everything_and_skip_adds_to_the_run(L, backend, tmp_path):
    made = published(tmp_path / "a")
    subject = made.seal(L, name="res/G1")
    run_ref, viz = row(L, subject, "run"), row(L, subject, "viz")
    every = dest_of(backend, tmp_path / "every")
    every.at().copy(made, safe=False, skip=())
    assert every.at().load("res/G1/run").hash == run_ref.hash and every.at().load("res/G1/viz").hash == viz.hash
    assert isinstance(row(every, subject, "run"), Ref)
    neither = dest_of(backend, tmp_path / "neither")
    neither.at().copy(made, safe=False, skip=("viz",))
    assert held(neither, subject) and not held(neither, run_ref.subject) and not held(neither, viz.subject)
    assert row(neither, subject, "viz") == f"{L._store.name}@{L.at().id}:{viz.subject}"
    with pytest.raises(TypeError, match="a tuple or list"):
        neither.at().copy(made, safe=False, skip="viz")


def test_deep_does_not_override_skip_and_a_declined_row_travels_as_it_is(L, backend, tmp_path):
    made = published(tmp_path / "a")
    child(made.path / "extra", "EXTRA")
    subject = made.seal(L, name="res/G1", skip=("extra",))
    run_ref = row(L, subject, "run")
    dest = dest_of(backend, tmp_path)
    dest.at().copy(made, deep=True, safe=False)
    assert not held(dest, run_ref.subject) and row(dest, subject, "extra") == "declined"


CLIP_WORDS = 64 * 1024
CLIP_BYTES = 4 * CLIP_WORDS


def counted(L, tmp_path, monkeypatch):
    monkeypatch.setattr(backends_mod, "_VALUES", dict(backends_mod._VALUES))
    monkeypatch.setattr(backends_mod, "_MADE", {})
    made = {}

    def make(uri):
        made["gcp"] = FolderValues(tmp_path / "gcp")
        return made["gcp"]
    register_values("bucket", make)
    store(L, "gcp")
    return made


def five_hundred(tmp_path, base, *, distinct=False):
    """500 folders: ``result.json`` (one text, or its own), a pred ``i``, and a ``viz/`` subdat of 256 KiB of its own."""
    out = []
    for i in range(500):
        folder = tmp_path / base / f"d{i}"
        folder.mkdir(parents=True)
        (folder / "result.json").write_text(json.dumps({"score": i if distinct else 1}))
        made = Dat.create({"dat": {"kwargs": {}}}, path=str(folder / "viz"))
        (made.path / "clip.bin").write_bytes(i.to_bytes(4, "big") * CLIP_WORDS)
        made.save()
        v = NumberedDat(folder)
        v.preds["i"] = i
        out.append(v)
    return out


def blobs(root: Path):
    return [p for p in root.rglob("*") if p.is_file()]


def test_500_parents_with_one_result_are_one_hash_and_500_subjects(L, tmp_path):
    dats = five_hundred(tmp_path, "same")
    with L.transaction(by="t") as t:
        for i, v in enumerate(dats):
            v.seal(t, name=f"run/{i}")
    assert len({v.hash for v in dats}) == 1 and len({v.subject for v in dats}) == 500
    # the parents share a manifest and a result.json; each child a manifest, a clip and a _result_.yaml; one _spec_.yaml
    assert len(blobs(L._store.art.root / "sha256")) == 2 + 3 * 500 + 1


def test_500_parents_load_for_two_fetches_each_and_no_child_byte(L, tmp_path, monkeypatch):
    remotes = counted(L, tmp_path, monkeypatch)
    dats = five_hundred(tmp_path, "many", distinct=True)
    with L.transaction(by="t") as t:
        for i, v in enumerate(dats):
            v.seal(t, name=f"run/{i}")
    gcp = remotes["gcp"]
    shutil.rmtree(L._store.art.root, ignore_errors=True)
    L._values.clear()
    gcp.pulls.clear()
    head = L.at()
    t0 = time.monotonic()
    loaded = [head.load(f"run/{i}") for i in range(500)]
    took = time.monotonic() - t0
    assert len(gcp.pulls) == 1000 and took < 5.0                                 # 0.6 s measured alone
    assert sum(gcp._p(h).stat().st_size for h in gcp.pulls) < 500 * 1024         # no clip among them
    assert not any((v.path / "viz").exists() for v in loaded)
    gcp.pulls.clear()
    viz = head.load("run/7/viz")
    assert (viz.path / "clip.bin").stat().st_size == CLIP_BYTES and viz.path == loaded[7].path / "viz"
    assert CLIP_BYTES <= sum(gcp._p(h).stat().st_size for h in gcp.pulls) < CLIP_BYTES + 4096
    print(f"500 parent loads with every fetch a miss: {took:.2f} s")


def test_500_parents_with_the_gallery_declined(L, tmp_path):
    dats = five_hundred(tmp_path, "skip")
    with L.transaction(by="t") as t:
        for i, v in enumerate(dats):
            v.seal(t, name=f"run/{i}", skip=("viz",))
    stored = blobs(L._store.art.root / "sha256")
    assert len(stored) == 2 and sum(b.stat().st_size for b in stored) < 1024 * 1024
    assert sum(L.at().get(v.subject, "db/subdat/viz") == "declined" for v in dats) == 500
