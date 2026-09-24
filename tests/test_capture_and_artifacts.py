"""Artifacts and the store (`save`, `load` by name or URN, the index, `type=`),
dependencies by capture (`recording`, `record_dependency`, `dat.dependencies`),
and `dat.standing` (2.14)."""
import hashlib
import os
import sys
import threading
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dvc_dat import Dat, DatManager  # noqa: E402
from dvc_dat.core import ART_FILE, DAT_CONFIG_FILE, INDEX_FILE, RESULT_YAML  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def m(tmp_path):
    return DatManager(dat_folders=[str(tmp_path / "dats")], art_folder=str(tmp_path / "art"))


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "G1.mp4"
    path.write_bytes(b"frames")
    return path


@pytest.fixture
def folder(tmp_path):
    path = tmp_path / "assets"
    (path / "sub").mkdir(parents=True)
    (path / "a.txt").write_text("a")
    (path / "sub" / "b.txt").write_text("b")
    return path


@pytest.fixture
def clean_code(monkeypatch):
    """Runs count as clean committed code, whatever the checkout holds."""
    import dvc_dat.core as core
    monkeypatch.setattr(core, "_code_of", lambda fn: {
        "branch": "main", "commit": "c", "dirty": False})


def stored_results(dat):
    return yaml.safe_load(Path(dat.get_path(), RESULT_YAML).read_text())


def sidecar(tmp_path, rel):
    return yaml.safe_load((tmp_path / "art" / rel / ART_FILE).read_text())


def index(tmp_path):
    return yaml.safe_load((tmp_path / "art" / INDEX_FILE).read_text())["entries"]


class VideoClip:
    def __init__(self, path):
        self.path = path


class TestArtifacts:
    def test_a_file_round_trips_with_its_hash(self, m, clip, tmp_path):
        urn = m.save(clip, name="video/G1")
        assert urn == "sha256:" + sha(b"frames")
        home = tmp_path / "art" / "video" / "G1"
        card = sidecar(tmp_path, "video/G1")
        assert card["names"] == ["video/G1"] and card["type"] is None
        assert card["payload"] == "G1.mp4" and card["sha256"] == urn and card["size"] == 6
        assert card["saved_at"]
        loaded = m.load("video/G1")
        assert loaded == Path(os.path.realpath(home), "G1.mp4")   # no type: a Path
        assert loaded.read_bytes() == b"frames"
        assert m.load(urn) == loaded
        assert m.exists("video/G1") and m.exists(urn) and not m.exists("video/G2")

    def test_a_folder_round_trips_with_its_hash(self, m, folder):
        urn = m.save(folder, name="assets/lock")
        lines = sorted([f"a.txt\0{sha(b'a')}\n", f"sub/b.txt\0{sha(b'b')}\n"])
        assert urn == "sha256:" + sha("".join(lines).encode())
        loaded = m.load("assets/lock")
        assert (loaded / "sub" / "b.txt").read_text() == "b"
        assert yaml.safe_load((loaded / ART_FILE).read_text())["payload"] == "."

    def test_a_name_is_written_once(self, m, clip, tmp_path):
        m.save(clip, name="video/G1")
        other = tmp_path / "other.mp4"
        other.write_bytes(b"other")
        with pytest.raises(FileExistsError):
            m.save(other, name="video/G1")

    @pytest.mark.parametrize("name", ["/G1", "video/", "v/../../x", "sha256:ab", "a//b"])
    def test_a_malformed_name_is_refused(self, m, clip, name):
        with pytest.raises(ValueError):
            m.save(clip, name=name)

    def test_a_name_inside_an_artifact_is_refused(self, m, clip, tmp_path):
        m.save(clip, name="video/G1")
        other = tmp_path / "x.bin"
        other.write_bytes(b"x")
        with pytest.raises(ValueError, match="inside the artifact 'video/G1'"):
            m.save(other, name="video/G1/more")

    def test_the_2_13_call_shape_says_what_moved(self, m, clip):
        with pytest.raises(TypeError, match="second argument is the type"):
            m.save(clip, "art:video/G1")
        with pytest.raises(TypeError, match="second argument is the type"):
            m.save(clip, "video/G1")

    def test_a_missing_artifact_names_itself(self, m):
        with pytest.raises(FileNotFoundError, match="art:video/nope"):
            m.load("art:video/nope")
        with pytest.raises(KeyError, match="not in the index"):
            m.load("sha256:" + "0" * 64)

    def test_the_art_folder_can_be_given(self, tmp_path, clip):
        m = DatManager(dat_folders=[str(tmp_path / "dats")], art_folder=str(tmp_path / "store"))
        m.save(clip, name="video/G1")
        assert (tmp_path / "store" / "video" / "G1" / ART_FILE).exists()
        assert (tmp_path / "store" / INDEX_FILE).exists()

    def test_no_art_folder_means_no_artifacts(self, tmp_path, clip):
        m = DatManager(dat_folders=[str(tmp_path / "dats")])
        with pytest.raises(RuntimeError, match="no art_folder"):
            m.save(clip, name="video/G1")
        with pytest.raises(RuntimeError, match="no art_folder"):
            m.load("art:video/G1")

    @pytest.mark.parametrize("dats, art", [("data", "data/art"), ("data/runs", "data"),
                                           ("data", "data")])
    def test_the_two_folders_never_nest(self, tmp_path, dats, art):
        with pytest.raises(ValueError, match="nest"):
            DatManager(dat_folders=[str(tmp_path / "other"), str(tmp_path / dats)],
                       art_folder=str(tmp_path / art))
        (tmp_path / DAT_CONFIG_FILE).write_text(f"dat_folders: {dats}\nart_folder: {art}\n")
        with pytest.raises(ValueError, match="nest"):
            DatManager.load_dat_config(tmp_path)

    def test_load_dat_config_puts_art_beside_data(self, tmp_path):
        m = DatManager.load_dat_config(tmp_path)
        root = os.path.realpath(tmp_path)
        assert m._dat_folders == [os.path.join(root, "data")]
        assert m._art_folder == os.path.join(root, "art")
        assert m._index_file == os.path.join(root, "art", INDEX_FILE)

    def test_load_dat_config_reads_art_folder(self, tmp_path, clip, monkeypatch):
        (tmp_path / DAT_CONFIG_FILE).write_text("dat_folders: dats\nart_folder: blobs\n")
        m = DatManager.load_dat_config(tmp_path)
        m.save(clip, name="video/G1")
        assert (tmp_path / "blobs" / "video" / "G1" / ART_FILE).exists()
        monkeypatch.setenv("DAT_ART_FOLDER", str(tmp_path / "env"))
        assert DatManager.load_dat_config(tmp_path)._art_folder == os.path.realpath(tmp_path / "env")


class TestType:
    def test_a_class_is_recorded_by_its_dotted_name_and_built_at_load(self, m, clip, tmp_path):
        m.save(clip, VideoClip, "video/G1")
        assert sidecar(tmp_path, "video/G1")["type"] == m.do.name_of(VideoClip)
        video = m.load("video/G1")
        assert isinstance(video, VideoClip) and video.path.name == "G1.mp4"

    def test_a_mounted_factory_is_named_by_its_mount(self, m, folder):
        m.do.mount(value=lambda path: sorted(os.listdir(path)), at="listing.of")
        m.save(folder, type="listing.of", name="assets/lock")
        assert m.load("assets/lock") == [ART_FILE, "a.txt", "sub"]

    def test_a_factory_that_cannot_be_imported_says_to_mount_it(self, m, clip):
        with pytest.raises(TypeError, match="mount it"):
            m.save(clip, lambda path: path, "video/G1")

    def test_a_type_name_that_does_not_resolve_is_refused(self, m, clip):
        with pytest.raises(ValueError, match="does not resolve"):
            m.save(clip, "no.such.factory", "video/G1")

    def test_load_path_builds_nothing(self, m, clip):
        m.save(clip, VideoClip, "video/G1")
        assert m.load_path("video/G1").name == "G1.mp4"


class TestNoNameAndDedupe:
    def test_no_name_stores_under_the_urn_only(self, m, clip, tmp_path):
        urn = m.save(clip)
        hexed = urn[len("sha256:"):]
        assert (tmp_path / "art" / "sha256" / hexed / "G1.mp4").read_bytes() == b"frames"
        assert sidecar(tmp_path, f"sha256/{hexed}")["names"] == []
        assert m.load(urn).read_bytes() == b"frames"
        assert index(tmp_path) == {urn: {"art": f"sha256/{hexed}"}}

    def test_a_second_name_for_stored_bytes_copies_nothing(self, m, clip, tmp_path):
        urn = m.save(clip, name="video/G1")
        assert m.save(clip, name="video/G1-again") == urn
        assert not (tmp_path / "art" / "video" / "G1-again").exists()
        assert m.load("video/G1-again") == m.load("video/G1")
        assert sidecar(tmp_path, "video/G1")["names"] == ["video/G1", "video/G1-again"]
        assert index(tmp_path)["video/G1-again"] == {"art": "video/G1"}
        assert m.save(clip) == urn                     # unnamed: nothing new
        assert not (tmp_path / "art" / "sha256").exists()

    def test_an_equal_hash_with_a_different_size_is_refused(self, m, clip, tmp_path):
        m.save(clip, name="video/G1")
        card_path = tmp_path / "art" / "video" / "G1" / ART_FILE
        card = yaml.safe_load(card_path.read_text())
        card["size"] = 999
        card_path.write_text(yaml.safe_dump(card))
        with pytest.raises(ValueError, match="999 bytes"):
            m.save(clip, name="video/G1-again")

    def test_stored_bytes_keep_their_type(self, m, clip):
        m.save(clip, VideoClip, "video/G1")
        with pytest.raises(ValueError, match="with type"):
            m.save(clip, "os.path.basename", "video/G1-as-name")
        assert isinstance(m.load(m.save(clip, name="video/G1-b")), VideoClip)


class TestIndex:
    def test_the_index_keys_names_and_urns_and_is_written_whole(self, m, clip, tmp_path):
        urn = m.save(clip, name="video/G1")
        dat = m.create({"dat": {}}, path="d")
        dat.save()
        assert index(tmp_path) == {"video/G1": {"art": "video/G1"},
                                   urn: {"art": "video/G1"},
                                   dat._sha256(): {"dat": "d"}}
        assert not [p for p in (tmp_path / "art").iterdir() if p.name.endswith(".tmp")]

    def test_index_moves_it(self, tmp_path, clip):
        (tmp_path / DAT_CONFIG_FILE).write_text("index: meta/where.yaml\n")
        m = DatManager.load_dat_config(tmp_path)
        m.save(clip, name="video/G1")
        assert (tmp_path / "meta" / "where.yaml").exists()
        other = DatManager(dat_folders=[str(tmp_path / "d")], index=str(tmp_path / "i.yaml"))
        other.create({"dat": {}}, path="x").save()
        assert (tmp_path / "i.yaml").exists()

    def test_reindex_rebuilds_it_from_the_folders(self, m, clip, tmp_path):
        urn = m.save(clip, name="video/G1")
        m.save(clip, name="video/G1-again")
        dat = m.create({"dat": {}}, path="d")
        dat.save()
        before = index(tmp_path)
        (tmp_path / "art" / INDEX_FILE).unlink()
        assert m.reindex() == 4
        assert index(tmp_path) == before and m.load(urn).name == "G1.mp4"

    def test_a_dat_answers_to_its_urn_until_it_is_saved_again(self, m):
        dat = m.create({"dat": {"standing": "rolling"}}, path="G1")
        dat.save()
        first = dat._sha256()
        assert m.load(first) is dat
        Path(dat.get_path(), "labels.txt").write_text("fixed")
        dat.save()
        assert m.load(dat._sha256()) is dat
        with pytest.raises(KeyError):
            m.load(first)

    def test_delete_and_move_keep_the_index_true(self, m, tmp_path):
        dat = m.create({"dat": {}}, path="a")
        dat.save()
        urn = dat._sha256()
        moved = dat.move("b")
        assert index(tmp_path)[urn] == {"dat": "b"}
        moved.delete()
        assert urn not in index(tmp_path)


class TestOneNamespace:
    def test_a_dat_name_is_not_an_artifact_name(self, m, clip):
        m.create({"dat": {}}, path="games/G1")
        with pytest.raises(FileExistsError, match="a dat's name"):
            m.save(clip, name="games/G1")

    def test_an_artifact_name_is_not_a_dat_name(self, m, clip):
        m.save(clip, name="games/G1")
        with pytest.raises(FileExistsError, match="an artifact's name"):
            m.create({"dat": {}}, path="games/G1")

    def test_a_name_both_hold_is_refused_at_load(self, m, clip, tmp_path):
        m.save(clip, name="games/G1")
        (tmp_path / "dats" / "games" / "G1").mkdir(parents=True)
        (tmp_path / "dats" / "games" / "G1" / "_spec_.yaml").write_text("dat: {}\n")
        with pytest.raises(ValueError, match="both a dat and an artifact"):
            m.load("games/G1")


class TestLegacyStore:
    @pytest.fixture
    def old(self, tmp_path):
        """An artifact as 2.13 left it: `art:` name, `kind`, no index."""
        home = tmp_path / "art" / "video" / "G1"
        home.mkdir(parents=True)
        (home / "G1.mp4").write_bytes(b"frames")
        (home / ART_FILE).write_text(yaml.safe_dump({
            "kind": "video", "name": "art:video/G1", "payload": "G1.mp4",
            "sha256": "sha256:" + sha(b"frames"), "saved_at": "2026-09-24T00:00:00+00:00"}))
        return DatManager(dat_folders=[str(tmp_path / "dats")], art_folder=str(tmp_path / "art"))

    def test_an_art_name_loads_with_the_prefix_stripped(self, old):
        assert old.load("art:video/G1").read_bytes() == b"frames"
        assert old.load("video/G1") == old.load("art:video/G1")
        assert old.standing("art:video/G1") == "referenceable"

    def test_reindex_gives_it_its_urn(self, old):
        old.reindex()
        assert old.load("sha256:" + sha(b"frames")).name == "G1.mp4"

    def test_a_legacy_name_in_a_map_counts_as_an_artifact(self, old):
        dat = old.create({"dat": {}}, path="d")
        with old.recording(dat):
            old.record_dependency("art:video/G1", "sha256:" + sha(b"frames"))
        dat.save()
        assert stored_results(dat)["dat"]["standing"] == "referenceable"


def uses_both(dat, prev):
    dat.manager.load(prev)
    dat.manager.load("video/G1")
    dat.save()
    return "ran"


def outer(dat):
    dat.manager.do({"dat": {"do": "inner_fn", "name": "inner"}})
    dat.manager.load("video/G1")
    dat.save()


def inner_fn(dat):
    dat.manager.load("prev")
    dat.save()


class TestCapture:
    @pytest.fixture
    def world(self, m, clip):
        m.do.mount(value=uses_both, at="uses_both")
        m.do.mount(value=outer, at="outer")
        m.do.mount(value=inner_fn, at="inner_fn")
        self.digest = m.save(clip, name="video/G1")
        m.create({"dat": {}}, path="prev").save()
        return m

    def test_a_runs_loads_land_in_its_dependencies(self, world):
        dat = world.create({"dat": {"do": "uses_both", "kwargs": {"prev": "prev"}}},
                           path="run")
        assert world.execute(dat) == "ran"
        deps = stored_results(dat)["dat"]["dependencies"]
        assert deps == {"prev": world.load("prev").get_results()["dat"]["sha256"],
                        "video/G1": self.digest}

    def test_a_load_by_urn_is_recorded_by_the_urn(self, world):
        dat = world.create({"dat": {}}, path="by_urn")
        with world.recording(dat):
            world.load(self.digest)
        assert dat.get_results()["dat"]["dependencies"] == {self.digest: self.digest}

    def test_a_run_with_no_loads_says_so(self, world):
        world.do.mount(value=lambda dat: dat.save(), at="quiet")
        dat = world.create({"dat": {"do": "quiet"}}, path="quiet_run")
        world.execute(dat)
        assert stored_results(dat)["dat"]["dependencies"] == {}

    def test_a_nested_run_records_its_own_and_appears_once_outside(self, world):
        dat = world.create({"dat": {"do": "outer"}}, path="outer_run")
        world.execute(dat)
        inner = world.load("inner")
        assert stored_results(dat)["dat"]["dependencies"] == \
            {"inner": inner.get_results()["dat"]["sha256"], "video/G1": self.digest}
        assert stored_results(inner)["dat"]["dependencies"] == \
            {"prev": world.load("prev").get_results()["dat"]["sha256"]}

    def test_recording_by_hand(self, world):
        dat = world.create({"dat": {}}, path="builder")
        with world.recording(dat):
            world.load("video/G1")
            world.record_dependency("https://example.com/weights", "sha256:w")
        assert dat.get_results()["dat"]["dependencies"] == {
            "video/G1": self.digest, "https://example.com/weights": "sha256:w"}
        world.load("prev")                          # outside: recorded nowhere
        assert "prev" not in dat.get_results()["dat"]["dependencies"]

    def test_record_dependency_outside_a_recording_raises(self, world):
        with pytest.raises(RuntimeError, match="no dat is recording"):
            world.record_dependency("x")

    def test_a_save_inside_a_run_is_recorded(self, world, tmp_path):
        out = tmp_path / "out.bin"
        out.write_bytes(b"out")
        dat = world.create({"dat": {}}, path="saver")
        with world.recording(dat):
            digest = world.save(out, name="blob/out")
            unnamed = world.save(tmp_path / "G1.mp4")
        assert dat.get_results()["dat"]["dependencies"] == {"blob/out": digest,
                                                             unnamed: unnamed}

    def test_a_wrapping_subclass_does_not_record_a_dat_into_itself(self, clip, tmp_path):
        class Store(DatManager):
            def execute(self, dat):
                with self.recording(dat):
                    return super().execute(dat)
        m = Store(dat_folders=[str(tmp_path / "dats")], art_folder=str(tmp_path / "art"))
        m.do.mount(value=lambda dat: dat.save(), at="quiet")
        dat = m.create({"dat": {"do": "quiet"}}, path="wrapped")
        m.execute(dat)
        assert stored_results(dat)["dat"]["dependencies"] == {}

    def test_two_threads_recording_at_once_do_not_mix(self, world):
        a = world.create({"dat": {}}, path="thread_a")
        b = world.create({"dat": {}}, path="thread_b")
        barrier = threading.Barrier(2)

        def work(dat, name):
            with world.recording(dat):
                barrier.wait()
                world.record_dependency(name)
                barrier.wait()

        threads = [threading.Thread(target=work, args=(a, "only_a")),
                   threading.Thread(target=work, args=(b, "only_b"))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert a.get_results()["dat"]["dependencies"] == {"only_a": None}
        assert b.get_results()["dat"]["dependencies"] == {"only_b": None}


class TestSeal:
    def test_create_does_not_seal_and_the_first_save_does(self, m):
        dat = m.create({"dat": {}, "k": 1}, path="born")
        assert m.standing("born") == "open"
        assert not Path(dat.get_path(), RESULT_YAML).exists()
        dat.save()
        assert m.standing("born") == "referenceable" == stored_results(dat)["dat"]["standing"]
        assert dat.get_results()["dat"]["sha256"].startswith("sha256:")
        assert dat.verify()

    def test_a_second_save_is_refused(self, m):
        dat = m.create({"dat": {}}, path="once")
        dat.save()
        with pytest.raises(RuntimeError, match="sealed"):
            dat.save()

    def test_a_dat_saved_without_a_run_is_marked_manual(self, m):
        dat = m.create({"dat": {}}, path="by_hand")
        dat.save()
        assert stored_results(dat)["dat"]["dependencies"] == {"$MANUAL": "manual"}

    def test_execute_does_not_save(self, m, clean_code):
        m.do.mount(value=lambda dat: "ran", at="plain")
        dat = m.create({"dat": {"do": "plain"}}, path="unsaved")
        assert m.execute(dat) == "ran"
        assert not Path(dat.get_path(), RESULT_YAML).exists()
        assert dat.get_results()["dat"]["run_at"]           # recorded, in memory
        assert m.standing(dat) == "open"
        dat.save()                                  # sealed outside the run: by hand
        assert m.standing(dat) == "referenceable"
        assert stored_results(dat)["dat"]["dependencies"] == {"$MANUAL": "manual"}

    def test_a_save_inside_the_run_is_a_checkpoint_and_seals_when_it_ends(self, m, clean_code):
        seen = {}

        def fn(dat):
            dat.save()
            seen["inside"] = m.standing("inside")
            seen["checkpoint"] = stored_results(dat)["dat"]["sha256"]
        m.do.mount(value=fn, at="saves")
        dat = m.create({"dat": {"do": "saves"}}, path="inside")
        m.execute(dat)
        assert seen["inside"] == "open" and seen["checkpoint"]
        results = stored_results(dat)["dat"]
        assert results["run_time"] and results["standing"] == "referenceable" and dat.verify()
        assert "$MANUAL" not in results["dependencies"]

    def test_an_open_dat_runs_again_in_place(self, m):
        m.do.mount(value=lambda dat: "ran", at="plain")
        dat = m.create({"dat": {"do": "plain"}}, path="twice")
        assert m.execute(dat) == "ran" and m.execute(dat) == "ran"

    def test_execute_refuses_a_sealed_dat(self, m):
        m.do.mount(value=lambda dat: dat.save(), at="saves")
        dat = m.create({"dat": {"do": "saves"}}, path="ran_once")
        m.execute(dat)
        with pytest.raises(RuntimeError, match="sealed"):
            m.execute(dat)

    def test_the_seal_keeps_the_roots_only(self, m):
        base = m.create({"dat": {}}, path="base")
        base.save()
        mid = m.create({"dat": {}}, path="mid")
        with m.recording(mid):
            m.load("base")
        mid.save()
        top = m.create({"dat": {}}, path="top")
        with m.recording(top):
            m.load("base")
            m.load("mid")
        top.save()
        assert stored_results(top)["dat"]["dependencies"] == {"mid": mid._sha256()}


class TestStanding:
    @pytest.fixture
    def w(self, m, clip):
        m.do.mount(value=lambda dat, src: (dat.manager.load(src), dat.save()), at="reads")
        m.create({"dat": {}}, path="base").save()          # hand-sealed: referenceable
        m.create({"dat": {"standing": "rolling"}}, path="roll").save()
        m.create({"dat": {}}, path="draft")                 # never saved: open
        m.save(clip, name="video/G1")
        return m

    def test_a_rolling_dat_saves_again_and_never_freezes(self, w):
        dat = w.load("roll")
        first = dat._sha256()
        Path(dat.get_path(), "labels.txt").write_text("fixed")
        dat.save()                                     # rewritten: allowed
        assert dat._sha256() != first
        assert stored_results(dat)["dat"]["standing"] == "rolling" == w.standing("roll")

    def test_a_rolling_dat_runs_again(self, m):
        m.do.mount(value=lambda dat: dat.save(), at="saves")
        dat = m.create({"dat": {"do": "saves", "standing": "rolling"}}, path="roll")
        m.execute(dat)
        m.execute(dat)
        assert m.standing("roll") == "rolling"

    def test_referenceable_inputs_and_clean_code_earn_referenceable(self, w, clean_code):
        for src in ("base", "video/G1"):
            dat = w.create({"dat": {"do": "reads", "args": [src]}}, path=f"r_{src}")
            w.execute(dat)
            assert w.standing(dat) == "referenceable"

    def test_a_rolling_input_caps_the_run_at_sealed(self, w, clean_code):
        dat = w.create({"dat": {"do": "reads", "args": ["roll"]}}, path="r1")
        w.execute(dat)
        assert stored_results(dat)["dat"]["standing"] == "sealed"

    def test_dirty_code_caps_the_run_at_sealed(self, w, monkeypatch):
        import dvc_dat.core as core
        monkeypatch.setattr(core, "_code_of", lambda fn: {
            "branch": "main", "commit": "c", "dirty": True})
        dat = w.create({"dat": {"do": "reads", "args": ["base"]}}, path="dirty")
        w.execute(dat)
        assert w.standing("dirty") == "sealed"

    def test_an_open_input_keeps_the_run_open_for_good(self, w):
        dat = w.create({"dat": {"do": "reads", "args": ["draft"]}}, path="r2")
        w.execute(dat)
        results = stored_results(dat)
        assert results["dat"]["dependencies"]["draft"] == "unsealed"
        assert results["dat"]["standing"] == "open" == w.standing("r2")
        dat.get_results()["note"] = "again"
        dat.save()                                    # still open: saves again
        assert stored_results(dat)["note"] == "again" and w.standing("r2") == "open"

    def test_a_referenceable_demand_fails_at_the_load(self, w, clean_code):
        dat = w.create({"dat": {"do": "reads", "args": ["roll"],
                                "standing": "referenceable"}}, path="loud")
        with pytest.raises(RuntimeError, match="'roll' is rolling"):
            w.execute(dat)

    def test_a_referenceable_demand_refuses_dirty_code_up_front(self, w, monkeypatch):
        import dvc_dat.core as core
        monkeypatch.setattr(core, "_code_of", lambda fn: {
            "branch": "main", "commit": "c", "dirty": True})
        dat = w.create({"dat": {"do": "reads", "args": ["base"],
                                "standing": "referenceable"}}, path="dirty")
        with pytest.raises(RuntimeError, match="dirty"):
            w.execute(dat)

    def test_a_referenceable_demand_fails_a_seal_that_earns_less(self, w):
        dat = w.create({"dat": {"standing": "referenceable"}}, path="by_hand")
        with w.recording(dat):
            w.record_dependency("https://example.com/weights")   # no hash
        with pytest.raises(RuntimeError, match="'https://example.com/weights' is sealed"):
            dat.save()

    def test_a_spec_asks_only_for_rolling_or_referenceable(self, m):
        with pytest.raises(ValueError, match="dat.standing"):
            m.create({"dat": {"standing": "sealed"}}, path="x")

    def test_standing_reads_the_files(self, w):
        assert w.standing("nope") is None and w.standing("sha256:" + "0" * 64) is None
        assert w.standing("draft") == "open" and w.standing("base") == "referenceable"
        assert w.standing("video/G1") == "referenceable"

    def test_dat_standing_asks_the_default_world(self):
        assert Dat.standing("certainly/not/here") is None


class TestLegacyResults:
    def write(self, tmp_path, name, spec, result=None):
        folder = tmp_path / "dats" / name
        folder.mkdir(parents=True)
        (folder / "_spec_.yaml").write_text(yaml.safe_dump(spec))
        if result is not None:
            (folder / RESULT_YAML).write_text(yaml.safe_dump(result))

    def test_2_13_files_read_by_the_2_13_rule(self, m, tmp_path):
        self.write(tmp_path, "ref", {"dat": {}}, {"dat": {
            "run_time": "00:00:01.000", "referenceable": True, "sha256": "sha256:x"}})
        self.write(tmp_path, "sealed", {"dat": {}}, {"dat": {
            "dependencies": {"$MANUAL": "manual"}, "referenceable": False}})
        self.write(tmp_path, "roll", {"dat": {"rolling": True}})
        assert [m.standing(n) for n in ("ref", "sealed", "roll")] == \
            ["referenceable", "sealed", "rolling"]

    def test_a_dat_saved_before_2_9_is_open(self, m, tmp_path):
        self.write(tmp_path, "old", {"dat": {"kind": "Dat"}}, {"accuracy": 0.5})
        dat = m.load("old")
        assert m.standing("old") == "open" and not dat.verify()
        dat.save()                                          # sealed by hand, now
        assert m.standing("old") == "referenceable" and dat.verify()


class TestVerifyingLoad:
    def test_a_changed_dat_is_refused_with_both_hashes(self, m):
        dat = m.create({"dat": {}}, path="v")
        dat.save()
        m.load("v", verify=True)                       # intact: loads
        Path(dat.get_path(), "extra.bin").write_bytes(b"x")
        with pytest.raises(ValueError, match="hashes to sha256:.*not its stored sha256:"):
            m.load("v", verify=True)
        m.load("v")                                    # off by default

    def test_the_manager_switch_and_artifacts(self, tmp_path, clip):
        m = DatManager(dat_folders=[str(tmp_path / "dats")],
                       art_folder=str(tmp_path / "art"), verify=True)
        m.save(clip, name="video/G1")
        (tmp_path / "art" / "video" / "G1" / "G1.mp4").write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="video/G1"):
            m.load_path("video/G1")


class TestHeldAsks:
    def test_roots_is_the_seal_trim(self, m):
        m.create({"dat": {}}, path="a").save()
        mid = m.create({"dat": {}}, path="b")
        with m.recording(mid):
            m.load("a")
        mid.save()
        assert list(m.roots({"a": "x", "b": "y"})) == ["b"]

    def test_code_of(self):
        code = DatManager.code_of(test_code_of)
        assert code is None or set(code) == {"branch", "commit", "dirty"}

    def test_link_hard_links_the_payload(self, m, clip, tmp_path):
        m.save(clip, name="video/G1", link=True)
        stored = tmp_path / "art" / "video" / "G1" / "G1.mp4"
        assert os.stat(stored).st_ino == os.stat(clip).st_ino


class TestDatHash:
    def test_the_hash_covers_the_data_the_spec_and_the_results(self, m):
        dat = m.create({"dat": {}}, path="h")
        Path(dat.get_path(), "data.bin").write_bytes(b"x")
        dat.save()
        assert dat.verify()
        Path(dat.get_path(), "data.bin").write_bytes(b"y")
        assert not dat.verify()                       # a file changed under it

    def test_editing_the_results_file_by_hand_fails_verification(self, m):
        dat = m.create({"dat": {}}, path="edited")
        dat.save()
        path = Path(dat.get_path(), RESULT_YAML)
        path.write_text(path.read_text() + "tampered: true\n")
        assert not dat.verify()

    def test_reformatting_the_results_file_does_not(self, m):
        dat = m.create({"dat": {}}, path="reformatted")
        dat.get_results()["b"] = 2
        dat.get_results()["a"] = 1
        dat.save()
        path = Path(dat.get_path(), RESULT_YAML)
        path.write_text(yaml.safe_dump(yaml.safe_load(path.read_text()), sort_keys=True))
        assert dat.verify()


class TestLoadPath:
    def test_a_dat_gives_its_folder_and_is_recorded(self, m):
        prev = m.create({"dat": {}}, path="prev")
        prev.save()
        dat = m.create({"dat": {}}, path="run")
        with m.recording(dat):
            assert m.load_path("prev") == Path(prev.get_path())
        assert dat.get_results()["dat"]["dependencies"] == {"prev": prev._sha256()}

    def test_an_artifact_gives_its_payload_and_is_recorded(self, m, clip):
        digest = m.save(clip, VideoClip, "video/G1")
        dat = m.create({"dat": {}}, path="run")
        with m.recording(dat):
            path = m.load_path("video/G1")
        assert path.name == "G1.mp4" and path.read_bytes() == b"frames"
        assert dat.get_results()["dat"]["dependencies"] == {"video/G1": digest}

    def test_a_missing_name_raises(self, m):
        with pytest.raises(KeyError):
            m.load_path("nope")
        with pytest.raises(FileNotFoundError):
            m.load_path("art:video/nope")


def test_code_of():
    """A module-level function, so `code_of` has a source file to look up."""
