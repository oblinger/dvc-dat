import os
import sys
import json
import tempfile
from pathlib import Path
from typing import Dict
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dat.do import do
from dat.cube import Cube
import dat.inst as inst_module
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
    temp_dir = tempfile.TemporaryDirectory()
    monkeypatch.setattr(inst_module, "INST_ROOT", temp_dir.name)
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
    # temp_root_with_gameset contains the dir to the mocked...
    # INST_ROOT, just with the gamesets already setup
    mock_inst_root = temp_root_with_gameset

    runset_path = Path(mock_inst_root.name, "runsets/bb/baller10")
    runset_path.mkdir(parents=True, exist_ok=True)

    with (runset_path / "_spec_.json").open("w") as f:
        json.dump(instcontainer_spec, f)

    run_1_path = runset_path / "1"
    run_1_path.mkdir(exist_ok=True, parents=True)

    game_1_path = Path(mock_inst_root.name,
                       "gamesets/bb/baller10/1")

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


class TestDoHello:
    def test_load_do(self):
        assert do("cube_hello", show=True)


class TestCreate:
    def test_null_create(self, spec1):
        assert Cube(), "Couldn't create Persistable"

    def test_add_do_fn(self):
        cube = Cube()
        cube.add_do_fn("always_17", lambda inst: 17)
        return cube

    def test_add_inst(self, inst1):
        cube = test_add_do_fn()
        cube.add_inst(inst1)
        assert cube.points == [{"always17": 17}], "Couldn't add Inst to Cube"


class TestPointFns:
    def test_simple_point_fn(self):
        cube = Cube()
        cube.add_do_fn("always_17", lambda inst: 17)
        cube.add_do_fn("always_18", lambda inst: 18)
        cube.add_inst(Inst(spec={}, path=TMP_PATH))
        assert cube.points == [{"always17": 17}], "Couldn't add Inst to Cube"

    def test_multi_value_point_fns(self):
        cube = Cube()
        cube.add_do_fn("two_value", lambda inst: {"val1": 1, "val2": 2})
        cube.add_do_fn("always_18", lambda inst: 18)
        cube.add_inst(Inst(spec={}, path=TMP_PATH))
        assert cube.points == [{"always18": 18, "two_value": {"val1": 1, "val2": 2}}], \
            "Couldn't add Inst to Cube"

    def test_multi_point_point_fns(self):
        cube = Cube()
        cube.add_do_fn("two_value", lambda inst: [{"val1": 1}, {"val2": 2}])
        cube.add_do_fn("always_18", lambda inst: 18)
        cube.add_inst(Inst(spec={}, path=TMP_PATH))
        assert cube.points == [{"always18": 18, "two_value": {"val1": 1, "val2": 2}},
                               {"always18": 18, "two_value": {"val1": 1, "val2": 2}}], \
            "Couldn't add Inst to Cube"


# class TestInstLoadingAndSaving:
#     def test_create(self):
#         assert Inst(spec={}, path=TMP_PATH), "Couldn't create Persistable"
#
#     def test_path_accessor(self, inst1):
#         assert inst1.path == TMP_PATH
#
#     def test_spec_accessors(self, spec1, inst1):
#         assert inst1.spec == spec1
#
#     def test_save(self, inst1):
#         inst1.save()
#         assert True
#
#     def test_load(self, spec1):
#         original = Inst(spec=spec1, path=TMP_PATH)
#         original.save()
#
#         inst = Inst.load(TMP_PATH)
#         assert isinstance(inst, Inst), "Did not load the Persistable"
#         assert inst.spec == spec1
#
#
# class TestInstContainers:
#     def test_create(self):
#         container = InstContainer(path=TMP_PATH, spec={})
#         assert isinstance(container, InstContainer)
#         assert container.inst_paths == []
#         assert container.insts == []
#
#     def test_save_empty_container(self):
#         container = InstContainer(path=TMP_PATH, spec={})
#         container.save()
#         assert Inst.get(container.spec, MAIN_CLASS) == "InstContainer"
#
#     def test_composite_inst_container(self):
#         container = InstContainer(path=TMP_PATH, spec={})
#         container.save()
#         for i in range(10):
#             name = f"sub_{i}"
#             sub = Inst(path=os.path.join(container.path, name), spec={})
#             Inst.set(sub.spec, "main.my_nifty_name", name)
#             sub.save()
#
#         reload: InstContainer[Inst] = InstContainer.load(TMP_PATH)
#         assert isinstance(reload, InstContainer)
#         assert Inst.get(reload.spec, MAIN_CLASS) == "InstContainer"
#
#         paths = reload.inst_paths
#         assert isinstance(paths, list)
#         assert isinstance(paths[3], str)
#
#         sub_insts = reload.insts
#         assert isinstance(sub_insts, list)
#         assert isinstance(sub_insts[3], Inst)
#         assert Inst.get(sub_insts[8], "main.my_nifty_name") == "sub_8"
#
#         os.system(f"rm -r '{TMP_PATH}'")


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
#             runs10: InstContainer[MCProcRun]=InstContainer.load("runsets/bb/baller10")
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


if __name__ == "__main__":
    TestCreate().test_create(spec1)
    # pytest.main([__file__])
