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
    return "ran"


def outer(dat):
    dat.manager.do({"dat": {"do": "inner_fn", "name": "inner"}})
    dat.manager.load("art:video/G1")


def inner_fn(dat):
    dat.manager.load("prev")


class TestCapture:
    @pytest.fixture
    def world(self, m, clip):
        m.do.mount(value=uses_both, at="uses_both")
        m.do.mount(value=outer, at="outer")
        m.do.mount(value=inner_fn, at="inner_fn")
        self.digest = m.save(clip, "art:video/G1")
        m.create({"dat": {}}, path="prev")
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
        world.do.mount(value=lambda dat: None, at="quiet")
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

    def test_a_dats_own_hash_is_its_entry(self, world):
        prev = world.load("prev")
        prev.get_results()["note"] = "changed"
        prev.save()                                   # a new state, a new hash
        dat = world.create({"dat": {"do": "uses_both", "kwargs": {"prev": "prev"}}},
                           path="run2")
        world.execute(dat)
        assert stored_results(dat)["dat"]["dependencies"]["prev"] == \
            prev.get_results()["dat"]["sha256"]

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
        m.do.mount(value=lambda dat: None, at="quiet")
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


class TestDatHash:
    def test_every_dat_is_hashed_from_birth_and_verifies(self, m):
        dat = m.create({"dat": {}, "k": 1}, path="born")
        assert dat.get_results()["dat"]["sha256"].startswith("sha256:")
        assert dat.verify()

    def test_the_hash_covers_the_data_the_spec_and_the_results(self, m):
        dat = m.create({"dat": {}}, path="h")
        first = dat.get_results()["dat"]["sha256"]
        Path(dat.get_path(), "data.bin").write_bytes(b"x")
        assert not dat.verify()                       # a file changed under it
        dat.save()
        second = dat.get_results()["dat"]["sha256"]
        assert second != first and dat.verify()
        dat.get_results()["accuracy"] = 0.9
        dat.save()
        assert dat.get_results()["dat"]["sha256"] != second and dat.verify()

    def test_editing_the_results_file_by_hand_fails_verification(self, m):
        dat = m.create({"dat": {}}, path="edited")
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

    def test_a_dat_saved_before_2_9_is_hashed_on_load(self, m, tmp_path):
        old = tmp_path / "dats" / "old"
        old.mkdir(parents=True)
        (old / "_spec_.yaml").write_text("dat: {kind: Dat}\n")
        (old / RESULT_YAML).write_text("accuracy: 0.5\n")    # no dat.sha256
        dat = m.load("old")
        assert dat._sha256().startswith("sha256:")
        assert not dat.verify()

