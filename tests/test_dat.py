import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dvc_dat import Dat, DatContainer  # noqa


TMP_PATH = "/tmp/job_test"
TMP_PATH2 = "/tmp/job_test2"


@pytest.fixture
def spec1():
    # In the new system, extra fields go at the top level of the spec
    # (outside the "dat" section which only accepts kind, base, do)
    return {
        "dat": {"kind": "Dat", "target_exists": "overwrite"},
        "my_key1": "my_val1",
        "my_key2": "my_val2"
    }


@pytest.fixture
def dat1(spec1):
    return Dat.create(spec=spec1, path=TMP_PATH)


@pytest.fixture
def spec2():
    return {
        "dat": {
            "kind": "Dat",
            "name": "test_dats/{YY}-{MM} Dats{unique}",
            "my_key1": "my_val111", "my_key2": "my_val222"},
        "other": "key_value"}


# Tests


class TestDatAccessors:
    def test_path_accessors(self, spec1):
        dat = Dat.create(spec=spec1, path="any/path/goes/here/my_dat")
        expected_path = f"{Dat.manager._dat_folders[0]}/any/path/goes/here/my_dat"
        assert dat.get_path() == expected_path
        assert dat.get_path_name() == "any/path/goes/here/my_dat"
        assert dat.delete()

    def test_spec_and_result_accessors(self, spec1):
        my_name = "any/path/my_dat"
        dat = Dat.create(spec=spec1, path=my_name)
        # get_spec() returns the spec as a dict
        spec_dict = dat.get_spec()
        # Extra fields are at the top level in the new system
        assert spec_dict["my_key1"] == spec1["my_key1"]
        assert spec_dict["my_key2"] == spec1["my_key2"]
        assert dat.get_results() == {}
        Dat.set(dat.get_results(), "result_key", "result_val")
        assert dat.delete()


class TestDatCreationFromStaticFolders:
    def test_create_with_spec(self, spec1):
        assert Dat.create(path=TMP_PATH, spec=spec1)

    def test_create_with_spec_and_path(self, spec1):
        assert Dat.create(path=TMP_PATH, spec=spec1)


class TestCreateSaveAndLoad:
    def test_create(self, spec1):  # Creation needed to work for these tests
        assert Dat.create(path=TMP_PATH, spec=spec1)

    def test_get(self, spec1):
        # Extra keys are at top level in new system
        assert Dat.get(spec1, ["my_key1"]) == "my_val1"
        assert Dat.get(spec1, "my_key1") == "my_val1"
        assert Dat.get(spec1, ["dat"]) == spec1["dat"]
        assert Dat.get(spec1, "dat") == spec1["dat"]

    def test_set(self, spec1):
        Dat.set(spec1, ["extra", "foo"], "bar")
        assert Dat.get(spec1, ["extra", "foo"]) == "bar"
        Dat.set(spec1, "extra.foo", "baz")
        assert Dat.get(spec1, ["extra", "foo"]) == "baz"

        Dat.set(spec1, ["key1"], "value1")
        assert Dat.get(spec1, ["key1"]) == "value1"
        Dat.set(spec1, "key1", "value2")
        assert Dat.get(spec1, ["key1"]) == "value2"

    def test_deep_set(self, spec1):
        Dat.set(spec1, ["level1", "level2", "level3", "lev4"], "val")
        assert Dat.get(spec1, ["level1", "level2", "level3", "lev4"]) == "val"

    def test_persistable_get_set(self, spec1):
        dat = Dat.create(spec=spec1, path=TMP_PATH)
        # Extra keys are at top level
        assert Dat.get(dat, ["my_key1"]) == "my_val1"
        # dat section contains only kind/base/do
        dat_dict = Dat.get(dat, ["dat"])
        assert dat_dict["kind"] == "dvc_dat.core.Dat"

    def test_set_creates_levels(self, spec1):
        Dat.set(spec1, "bip.bop.boop", 3.14)
        assert Dat.get(spec1, "bip.bop.boop") == 3.14


class TestDatLoadingAndSaving:
    def test_create(self):
        assert Dat.create(spec={"dat": {"kind": "Dat", "target_exists": "overwrite"}}, path=TMP_PATH)

    def test_path_accessor(self, dat1):
        assert dat1._path == TMP_PATH

    def test_spec_accessors(self, spec1, dat1):
        # In the new system, spec is a Pydantic model, compare via get_spec()
        spec_dict = dat1.get_spec()
        assert spec_dict["my_key1"] == spec1["my_key1"]

    def test_load(self, spec1):
        original = Dat.create(spec=spec1, path=TMP_PATH)

        dat = Dat.load(TMP_PATH)
        assert isinstance(dat, Dat), "Did not load the Persistable"
        spec_dict = dat.get_spec()
        assert spec_dict["my_key1"] == spec1["my_key1"]


class TestDatCopyMoveDelete:
    def test_copy_exists_and_delete(self):
        if Dat.manager.exists("Datasets/a_copy"):
            Dat.load("Datasets/a_copy").delete()
        dat = Dat.create(spec={"dat": {"kind": "Dat"}, "zap": 77})
        assert isinstance(dat2 := dat.copy("Datasets/a_copy"), Dat)
        assert Dat.get(dat2, "zap") == 77
        assert Dat.manager.exists("Datasets/a_copy") is True
        assert dat2.delete()
        assert dat.delete()
        assert Dat.manager.exists("Datasets/a_copy") is False

    def test_move(self):
        if Dat.manager.exists("Datasets/moved"):
            Dat.load("Datasets/moved").delete()
        dat = Dat.create(spec={"dat": {"kind": "Dat"}, "zap": 88})
        original_name = dat.get_path_name()
        assert isinstance(dat2 := dat.move("Datasets/moved"), Dat)
        assert Dat.get(dat2, "zap") == 88
        assert Dat.manager.exists("Datasets/moved") is True
        assert Dat.manager.exists(original_name) is False
        assert dat2.delete()


class TestDatContainers:
    def test_create(self):
        # os.system(f"rm -r '{TMP_PATH}'")
        container = DatContainer.create(path=TMP_PATH, spec={"dat": {"kind": "DatContainer", "target_exists": "overwrite"}})
        assert isinstance(container, DatContainer)
        assert container.get_dat_paths() == []
        assert container.get_dats() == []

    def test_composite_dat_container(self):
        container = DatContainer.create(path=TMP_PATH, spec={"dat": {"kind": "DatContainer", "target_exists": "overwrite"}})
        for i in range(10):
            name = f"sub_{i}"
            # Extra fields go at top level in new system
            spec = {"dat": {"kind": "Dat"}, "my_nifty_name": name}
            sub = Dat.create(path=os.path.join(container.get_path(), name), spec=spec)

        reload: DatContainer[Dat] = DatContainer.load(TMP_PATH)
        assert isinstance(reload, DatContainer)
        assert Dat.get(reload.get_spec(), "dat.kind") == "dvc_dat.core.DatContainer"

        paths = reload.get_dat_paths()
        assert isinstance(paths, list)
        assert isinstance(paths[3], str)

        sub_dats = reload.get_dats()
        assert isinstance(sub_dats, list)
        assert isinstance(sub_dats[3], Dat)
        # Extra fields at top level
        assert Dat.get(sub_dats[8], "my_nifty_name") == "sub_8"

        os.system(f"rm -r '{TMP_PATH}'")


class TestCleanup:
    def test_cleanup(self):
        os.system("rm -r test_sync_folder/anonymous")  # remove all anon dats
