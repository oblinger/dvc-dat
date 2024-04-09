import os
import sys
import json
import tempfile
from pathlib import Path
from typing import Dict
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dat.inst import MAIN_CLASS, Inst, InstContainer


TMP_PATH = "/tmp/job_test"
TMP_PATH2 = "/tmp/job_test2"


@pytest.fixture
def spec1():
    return {
        "main": {"my_key1": "my_val1", "my_key2": "my_val2"}
    }


@pytest.fixture
def inst1(spec1):
    return Inst(spec=spec1, path=TMP_PATH)


@pytest.fixture
def spec2():
    return {"main": {"my_key1": "my_val1", "my_key2": "my_val2"}, "other": "key_value"}


@pytest.fixture
def instcontainer_spec():
    return {"main": {"class": "InstContainer"}}


@pytest.fixture
def game_spec():
    return {"main": {"class": "Game"}, "game": {"views": {"view_1": "vid_1.mp4"}}}


@pytest.fixture
def mock_inst_root(monkeypatch: pytest.MonkeyPatch) -> tempfile.TemporaryDirectory:
    import dat.inst as inst
    temp_dir = tempfile.TemporaryDirectory()
    monkeypatch.setattr(inst, "INST_ROOT", temp_dir.name)
    return temp_dir


@pytest.fixture
def temp_root_with_gameset(
    mock_inst_root: tempfile.TemporaryDirectory,
    instcontainer_spec: Dict,
    game_spec: Dict,
) -> tempfile.TemporaryDirectory:
    gameset_path = Path(mock_inst_root.name, "gamesets/bb/baller10")
    gameset_path.mkdir(parents=True, exist_ok=True)

    with (gameset_path / "_spec_.json").open("w") as f:
        json.dump(instcontainer_spec, f)

    game_1_path = gameset_path / "1"
    game_1_path.mkdir(exist_ok=True, parents=True)

    with (game_1_path / "_spec_.json").open("w") as f:
        json.dump(game_spec, f)

    return mock_inst_root


@pytest.fixture
def temp_root_with_runset(
    temp_root_with_gameset: tempfile.TemporaryDirectory,
    instcontainer_spec: Dict,
) -> tempfile.TemporaryDirectory:
    # temp_root_with_gameset contains the dir to the mocked
    # INST_ROOT, just with the gamesets already setup
    mock_inst_root = temp_root_with_gameset

    runset_path = Path(mock_inst_root.name, "runsets/bb/baller10")
    runset_path.mkdir(parents=True, exist_ok=True)

    with (runset_path / "_spec_.json").open("w") as f:
        json.dump(instcontainer_spec, f)

    run_1_path = runset_path / "1"
    run_1_path.mkdir(exist_ok=True, parents=True)

    game_1_path = Path(mock_inst_root.name, "gamesets/bb/baller10/1")

    run_spec = {
        "main": {"class": "MCProcRun"},
        "run": {
            "input_game": str(game_1_path),
            "mcproc_output": "my_file.pickle",
        },
    }

    with (run_1_path / "_spec_.json").open("w") as f:
        json.dump(run_spec, f)

    return mock_inst_root


class TestCreateSaveAndLoad:
    def test_create(self, spec1):  # Creation needed to work for these tests
        assert Inst(path=TMP_PATH, spec=spec1), "Couldn't create Persistable"

    def test_get(self, spec1):
        assert Inst.get(spec1, ["main", "my_key1"]) == "my_val1"
        assert Inst.get(spec1, "main.my_key1") == "my_val1"
        assert Inst.get(spec1, ["main"]) == spec1["main"]
        assert Inst.get(spec1, "main") == spec1["main"]

    def test_set(self, spec1):
        Inst.set(spec1, ["main", "foo"], "bar")
        assert Inst.get(spec1, ["main", "foo"]) == "bar"
        Inst.set(spec1, "main.foo", "baz")
        assert Inst.get(spec1, ["main", "foo"]) == "baz"

        Inst.set(spec1, ["key1"], "value1")
        assert Inst.get(spec1, ["key1"]) == "value1"
        Inst.set(spec1, "key1", "value2")
        assert Inst.get(spec1, ["key1"]) == "value2"

    def test_deep_set(self, spec1):
        Inst.set(spec1, ["level1", "level2", "level3", "lev4"], "val")
        assert Inst.get(spec1, ["level1", "level2", "level3", "lev4"]) == "val"

    def test_persistable_get_set(self, spec1):
        inst = Inst(spec=spec1, path=TMP_PATH)
        assert Inst.get(inst, ["main", "my_key1"]) == "my_val1"
        assert Inst.get(inst, ["main"]) == spec1["main"]

    def test_gets(self, spec1):
        inst = Inst(spec=spec1, path=TMP_PATH)
        assert Inst.gets(inst, "main.my_key1", "main") == [
            "my_val1",
            spec1["main"],
        ]

    def test_sets(self, spec1):
        Inst.sets(spec1, "main.foo = bar", "bip.bop.boop=3.14", "bip.zip=7")
        assert Inst.gets(spec1, "main.foo", "bip.bop.boop", "bip.zip") == [
            "bar",
            3.14,
            7,
        ]


class TestInstLoadingAndSaving:
    def test_create(self):
        assert Inst(spec={}, path=TMP_PATH), "Couldn't create Persistable"

    def test_path_accessor(self, inst1):
        assert inst1.path == TMP_PATH

    def test_spec_accessors(self, spec1, inst1):
        assert inst1.spec == spec1

    def test_save(self, inst1):
        inst1.save()
        assert True

    def test_load(self, spec1):
        original = Inst(spec=spec1, path=TMP_PATH)
        original.save()

        inst = Inst.load(TMP_PATH)
        assert isinstance(inst, Inst), "Did not load the Persistable"
        assert inst.spec == spec1


class TestInstContainers:
    def test_create(self):
        container = InstContainer(path=TMP_PATH, spec={})
        assert isinstance(container, InstContainer)
        assert container.inst_paths == []
        assert container.insts == []

    def test_save_empty_container(self):
        container = InstContainer(path=TMP_PATH, spec={})
        container.save()
        assert Inst.get(container.spec, MAIN_CLASS) == "InstContainer"

    def test_composite_inst_container(self):
        container = InstContainer(path=TMP_PATH, spec={})
        container.save()
        for i in range(10):
            name = f"sub_{i}"
            sub = Inst(path=os.path.join(container.path, name), spec={})
            Inst.set(sub.spec, "main.my_nifty_name", name)
            sub.save()

        reload: InstContainer[Inst] = InstContainer.load(TMP_PATH)
        assert isinstance(reload, InstContainer)
        assert Inst.get(reload.spec, MAIN_CLASS) == "InstContainer"

        paths = reload.inst_paths
        assert isinstance(paths, list)
        assert isinstance(paths[3], str)

        sub_insts = reload.insts
        assert isinstance(sub_insts, list)
        assert isinstance(sub_insts[3], Inst)
        assert Inst.get(sub_insts[8], "main.my_nifty_name") == "sub_8"

        os.system(f"rm -r '{TMP_PATH}'")


# from src.inst.builtins import Game, MCProcRun

# class TestBaller10:
#     def test_scanning_baller10_games(
#         self,
#         temp_root_with_gameset: tempfile.TemporaryDirectory,
#     ):
#         with temp_root_with_gameset:
#             b10: InstContainer[Game] = InstContainer.load("gamesets/bb/baller10")
#             assert isinstance(b10, InstContainer)
#
#             for game in b10.insts:
#                 assert isinstance(game, Game)
#                 print(f"The views for {game} are {game.views}")
#             assert True
#
#     def test_scanning_baller10_runs(
#         self,
#         temp_root_with_runset: tempfile.TemporaryDirectory,
#     ):
#         with temp_root_with_runset:
#           runs10: InstContainer[MCProcRun] = InstContainer.load("runsets/bb/baller10")
#             assert isinstance(runs10, InstContainer)
#
#             for run in runs10.insts:
#                 assert isinstance(run, MCProcRun)
#
#                 views = run.game.views
#                 assert isinstance(views, list)
#
#                 target_view = views[0]
#                 assert isinstance(target_view, str)
#
#                 assert isinstance(run.game, Game)
#
#             assert True
