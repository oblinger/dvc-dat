import os
import sys
from typing import Callable
import pytest
import subprocess

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dvc_dat import do, DoManager


@pytest.fixture
def empty_do_mgr():
    return DoManager()


def run_capture(line: str) -> str:
    result = subprocess.run(line, shell=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    return result.stdout.strip()


class TestLoad:
    def test_load(self):
        assert do.load("not_there", default=None) is None
        assert isinstance(do.load("hello_world"), Callable)

    def test_load_with_default(self):
        assert do.load("not_there", default="hello") == "hello"
        assert do.load("not_there", default=None) is None
        huh = do.load("hello_world", default="hello")
        assert isinstance(huh, Callable)

    def test_multiple_values_in_one_loadable(self):
        assert isinstance(do.load("hello_again"), Callable)
        assert isinstance(do.load("hello_again.hella"), Callable)

    def test_do(self):
        assert do("hello_world") == "hello world!"

    def test_do_with_args_and_return_value(self):
        assert do("hello_again.salutation",
                  name="hello", emphasis=True, lucky_number=7) == \
               (7, "hello, My lucky number is 7")

    def test_do_within_deep_sub_folders(self, capsys):
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
        assert result == "MAXIM, MY LUCKY NUMBER IS 999!\n" + \
               "(999, 'Maxim, My lucky number is 999')"

    def test_run_configuration_from_cmdline(self):
        result = run_capture("./do my_letters")
        assert result == ("The Letterator\na  jackpot   ccc  D  e  fff  g  h  "
                          "JACKPOT JACKPOT JACKPOT   j  k  lll  m  N  ooo  jackpot"
                          "   q  rrr  S  t  uuu  v  jackpot   XXX  y")

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


class TestRegisteringStuff:

    def test_registering_simple_values(self, empty_do_mgr):
        do_ = empty_do_mgr
        do_.mount(at="foo", value="bar")
        assert do_.load("foo") == "bar"

        do_.mount(at="another.bar", value="baz")
        assert do_.load("another.bar") == "baz"

        do_.mount(at="three.levels.deep", value=333.333)
        assert do_.load("three.levels.deep") == 333.333

    def test_loading_missing_values(self, empty_do_mgr):
        do_ = empty_do_mgr
        assert do_.load("this.is.not_there", default="hello") == "hello"
        assert do_.load("not_there", default=None) is None

    def test_registering_simple_functions(self, empty_do_mgr):
        do_ = empty_do_mgr
        do_.mount(at="foo", value=lambda: "bar")
        assert do_("foo") == "bar"

    def test_registering_do_fns(self, empty_do_mgr):
        do_ = empty_do_mgr
        do_.mount(at="foo.bar", value=lambda: "baz")
        assert do_("foo.bar") == "baz"

    def test_registering_modules_paths(self, empty_do_mgr):
        do_ = empty_do_mgr
        path = os.path.join(os.path.dirname(__file__), "test_do_folder/hello_world.py")
        do_.mount(at="xxx", module=path)
        assert do_("xxx.main") == "hello world!"
        do_.mount(at="yyy", module="dvc_dat")  # The already loaded 'dvc_dat' module
        from dvc_dat import dat_config
        assert do_.load("yyy.dat_config") == dat_config


class TestTemplatedDatCreationAndDeletion:
    def test_empty_creation_and_deletion(self):
        from dvc_dat import do
        assert (dat := do.dat_from_template({})), "Couldn't create Persistable"
        assert dat.delete(), "Couldn't delete Persistable"

    def test_creation_and_deletion_with_spec(self):
        from dvc_dat import do
        spec1 = {"main": {"path": "test_dats/{YY}-{MM} Dats{unique}"}}
        assert (dat := do.dat_from_template(spec1)), "Couldn't create Persistable"
        assert dat.get_path_name().startswith("test_dats/"), "Wrong path"
        assert dat.delete(), "Couldn't delete Persistable"


class TestDatCallArgs:
    def test_call_args(self, empty_do_mgr):
        def foo(dat, *args, **_kwargs):
            return list(args)
        do_ = empty_do_mgr
        do_.mount(at="foo", value=foo)
        do_.mount(at="bar", value={"main": {"do": "foo"}})
        assert do_("bar", 1, 2, 3) == [1, 2, 3]
        do_.mount(at="baz", value={"main": {"do": "foo", "args": [4, 5, 6]}})
        assert do_("baz") == [4, 5, 6]
        assert do_("baz", 1, 2, 3) == [4, 5, 6, 1, 2, 3]

    def test_call_kwargs(self, empty_do_mgr):
        def foo(dat, *_args, **kwargs):
            return dict(kwargs)
        do_ = empty_do_mgr
        do_.mount(at="foo", value=foo)
        do_.mount(at="bar", value={"main": {"do": "foo"}})
        assert do_("bar", a=1, b=2, c=3) == {"a": 1, "b": 2, "c": 3}
        do_.mount(at="baz", value={"main": {"do": "foo", "kwargs": {"c": 33, "d": 44}}})
        assert do_("baz") == {"c": 33, "d": 44}
        assert do_("baz", a=1, b=2, c=3) == {"a": 1, "b": 2, "c": 3, "d": 44}
