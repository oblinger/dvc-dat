import os
import sys
import json
import tempfile
from pathlib import Path
from typing import Dict, Callable
import pytest
import subprocess

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dat.do import do


def run_capture(line: str) -> str:
    result = subprocess.run(line, shell=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    # Optionally, assert that there was no error
    # assert result.returncode == 0
    return result.stdout.strip()


class TestLoad:
    def test_load(self):
        assert do.load("not_there", default=None) is None
        assert isinstance(do.load("hello_world"), Callable)

    def test_load_with_default(self):
        assert do.load("not_there", default="hello") == "hello"
        assert do.load("not_there", default=None) is None
        assert isinstance(do.load("hello_world", default="hello"), Callable)

    def test_multiple_values_in_one_loadable(self):
        assert isinstance(do.load("hello_again"), Callable)
        assert isinstance(do.load("hello_again.hella"), Callable)

    def test_do(self):
        assert do("hello_world") == "hello world!"

    def test_do_with_args_and_return_value(self):
        assert do("hello_again.salutation",
                  name="hello", emphasis=True, lucky_number=7) == \
               (7, "hello, My lucky number is 7")

    def test_do_within_deep_subfolders(self, capsys):
        do("deep_hello")
        captured = capsys.readouterr()
        assert captured.out == "hello echoing out from deep in the filesystem!\n"

    def test_do_on_a_configuration_file(self, capsys):
        do("hello_config", "Martin")
        assert capsys.readouterr().out == "   Martin, My lucky number is 7\n"

    def test_do_on_a_shadowed_config(self, capsys):
        do("hello_shadowed_config")
        assert capsys.readouterr().out == "   Hello, My lucky number is 777\n"

    def test_combining_configs_and_code(self):
        result = "a  jackpot   ccc  D  e  fff  g  h  JACKPOT JACKPOT JACKPOT   j  k" + \
            "  lll  m  N  ooo  jackpot   q  rrr  S  t  uuu  v  jackpot   XXX  y"
        assert do("my_letters") == result

    def test_yaml_constant_loading(self):
        value = {'datasets': ['regression_games', 'baller10', 'volley10', 'arron4'],
                 'metrics': ['team_highlight.money', 'team_highlight.precision',
                             'player_highlight.money', 'basket_stats.money',
                             'p_metric']}
        assert do.load("supported") == value


class TestCommandLine:
    def test_usage_message(self):
        lines = run_capture("./do --usage")
        assert 30 < len(lines.split("\n")) < 50

    def test_commandline_fixed_and_key_args(self):
        result = run_capture("./do hello_again.salutation Maxim --emphasis")
        assert result == "MAXIM, MY LUCKY NUMBER IS 999!\n(999, 'Maxim, My lucky number is 999')"


    def test_run_configuration_from_cmdline(self):
        result = run_capture("./do my_letters")
        assert result == "The Letterator\na  jackpot   ccc  D  e  fff  g  h  JACKPOT JACKPOT JACKPOT   j  k  lll  m  N  ooo  jackpot   q  rrr  S  t  uuu  v  jackpot   XXX  y"

    def test_tweaking_command_from_cmdline(self):
        line = """./do my_letters --set main.title "Re-configured letterator" """ + \
                """--json rules '[[2, "my_letters.triple_it"]]'"""
        expect = """Re-configured letterator\na  bbb  c  ddd  e  fff  g  hhh  i""" + \
                 """  jjj  k  lll  m  nnn  o  ppp  q  rrr  s  ttt  u  vvv  w  xxx  y"""
        assert run_capture(line) == expect


    def test_setting_multiple_params_at_once(self):
        line = """./do my_letters --sets main.title=Quickie,start=100,end=110"""
        expect = """Quickie\n""" + \
                 """D  e  fff  g  h  JACKPOT JACKPOT JACKPOT   j  k  lll  m"""
        assert run_capture(line) == expect









# TMP_PATH = "/tmp/job_test"
# TMP_PATH2 = "/tmp/job_test2"
#
#
# @pytest.fixture
# def spec1():
#     return {
#         "main": {"my_key1": "my_val1", "my_key2": "my_val2"}
#     }
#
#
# @pytest.fixture
# def inst1(spec1):
#     return Inst(spec=spec1, path=TMP_PATH)
#
#
# @pytest.fixture
# def spec2():
#     return {"main": {"my_key1": "my_val1", "my_key2": "my_val2"}, "other": "key_value"}
#
#
# @pytest.fixture
# def instcontainer_spec():
#     return {"main": {"class": "InstContainer"}}
#
#
# @pytest.fixture
# def game_spec():
#     return {"main": {"class": "Game"}, "game": {"views": {"view_1": "vid_1.mp4"}}}
#
#
# @pytest.fixture
# def mock_inst_root(monkeypatch: pytest.MonkeyPatch) -> tempfile.TemporaryDirectory:
#     import dat.inst as inst
#     temp_dir = tempfile.TemporaryDirectory()
#     monkeypatch.setattr(inst, "INST_ROOT", temp_dir.name)
#     return temp_dir
#
#
# @pytest.fixture
# def temp_root_with_gameset(
#     mock_inst_root: tempfile.TemporaryDirectory,
#     instcontainer_spec: Dict,
#     game_spec: Dict,
# ) -> tempfile.TemporaryDirectory:
#     gameset_path = Path(mock_inst_root.name, "gamesets/bb/baller10")
#     gameset_path.mkdir(parents=True, exist_ok=True)
#
#     with (gameset_path / "_spec_.json").open("w") as f:
#         json.dump(instcontainer_spec, f)
#
#     game_1_path = gameset_path / "1"
#     game_1_path.mkdir(exist_ok=True, parents=True)
#
#     with (game_1_path / "_spec_.json").open("w") as f:
#         json.dump(game_spec, f)
#
#     return mock_inst_root
#
#
# @pytest.fixture
# def temp_root_with_runset(
#     temp_root_with_gameset: tempfile.TemporaryDirectory,
#     instcontainer_spec: Dict,
# ) -> tempfile.TemporaryDirectory:
#     # temp_root_with_gameset contains the dir to the mocked
#     # INST_ROOT, just with the gamesets already setup
#     mock_inst_root = temp_root_with_gameset
#
#     runset_path = Path(mock_inst_root.name, "runsets/bb/baller10")
#     runset_path.mkdir(parents=True, exist_ok=True)
#
#     with (runset_path / "_spec_.json").open("w") as f:
#         json.dump(instcontainer_spec, f)
#
#     run_1_path = runset_path / "1"
#     run_1_path.mkdir(exist_ok=True, parents=True)
#
#     game_1_path = Path(mock_inst_root.name, "gamesets/bb/baller10/1")
#
#     run_spec = {
#         "main": {"class": "MCProcRun"},
#         "run": {
#             "input_game": str(game_1_path),
#             "mcproc_output": "my_file.pickle",
#         },
#     }
#
#     with (run_1_path / "_spec_.json").open("w") as f:
#         json.dump(run_spec, f)
#
#     return mock_inst_root



#         assert Inst(path=TMP_PATH, spec=spec1), "Couldn't create Persistable"
#
#     def test_get(self, spec1):
#         assert Inst.get(spec1, ["main", "my_key1"]) == "my_val1"
#         assert Inst.get(spec1, "main.my_key1") == "my_val1"
#         assert Inst.get(spec1, ["main"]) == spec1["main"]
#         assert Inst.get(spec1, "main") == spec1["main"]
#
#     def test_set(self, spec1):
#         Inst.set(spec1, ["main", "foo"], "bar")
#         assert Inst.get(spec1, ["main", "foo"]) == "bar"
#         Inst.set(spec1, "main.foo", "baz")
#         assert Inst.get(spec1, ["main", "foo"]) == "baz"
#
#         Inst.set(spec1, ["key1"], "value1")
#         assert Inst.get(spec1, ["key1"]) == "value1"
#         Inst.set(spec1, "key1", "value2")
#         assert Inst.get(spec1, ["key1"]) == "value2"
#
#     def test_deep_set(self, spec1):
#         Inst.set(spec1, ["level1", "level2", "level3", "lev4"], "val")
#         assert Inst.get(spec1, ["level1", "level2", "level3", "lev4"]) == "val"
#
#     def test_persistable_get_set(self, spec1):
#         inst = Inst(spec=spec1, path=TMP_PATH)
#         assert Inst.get(inst, ["main", "my_key1"]) == "my_val1"
#         assert Inst.get(inst, ["main"]) == spec1["main"]
#
#     def test_gets(self, spec1):
#         inst = Inst(spec=spec1, path=TMP_PATH)
#         assert Inst.gets(inst, "main.my_key1", "main") == [
#             "my_val1",
#             spec1["main"],
#         ]
#
#     def test_sets(self, spec1):
#         Inst.sets(spec1, "main.foo = bar", "bip.bop.boop=3.14", "bip.zip=7")
#         assert Inst.gets(spec1, "main.foo", "bip.bop.boop", "bip.zip") == [
#             "bar",
#             3.14,
#             7,
#         ]
#
#
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
