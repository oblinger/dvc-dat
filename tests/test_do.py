import os
import sys
from typing import Callable
import pytest
import subprocess

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dvc_dat import Dat, DatManager, Do

do = Dat.do


@pytest.fixture
def empty_do(tmp_path):
    """A do namespace with nothing mounted, in a world of its own (2.3)."""
    return DatManager(dat_folders=[str(tmp_path)]).do


def run_capture(line: str) -> str:
    # Run from the tests directory since ./do is located there
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(line, shell=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, cwd=tests_dir)
    return result.stdout.strip()


def run_capture_tail(line: str) -> str:
    """Run a command and return the last line of the output.
       (test using this will not fail if prints are added to the code)"""
    return run_capture(line).strip().split("\n")[-1]


class TestLoad:
    def test_load(self):
        assert do.load("not_there", default=None) is None
        assert isinstance(do.load("hello_world"), Callable)

    def test_load_with_default(self):
        assert do.load("not_there", default="hello") == "hello"
        assert do.load("not_there", default=None) is None
        assert isinstance(do.load("hello_world", default="hello"), Callable)

    def test_load_subfolder_value(self):
        assert isinstance(do.load("script/hello_world", default="hello"), Callable)

    def test_multiple_values_in_one_loadable(self):
        assert isinstance(do.load("hello_again"), Callable)
        assert isinstance(do.load("hello_again.hella"), Callable)

    def test_do(self):
        assert Dat.manager.run("hello_world") == "hello world!"

    def test_do_with_args_and_return_value(self):
        assert Dat.manager.run("hello_again.salutation",
                  name="hello", emphasis=True, lucky_number=7) == \
               (7, "hello, My lucky number is 7")

    def test_do_on_a_configuration_file(self, capsys):
        Dat.manager.run("hello_config", "Martin")
        assert capsys.readouterr().out == "   Martin, My lucky number is 7\n"

    def test_do_on_a_shadowed_config(self, capsys):
        Dat.manager.run("hello_shadowed_config")
        assert capsys.readouterr().out == "   Hello, My lucky number is 777\n"

    def test_combining_configs_and_code(self):
        result = "a  jackpot   ccc  D  e  fff  g  h  JACKPOT JACKPOT JACKPOT   j  k" + \
            "  lll  m  N  ooo  jackpot   q  rrr  S  t  uuu  v  jackpot   XXX  y"
        assert Dat.manager.run("my_letters") == result

    def test_yaml_constant_loading(self):
        value = {'datasets': ['regression_games', 'baller10', 'volley10', 'arron4'],
                 'metrics': ['team_highlight.money', 'team_highlight.precision',
                             'player_highlight.money', 'basket_stats.money',
                             'p_metric']}
        assert do.load("supported") == value

    def test_yaml_string_spec_parsing(self):
        """Test that YAML string specs (prefixed with 'yaml') are parsed correctly."""
        yaml_spec = """yaml
dat:
  do: hello_world
foo: bar
nested:
  key: value
"""
        do.mount(at="yaml_test", value=yaml_spec)
        loaded = do.load("yaml_test")
        assert isinstance(loaded, dict), "YAML string should be parsed to dict"
        assert loaded["foo"] == "bar"
        assert loaded["nested"]["key"] == "value"
        assert loaded["dat"]["do"] == "hello_world"

    def test_yaml_string_spec_from_file(self, capsys):
        """Test YAML string spec loaded from a .py file works correctly."""
        Dat.manager.run("hello_yaml_config")
        output = capsys.readouterr().out
        assert "YAML GREETER" in output or "888" in output


class TestCommandLine:
    """The `./do` shim onto `cli_main`; `test_cli.py` covers every `dat` verb."""

    def test_usage_message(self):
        lines = run_capture("./do --usage")
        assert 30 < len(lines.split("\n"))

    def test_commandline_fixed_and_key_args(self):
        result = run_capture_tail("./do hello_again.salutation Maxim emphasis=true")
        assert result == "(999, 'Maxim, My lucky number is 999')"

    def test_keyword_values_are_json(self):
        result = run_capture_tail("./do hello_again.salutation Maxim lucky_number=7")
        assert result == "(7, 'Maxim, My lucky number is 7')"

    def test_run_configuration_from_cmdline(self):
        result = run_capture_tail("./do my_letters")
        assert result == ("a  jackpot   ccc  D  e  fff  g  h  "
                          "JACKPOT JACKPOT JACKPOT   j  k  lll  m  N  ooo  jackpot"
                          "   q  rrr  S  t  uuu  v  jackpot   XXX  y")

    def test_tweaking_command_from_cmdline(self):
        line = """./do my_letters --set "dat.title=Re-configured letterator" """ + \
                """--json rules='[[2, "my_letters.triple_it"]]'"""
        expect = """a  bbb  c  ddd  e  fff  g  hhh  i""" + \
                 """  jjj  k  lll  m  nnn  o  ppp  q  rrr  s  ttt  u  vvv  w  xxx  y"""
        assert run_capture_tail(line) == expect

    def test_setting_multiple_params_at_once(self):
        line = """./do my_letters --set dat.title=Quickie --set start=100 --set end=110"""
        expect = """D  e  fff  g  h  JACKPOT JACKPOT JACKPOT   j  k  lll  m"""
        assert run_capture_tail(line) == expect


class TestRegisteringStuff:

    def test_registering_simple_values(self, empty_do):
        do_ = empty_do
        do_.mount(at="foo", value="bar")
        assert do_.load("foo") == "bar"

        do_.mount(at="another.bar", value="baz")
        assert do_.load("another.bar") == "baz"

        do_.mount(at="three.levels.deep", value=333.333)
        assert do_.load("three.levels.deep") == 333.333

    def test_loading_missing_values(self, empty_do):
        do_ = empty_do
        assert do_.load("this.is.not_there", default="hello") == "hello"
        assert do_.load("not_there", default=None) is None

    def test_registering_simple_functions(self, empty_do):
        do_ = empty_do
        do_.mount(at="foo", value=lambda: "bar")
        assert do_.manager.run("foo") == "bar"

    def test_registering_do_fns(self, empty_do):
        do_ = empty_do
        do_.mount(at="foo.bar", value=lambda: "baz")
        assert do_.manager.run("foo.bar") == "baz"

    def test_registering_modules_paths(self, empty_do):
        do_ = empty_do
        path = os.path.join(os.path.dirname(__file__),
                            "test_mounted_folder/script/hello_world.py")
        do_.mount(at="xxx", module=path)
        assert do_.manager.run("xxx.__main__") == "hello world!"
        do_.mount(at="yyy", module="dvc_dat")  # The already loaded 'dvc_dat' module
        from dvc_dat import Dat
        assert do_.load("yyy.Dat") == Dat


class TestTemplatedDatCreationAndDeletion:
    def test_empty_creation_and_deletion(self):
        dat, _ = do._dat_from_template({})
        assert dat, "Couldn't create Persistable"
        assert dat.delete(), "Couldn't delete Persistable"

    def test_creation_and_deletion_with_spec(self):
        spec1 = {"dat": {"name": "test_dats/{YY}-{MM} Dats{unique}"}}
        dat, _ = do._dat_from_template(spec1)
        assert dat, "Couldn't create Persistable"
        assert dat.get_path_name().startswith("test_dats/"), "Wrong path"
        assert dat.delete(), "Couldn't delete Persistable"


class TestDatCallArgs:
    """Arguments fork a new spec; they are never appended at the call site (2.0)."""

    def test_call_args(self, empty_do):
        def foo(_dat, *args, **_kwargs):
            return list(args)
        do_ = empty_do
        do_.mount(at="foo", value=foo)
        do_.mount(at="bar", value={"dat": {"do": "foo"}})
        assert do_.manager.run("bar", 1, 2, 3) == [1, 2, 3]
        do_.mount(at="baz", value={"dat": {"do": "foo", "args": [4, 5, 6]}})
        assert do_.manager.run("baz") == [4, 5, 6]
        assert do_.manager.run("baz", 1, 2, 3) == [1, 2, 3]   # 1.x appended: [4, 5, 6, 1, 2, 3]

    def test_call_kwargs(self, empty_do):
        def foo(_dat, *_args, **kwargs):
            return dict(kwargs)
        do_ = empty_do
        do_.mount(at="foo", value=foo)
        do_.mount(at="bar", value={"dat": {"do": "foo"}})
        assert do_.manager.run("bar", a=1, b=2, c=3) == {"a": 1, "b": 2, "c": 3}
        do_.mount(at="baz", value={"dat": {"do": "foo", "kwargs": {"c": 33, "d": 44}}})
        assert do_.manager.run("baz") == {"c": 33, "d": 44}
        assert do_.manager.run("baz", a=1, b=2, c=3) == {"a": 1, "b": 2, "c": 3, "d": 44}


class TestManagerRun:
    """DAT 1049: `Dat.manager.run(target, ...)` is the one run; `Dat.do` is the namespace only."""

    @pytest.fixture
    def m(self, tmp_path):
        m = DatManager(dat_folders=[str(tmp_path)])
        m.do.mount(at="echo", value=lambda dat, *a, **k: {"name": dat.get_path_name(),
                                                         "args": list(a), "kwargs": dict(k)})
        m.do.mount(at="tmpl", value={"dat": {"do": "echo", "name": "runs/t", "kwargs": {"x": 1}}})
        return m

    def test_a_dat_runs_in_place_and_dat_run_is_the_record(self, m):
        dat = m.create({"dat": {"do": "echo", "args": [3]}}, path="in_place")
        assert m.run(dat) == {"name": "in_place", "args": [3], "kwargs": {}}
        assert isinstance(dat.run, Dat)                          # still the record, not a verb
        record = dat.run.get_results()["dat"]
        assert "run_at" in record and "run_time" in record

    def test_a_dat_with_arguments_forks_beside_it(self, m):
        dat = m.create({"dat": {"do": "echo", "args": [3]}}, path="parent")
        out = m.run(dat, 9, y=2)
        assert out == {"name": "parent_2", "args": [9], "kwargs": {"y": 2}}
        assert dat.run is None                                   # the parent never ran

    def test_a_sealed_dat_is_refused(self, m):
        m.do.mount(at="saves", value=lambda dat: dat.save())
        dat = m.create({"dat": {"do": "saves"}}, path="sealed")
        m.run(dat)
        with pytest.raises(Exception, match="In <Dat") as e:
            m.run(dat)
        assert isinstance(e.value.__cause__, RuntimeError) and "sealed" in str(e.value.__cause__)

    def test_a_spec_name_creates_and_runs(self, m):
        assert m.run("tmpl") == {"name": "runs/t", "args": [], "kwargs": {"x": 1}}

    def test_a_spec_name_with_arguments_forks_the_spec(self, m):
        assert m.run("tmpl", 7, y=2) == {"name": "runs/t", "args": [7], "kwargs": {"x": 1, "y": 2}}

    def test_a_spec_dict_creates_and_runs(self, m):
        spec = {"dat": {"do": "echo", "name": "runs/d"}}
        assert m.run(spec, z=0) == {"name": "runs/d", "args": [], "kwargs": {"z": 0}}

    def test_a_spec_with_no_do_returns_the_dat(self, m):
        dat = m.run({"dat": {"name": "runs/plain"}})
        assert isinstance(dat, Dat) and dat.get_path_name() == "runs/plain" and dat.run is None

    def test_target_exists_use_returns_the_dat_unrun(self, m):
        first = m.run({"dat": {"name": "runs/u"}})
        again = m.run({"dat": {"do": "echo", "name": "runs/u", "target_exists": "use"}})
        assert again.get_path() == first.get_path() and again.run is None

    def test_a_callable_is_called(self, m):
        assert m.run(lambda a, b=0: a + b, 1, b=2) == 3

    def test_a_callable_name_is_called(self, m):
        m.do.mount(at="add", value=lambda a, b=0: a + b)
        assert m.run("add", 1, b=2) == 3

    def test_anything_else_is_refused(self, m):
        with pytest.raises(Exception, match="In 42") as e:
            m.run(42)
        assert isinstance(e.value.__cause__, TypeError)

    def test_the_default_world_runs_through_dat_manager_run(self):
        assert Dat.manager.run("hello_world") == "hello world!"

    def test_dat_do_is_the_namespace_and_not_callable(self, m):
        with pytest.raises(TypeError, match="not callable"):
            Dat.do("hello_world")
        with pytest.raises(TypeError, match="not callable"):
            m.do("tmpl")
        assert Dat.do.load("hello_world") is not None           # the namespace stays
        assert not hasattr(DatManager, "execute")


class TestCleanup:
    def test_cleanup(self):
        os.system("rm -r test_sync_folder/anonymous")  # remove all anon dats
