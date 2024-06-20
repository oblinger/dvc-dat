import os
import sys
import json
import tempfile
from pathlib import Path
from typing import Dict
import pytest

from dvc_dat import dat_config

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dvc_dat.dat import _DAT_CLASS, Dat, DatContainer


TMP_PATH = "/tmp/job_test"
TMP_PATH2 = "/tmp/job_test2"


@pytest.fixture
def do():
    from dvc_dat import do
    return do


@pytest.fixture
def spec1():
    return {
        "dat": {"path": "test_dats/{YY}-{MM} Dats{unique}",
                 "my_key1": "my_val1", "my_key2": "my_val2"}
    }


@pytest.fixture
def dat1(spec1):
    return Dat.create(spec=spec1, path=TMP_PATH, overwrite=True)


@pytest.fixture
def spec2():
    return {"dat": {"path": "test_dats/{YY}-{MM} Dats{unique}",
                     "my_key1": "my_val111", "my_key2": "my_val222"},
            "other": "key_value"}


@pytest.fixture
def dat_container_spec():
    return {"dat": {"class": "DatContainer"}}


@pytest.fixture
def game_spec():
    return {"dat": {"class": "Game"}, "game": {"views": {"view_1": "vid_1.mp4"}}}


@pytest.fixture
def mock_dat_root(monkeypatch: pytest.MonkeyPatch) -> tempfile.TemporaryDirectory:
    import dvc_dat.dat as dat
    temp_dir = tempfile.TemporaryDirectory()
    monkeypatch.setattr(dat, "DAT_ROOT", temp_dir.name)
    return temp_dir


@pytest.fixture
def temp_root_with_gameset(
    mock_dat_root: tempfile.TemporaryDirectory,
        dat_container_spec,
        game_spec: Dict) -> tempfile.TemporaryDirectory:
    gameset_path = Path(mock_dat_root.name, "gamesets/bb/baller10")
    gameset_path.mkdir(parents=True, exist_ok=True)

    with (gameset_path / "_spec_.yaml").open("w") as f:
        json.dump(dat_container_spec, f)

    game_1_path = gameset_path / "1"
    game_1_path.mkdir(exist_ok=True, parents=True)

    with (game_1_path / "_spec_.yaml").open("w") as f:
        json.dump(game_spec, f)

    return mock_dat_root


@pytest.fixture
def temp_root_with_runset(
        temp_root_with_gameset: tempfile.TemporaryDirectory,
        dat_container_spec) -> tempfile.TemporaryDirectory:
    mock_dat_root = temp_root_with_gameset
    runset_path = Path(mock_dat_root.name, "runsets/bb/baller10")
    runset_path.mkdir(parents=True, exist_ok=True)

    with (runset_path / "_spec_.yaml").open("w") as f:
        json.dump(dat_container_spec, f)

    run_1_path = runset_path / "1"
    run_1_path.mkdir(exist_ok=True, parents=True)

    game_1_path = Path(mock_dat_root.name, "gamesets/bb/baller10/1")

    run_spec = {
        "dat": {"class": "MCProcRun"},
        "run": {
            "input_game": str(game_1_path),
            "mcproc_output": "my_file.pickle",
        },
    }

    with (run_1_path / "_spec_.yaml").open("w") as f:
        json.dump(run_spec, f)

    return mock_dat_root


# Tests


class TestDatAccessors:
    def test_path_accessors(self, spec1):
        dat = Dat.create(spec=spec1, path="any/path/goes/here/my_dat", overwrite=True)
        assert dat.get_path() == f"{dat_config.sync_folder}/any/path/goes/here/my_dat"
        assert dat.get_path_name() == "any/path/goes/here/my_dat"
        assert dat.get_path_tail() == "my_dat"
        assert dat.delete()

    def test_spec_and_result_accessors(self, spec1):
        my_name = "any/path/my_dat"
        dat = Dat.create(spec=spec1, path=my_name, overwrite=True)
        assert dat.get_spec() == spec1
        assert dat.get_results() == {}
        Dat.set(dat.get_results(), "dat.my_key1", "my_val1")
        dat.save()
        dat2 = Dat.load(dat.get_path_name())  # Reloads the dat
        assert Dat.get(dat2.get_results(), "dat.my_key1") == "my_val1"
        assert dat.delete()


class TestDatCreationFromStaticFolders:
    def test_create_with_spec(self, spec1):
        assert Dat.create(path=TMP_PATH, spec=spec1, overwrite=True)

    def test_create_with_spec_and_path(self, spec1):
        assert Dat.create(path=TMP_PATH, spec=spec1, overwrite=True)


class TestCreateSaveAndLoad:
    def test_create(self, spec1):  # Creation needed to work for these tests
        assert Dat.create(path=TMP_PATH, spec=spec1, overwrite=True)

    def test_get(self, spec1):
        assert Dat.get(spec1, ["dat", "my_key1"]) == "my_val1"
        assert Dat.get(spec1, "dat.my_key1") == "my_val1"
        assert Dat.get(spec1, ["dat"]) == spec1["dat"]
        assert Dat.get(spec1, "dat") == spec1["dat"]

    def test_set(self, spec1):
        Dat.set(spec1, ["dat", "foo"], "bar")
        assert Dat.get(spec1, ["dat", "foo"]) == "bar"
        Dat.set(spec1, "dat.foo", "baz")
        assert Dat.get(spec1, ["dat", "foo"]) == "baz"

        Dat.set(spec1, ["key1"], "value1")
        assert Dat.get(spec1, ["key1"]) == "value1"
        Dat.set(spec1, "key1", "value2")
        assert Dat.get(spec1, ["key1"]) == "value2"

    def test_deep_set(self, spec1):
        Dat.set(spec1, ["level1", "level2", "level3", "lev4"], "val")
        assert Dat.get(spec1, ["level1", "level2", "level3", "lev4"]) == "val"

    def test_persistable_get_set(self, spec1):
        dat = Dat.create(spec=spec1, path=TMP_PATH, overwrite=True)
        assert Dat.get(dat, ["dat", "my_key1"]) == "my_val1"
        assert Dat.get(dat, ["dat"]) == spec1["dat"]

    def test_gets(self, spec1):
        dat = Dat.create(spec=spec1, path=TMP_PATH, overwrite=True)
        assert Dat.gets(dat, "dat.my_key1", "dat") == [
            "my_val1",
            spec1["dat"],
        ]

    def test_sets(self, spec1):
        Dat.sets(spec1, "dat.foo = bar", "bip.bop.boop=3.14", "bip.zip=7")
        assert Dat.gets(spec1, "dat.foo", "bip.bop.boop", "bip.zip") == [
            "bar",
            3.14,
            7,
        ]


class TestDatLoadingAndSaving:
    def test_create(self):
        assert Dat.create(spec={}, path=TMP_PATH, overwrite=True)

    def test_path_accessor(self, dat1):
        assert dat1._path == TMP_PATH

    def test_spec_accessors(self, spec1, dat1):
        assert dat1._spec == spec1

    def test_save(self, dat1):
        dat1.save()
        assert True

    def test_load(self, spec1):
        original = Dat.create(spec=spec1, path=TMP_PATH, overwrite=True)
        original.save()

        dat = Dat.load(TMP_PATH)
        assert isinstance(dat, Dat), "Did not load the Persistable"
        assert dat._spec == spec1


class TestDatCopyMoveDelete:
    def test_copy_exists_and_delete(self):
        if Dat.exists("Datasets/a_copy"):
            Dat.load("Datasets/a_copy").delete()
        dat = Dat.create(spec={"zap": 77})
        assert isinstance(dat2 := dat.copy("Datasets/a_copy"), Dat)
        assert Dat.get(dat2, "zap") == 77
        assert Dat.exists("Datasets/a_copy") is True
        assert dat2.delete()
        assert dat.delete()
        assert Dat.exists("Datasets/a_copy") is False

    def test_move(self):
        if Dat.exists("Datasets/moved"):
            Dat.load("Datasets/moved").delete()
        dat = Dat.create(spec={"zap": 88})
        original_name = dat.get_path_name()
        assert isinstance(dat2 := dat.move("Datasets/moved"), Dat)
        assert Dat.get(dat2, "zap") == 88
        assert Dat.exists("Datasets/moved") is True
        assert Dat.exists(original_name) is False
        assert dat2.delete()


class TestDatContainers:
    def test_create(self):
        # os.system(f"rm -r '{TMP_PATH}'")
        container = Dat.create(path=TMP_PATH, spec={"dat": {"class": "DatContainer"}},
                               overwrite=True)
        assert isinstance(container, DatContainer)
        assert container.get_dat_paths() == []
        assert container.get_dats() == []

    def test_save_empty_container(self):
        container = Dat.create(path=TMP_PATH, spec={"dat": {"class": "DatContainer"}},
                               overwrite=True)
        container.save()
        assert Dat.get(container._spec, _DAT_CLASS) == "DatContainer"

    def test_composite_dat_container(self):
        container = Dat.create(path=TMP_PATH, spec={"dat": {"class": "DatContainer"}},
                               overwrite=True)
        container.save()
        for i in range(10):
            name = f"sub_{i}"
            spec = {}
            Dat.set(spec, "dat.my_nifty_name", name)
            sub = Dat.create(path=os.path.join(container.get_path(), name), spec=spec)
            sub.save()

        reload: DatContainer[Dat] = DatContainer.load(TMP_PATH)
        assert isinstance(reload, DatContainer)
        assert Dat.get(reload.get_spec(), _DAT_CLASS) == "DatContainer"

        paths = reload.get_dat_paths()
        assert isinstance(paths, list)
        assert isinstance(paths[3], str)

        sub_dats = reload.get_dats()
        assert isinstance(sub_dats, list)
        assert isinstance(sub_dats[3], Dat)
        assert Dat.get(sub_dats[8], "dat.my_nifty_name") == "sub_8"

        os.system(f"rm -r '{TMP_PATH}'")


class TestCleanup:
    def test_cleanup(self):
        os.system("rm -r test_sync_folder/anonymous")  # remove all anon dats
