"""2.4: artifacts (`save`, `load` of `art:` names, `register_artifact`) and
dependencies by capture (`recording`, `record_dependency`, `dat.dependencies`)."""
import hashlib
import os
import sys
import threading
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dvc_dat import Dat, DatManager  # noqa: E402
from dvc_dat.core import ART_FILE, DAT_CONFIG_FILE, RESULT_YAML  # noqa: E402


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


def stored_results(dat):
    return yaml.safe_load(Path(dat.get_path(), RESULT_YAML).read_text())


class VideoClip:
    def __init__(self, path):
        self.path = path


class TestArtifacts:
    def test_a_file_round_trips_with_its_hash(self, m, clip, tmp_path):
        digest = m.save(clip, "art:video/G1")
        assert digest == "sha256:" + sha(b"frames")
        home = tmp_path / "art" / "video" / "G1"
        sidecar = yaml.safe_load((home / ART_FILE).read_text())
        assert sidecar["kind"] == "video" and sidecar["name"] == "art:video/G1"
        assert sidecar["payload"] == "G1.mp4" and sidecar["sha256"] == digest
        assert sidecar["saved_at"]
        loaded = m.load("art:video/G1")
        assert loaded == Path(os.path.realpath(home), "G1.mp4")   # unregistered: a Path
        assert loaded.read_bytes() == b"frames"
        assert m.exists("art:video/G1") and not m.exists("art:video/G2")

    def test_a_folder_round_trips_with_its_hash(self, m, folder):
        digest = m.save(folder, "art:assets/lock")
        lines = sorted([f"a.txt\0{sha(b'a')}\n", f"sub/b.txt\0{sha(b'b')}\n"])
        assert digest == "sha256:" + sha("".join(lines).encode())
        loaded = m.load("art:assets/lock")
        assert (loaded / "sub" / "b.txt").read_text() == "b"
        assert yaml.safe_load((loaded / ART_FILE).read_text())["payload"] == "."

    def test_a_name_is_written_once(self, m, clip):
        m.save(clip, "art:video/G1")
        with pytest.raises(FileExistsError):
            m.save(clip, "art:video/G1")

    @pytest.mark.parametrize("name", ["art:video", "art:/G1", "art:video/", "art:v/../../x"])
    def test_a_malformed_name_is_refused(self, m, clip, name):
        with pytest.raises(ValueError):
            m.save(clip, name)

    def test_a_missing_artifact_names_itself(self, m):
        with pytest.raises(FileNotFoundError, match="art:video/nope"):
            m.load("art:video/nope")

    def test_a_class_and_a_lambda_as_factories(self, m, clip, folder):
        m.save(clip, "art:video/G1")
        m.save(folder, "art:assets/lock")
        m.register_artifact("video", VideoClip)
        m.register_artifact("assets", lambda path: sorted(os.listdir(path)))
        video = m.load("art:video/G1")
        assert isinstance(video, VideoClip) and video.path.name == "G1.mp4"
        assert m.load("art:assets/lock") == [ART_FILE, "a.txt", "sub"]

    def test_the_art_folder_can_be_given(self, tmp_path, clip):
        m = DatManager(dat_folders=[str(tmp_path / "dats")], art_folder=str(tmp_path / "store"))
        m.save(clip, "art:video/G1")
        assert (tmp_path / "store" / "video" / "G1" / ART_FILE).exists()

    def test_no_art_folder_means_no_artifacts(self, tmp_path, clip):
        m = DatManager(dat_folders=[str(tmp_path / "dats")])
        with pytest.raises(RuntimeError, match="no art_folder"):
            m.save(clip, "art:video/G1")
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

    def test_load_dat_config_reads_art_folder(self, tmp_path, clip, monkeypatch):
        (tmp_path / DAT_CONFIG_FILE).write_text("dat_folders: dats\nart_folder: blobs\n")
        m = DatManager.load_dat_config(tmp_path)
        m.save(clip, "art:video/G1")
        assert (tmp_path / "blobs" / "video" / "G1" / ART_FILE).exists()
        monkeypatch.setenv("DAT_ART_FOLDER", str(tmp_path / "env"))
        assert DatManager.load_dat_config(tmp_path)._art_folder == os.path.realpath(tmp_path / "env")


def uses_both(dat, prev):
    dat.manager.load(prev)
    dat.manager.load("art:video/G1")
    dat.save()
    return "ran"


def outer(dat):
    dat.manager.do({"dat": {"do": "inner_fn", "name": "inner"}})
    dat.manager.load("art:video/G1")
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
        self.digest = m.save(clip, "art:video/G1")
        m.create({"dat": {}}, path="prev").save()
        return m

    def test_a_runs_loads_land_in_its_dependencies(self, world):
        dat = world.create({"dat": {"do": "uses_both", "kwargs": {"prev": "prev"}}},
                           path="run")
        assert world.execute(dat) == "ran"
        deps = stored_results(dat)["dat"]["dependencies"]
        assert deps == {"prev": world.load("prev").get_results()["dat"]["sha256"],
                        "art:video/G1": self.digest}
        assert all(v and v.startswith("sha256:") for v in deps.values())

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
            {"inner": inner.get_results()["dat"]["sha256"], "art:video/G1": self.digest}
        assert stored_results(inner)["dat"]["dependencies"] == \
            {"prev": world.load("prev").get_results()["dat"]["sha256"]}

    def test_an_unsealed_dependency_leaves_the_run_unsealed(self, world):
        world.create({"dat": {}}, path="draft")         # never saved
        dat = world.create({"dat": {"do": "uses_both", "kwargs": {"prev": "draft"}}},
                           path="run2")
        world.execute(dat)
        results = stored_results(dat)
        assert results["dat"]["dependencies"]["draft"] == "unsealed"
        assert "referenceable" not in results["dat"]
        assert world.status(dat) is Dat.Status.OPEN == world.status("run2")
        dat.get_results()["note"] = "again"
        dat.save()                                    # still open: saves again
        assert stored_results(dat)["note"] == "again"
        assert world.status("run2") is Dat.Status.OPEN

    def test_recording_by_hand(self, world):
        dat = world.create({"dat": {}}, path="builder")
        with world.recording(dat):
            world.load("art:video/G1")
            world.record_dependency("https://example.com/weights", "sha256:w")
        assert dat.get_results()["dat"]["dependencies"] == {
            "art:video/G1": self.digest, "https://example.com/weights": "sha256:w"}
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
            digest = world.save(out, "art:blob/out")
        assert dat.get_results()["dat"]["dependencies"] == {"art:blob/out": digest}

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
        assert m.status("born") is Dat.Status.OPEN
        assert not Path(dat.get_path(), RESULT_YAML).exists()
        dat.save()
        assert m.status("born") is Dat.Status.SEALED
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

    def test_execute_does_not_save(self, m):
        m.do.mount(value=lambda dat: "ran", at="plain")
        dat = m.create({"dat": {"do": "plain"}}, path="unsaved")
        assert m.execute(dat) == "ran"
        assert not Path(dat.get_path(), RESULT_YAML).exists()
        assert dat.get_results()["dat"]["run_at"]           # recorded, in memory
        dat.save()                                  # sealed outside the run: by hand
        assert m.status(dat) is Dat.Status.SEALED
        assert stored_results(dat)["dat"]["dependencies"] == {"$MANUAL": "manual"}

    def test_a_save_inside_the_run_seals_when_it_ends(self, m):
        seen = {}

        def fn(dat):
            dat.save()
            seen["inside"] = m.status("inside")
            seen["checkpoint"] = stored_results(dat)["dat"]["sha256"]
        m.do.mount(value=fn, at="saves")
        dat = m.create({"dat": {"do": "saves"}}, path="inside")
        m.execute(dat)
        assert seen["inside"] is Dat.Status.OPEN and seen["checkpoint"]
        results = stored_results(dat)["dat"]
        assert results["run_time"] and results["sha256"] and dat.verify()
        assert "$MANUAL" not in results["dependencies"]

    def test_an_unsealed_dat_runs_again_in_place(self, m):
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


class TestRolling:
    def test_a_rolling_dat_saves_again_and_never_freezes(self, m):
        dat = m.create({"dat": {"rolling": True}}, path="G1")
        assert m.status("G1") is Dat.Status.ROLLING
        dat.save()
        first = stored_results(dat)["dat"]["sha256"]
        Path(dat.get_path(), "labels.txt").write_text("fixed")
        dat.save()                                     # rewritten: allowed
        assert stored_results(dat)["dat"]["sha256"] != first
        assert stored_results(dat)["dat"]["referenceable"] is False
        assert m.status("G1") is Dat.Status.ROLLING

    def test_a_rolling_dat_runs_again(self, m):
        m.do.mount(value=lambda dat: dat.save(), at="saves")
        dat = m.create({"dat": {"do": "saves", "rolling": True}}, path="roll")
        m.execute(dat)
        m.execute(dat)
        assert m.status("roll") is Dat.Status.ROLLING


class TestReferenceable:
    @pytest.fixture
    def w(self, m):
        m.do.mount(value=lambda dat, src: (dat.manager.load(src), dat.save()), at="reads")
        base = m.create({"dat": {}}, path="base")
        base.save()                                    # hand-sealed: referenceable
        m.create({"dat": {"rolling": True}}, path="roll").save()
        return m

    def test_a_hand_seal_is_referenceable(self, w):
        assert stored_results(w.load("base"))["dat"]["referenceable"] is True

    def test_a_rolling_input_makes_the_run_unreferenceable(self, w):
        dat = w.create({"dat": {"do": "reads", "args": ["roll"]}}, path="r1")
        w.execute(dat)
        assert w.status("r1") is Dat.Status.SEALED
        assert stored_results(dat)["dat"]["referenceable"] is False

    def test_a_dirty_run_is_unreferenceable_and_a_clean_one_is_not(self, w, monkeypatch):
        import dvc_dat.core as core
        for dirty in (True, False):
            monkeypatch.setattr(core, "_code_of", lambda fn, d=dirty: {
                "branch": "main", "commit": "c", "dirty": d})
            dat = w.create({"dat": {"do": "reads", "args": ["base"]}}, path=f"d{dirty}")
            w.execute(dat)
            assert stored_results(dat)["dat"]["referenceable"] is (not dirty)

    def test_referenceable_true_fails_loudly_on_a_rolling_input(self, w, monkeypatch):
        import dvc_dat.core as core
        monkeypatch.setattr(core, "_code_of", lambda fn: {
            "branch": "main", "commit": "c", "dirty": False})
        dat = w.create({"dat": {"do": "reads", "args": ["roll"]}}, path="loud")
        with pytest.raises(RuntimeError, match="'roll' is rolling"):
            w.execute(dat, referenceable=True)

    def test_referenceable_true_refuses_dirty_code(self, w, monkeypatch):
        import dvc_dat.core as core
        monkeypatch.setattr(core, "_code_of", lambda fn: {
            "branch": "main", "commit": "c", "dirty": True})
        dat = w.create({"dat": {"do": "reads", "args": ["base"]}}, path="dirty")
        with pytest.raises(RuntimeError, match="dirty"):
            w.execute(dat, referenceable=True)


class TestStatus:
    def test_every_value_read_from_disk(self, m, clip):
        assert m.status("nope") is Dat.Status.ABSENT
        m.create({"dat": {}}, path="o")
        assert m.status("o") is Dat.Status.OPEN
        assert m.status("art:video/G1") is Dat.Status.ABSENT
        m.save(clip, "art:video/G1")
        assert m.status("art:video/G1") is Dat.Status.SEALED

    def test_dat_status_asks_the_default_world(self):
        assert Dat.status("certainly/not/here") is Dat.Status.ABSENT


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
        m.save(clip, "art:video/G1")
        (tmp_path / "art" / "video" / "G1" / "G1.mp4").write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="art:video/G1"):
            m.load_path("art:video/G1")


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
        m.save(clip, "art:video/G1", link=True)
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

    def test_a_dat_saved_before_2_9_is_unsealed(self, m, tmp_path):
        old = tmp_path / "dats" / "old"
        old.mkdir(parents=True)
        (old / "_spec_.yaml").write_text("dat: {kind: Dat}\n")
        (old / RESULT_YAML).write_text("accuracy: 0.5\n")    # no dat.sha256
        dat = m.load("old")
        assert m.status("old") is Dat.Status.OPEN and not dat.verify()
        dat.save()                                          # sealed by hand, now
        assert m.status("old") is Dat.Status.SEALED and dat.verify()



class TestLoadPath:
    def test_a_dat_gives_its_folder_and_is_recorded(self, m):
        prev = m.create({"dat": {}}, path="prev")
        prev.save()
        dat = m.create({"dat": {}}, path="run")
        with m.recording(dat):
            assert m.load_path("prev") == Path(prev.get_path())
        assert dat.get_results()["dat"]["dependencies"] == {"prev": prev._sha256()}

    def test_an_artifact_gives_its_payload_and_builds_nothing(self, m, clip):
        digest = m.save(clip, "art:video/G1")
        built = []
        m.register_artifact("video", lambda path: built.append(path))
        dat = m.create({"dat": {}}, path="run")
        with m.recording(dat):
            path = m.load_path("art:video/G1")
        assert path.name == "G1.mp4" and path.read_bytes() == b"frames"
        assert built == []                           # no factory ran
        assert dat.get_results()["dat"]["dependencies"] == {"art:video/G1": digest}

    def test_a_missing_name_raises(self, m):
        with pytest.raises(KeyError):
            m.load_path("nope")
        with pytest.raises(FileNotFoundError):
            m.load_path("art:video/nope")


def test_code_of():
    """A module-level function, so `code_of` has a source file to look up."""
