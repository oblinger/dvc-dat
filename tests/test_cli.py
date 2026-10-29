"""The command line (`just run`, `x`) and its `dvc_dat.just` recipes, exercised as processes.

Every case runs a real subprocess: the exit code is half of the contract.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"
X = REPO / "bin" / "x"
RECIPES = REPO / "dvc_dat" / "dvc_dat.just"
needs_just = pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")


def _env(**extra: str) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{REPO}:{TESTS}"
    env.pop("DAT_RUN", None)
    env.update(extra)
    return env


def dat(*args: str, cwd=TESTS, env=None):
    """Run one `dat` command line inside the test namespace -- `tests/mounts.py`
    run as a main, the way a project's own main runs `dat.cli_main()`; returns
    (exit code, stdout, stderr)."""
    done = subprocess.run([sys.executable, "-m", "mounts", *args], cwd=str(cwd),
                          capture_output=True, text=True, env=env or _env())
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def run_x(*args: str, cwd, env=None):
    """Run `x` (`just run`); returns (exit code, stdout, stderr)."""
    done = subprocess.run([str(X), *args], cwd=str(cwd),
                          capture_output=True, text=True, env=env or _env())
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def justfile(root: Path) -> None:
    """A project's justfile: dvc-dat's recipes imported."""
    (root / "justfile").write_text(f"import '{RECIPES}'\n")


@pytest.fixture
def no_config_dir(tmp_path: Path) -> Path:
    """A directory with no `.datconfig.yaml` anywhere above it."""
    folder = tmp_path / "elsewhere"
    folder.mkdir()
    justfile(folder)
    for parent in [folder, *folder.parents]:
        if (parent / ".datconfig.yaml").exists():
            pytest.skip(f"a .datconfig.yaml sits above {folder}")
    return folder


def make_project(root: Path, python: str = None) -> Path:
    """A minimal dat project: a config, and a main that mounts one script folder
    and hands the command line to `dat.cli_main()`.  `python` names the interpreter
    the config's `run:` uses; None leaves `run:` out."""
    config = ["dat_folders: data/"]
    if python is not None:
        config.append(f"run: {python} -m project_main")
    (root / ".datconfig.yaml").write_text("\n".join(config) + "\n")
    justfile(root)
    (root / "project_main.py").write_text(
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "from dvc_dat import Dat\n"
        "Dat.ns.mount(folder=str(Path(__file__).parent / 'scripts'))\n"
        "if __name__ == '__main__':\n"
        "    if os.environ.get('DAT_CLI_CONFIG'):   # launched by `just run`\n"
        "        sys.exit(Dat.cli_main())\n"
        "    print('own main')\n"
    )
    (root / "scripts").mkdir()
    (root / "scripts" / "greet.py").write_text(
        "def __main__(who='world', *, loud=False):\n"
        "    line = f'hello {who}'\n"
        "    return line.upper() if loud else line\n"
    )
    nested = root / "nested" / "deep"
    nested.mkdir(parents=True)
    return nested


def make_wrapper(folder: Path, marker: str) -> Path:
    """A `bin/python` that announces itself and then execs the real interpreter."""
    (folder / "bin").mkdir(parents=True)
    wrapper = folder / "bin" / "python"
    wrapper.write_text(f'#!/bin/sh\necho "{marker}"\nexec "{sys.executable}" "$@"\n')
    wrapper.chmod(0o755)
    return wrapper


class TestVerbs:
    def test_no_target_prints_usage(self):
        code, out, _ = dat()
        assert code == 0 and "SYNOPSIS" in out and "x --list" in out

    @pytest.mark.parametrize("flag", ["-h", "--help"])
    def test_help(self, flag):
        code, out, _ = dat(flag)
        assert code == 0 and "SYNOPSIS" in out

    def test_version(self):
        from dvc_dat import __version__
        code, out, _ = dat("--version")
        assert (code, out) == (0, __version__)

    def test_version_needs_no_config(self, no_config_dir):
        from dvc_dat import __version__
        code, out, err = dat("--version", cwd=no_config_dir)
        assert (code, out, err) == (0, __version__, "")

    def test_help_needs_no_config(self, no_config_dir):
        code, out, _ = dat("--help", cwd=no_config_dir)
        assert code == 0 and "SYNOPSIS" in out

    def test_info(self):
        code, out, _ = dat("--info")
        assert code == 0
        assert "Dat version" in out and "test_sync_folder" in out
        assert str(TESTS / ".datconfig.yaml") in out

    def test_list(self):
        code, out, _ = dat("--list")
        assert code == 0 and "hello_world" in out and "my_letters" in out

    @pytest.mark.parametrize("word", ["list", "info", "version"])
    def test_a_bare_word_is_always_a_target(self, word):
        code, _, err = dat(word)
        assert code == 2 and f"cannot load {word!r}" in err

    def test_list_shows_the_one_builtin_mount(self):
        code, out, _ = dat("--list", "d")
        names = [line.split()[0] for line in out.splitlines()[1:]]
        assert code == 0 and "dt" in names and "dat_tools" not in names

    def test_dt_list_is_the_list_command(self):
        assert dat("dt.list", "letter")[1] == dat("--list", "letter")[1]

    def test_list_with_prefix(self):
        code, out, _ = dat("--list", "letter")
        assert code == 0 and "letterator" in out and "hello_world" not in out

    def test_do_verb(self):
        assert dat("hello_world") == (0, "hello world!\nhello world!", "")

    def test_shorthand_is_do(self):
        code, _, err = dat("do", "hello_world")   # `do` is not a verb any more
        assert code == 2 and "cannot load 'do'" in err

    def test_shorthand_on_a_template(self):
        code, out, _ = dat("my_letters")
        assert code == 0 and out.endswith("XXX  y")

    def test_unloadable_target_exits_2(self):
        code, out, err = dat("no_such_thing")
        assert code == 2 and out == ""
        assert "no_such_thing" in err and err.startswith("run:")

    def test_unloadable_shorthand_exits_2(self):
        assert dat("no_such_thing")[0] == 2

    def test_a_failing_run_exits_1(self):
        code, _, err = dat("hello_again.salutation", "bogus_keyword=1")
        assert code == 1
        assert "bogus_keyword" in err and "Traceback" not in err

    def test_dat_debug_shows_the_traceback(self):
        code, _, err = dat("hello_again.salutation", "bogus_keyword=1",
                           env=_env(DAT_DEBUG="1"))
        assert code != 0 and "Traceback" in err

    def test_unknown_option_exits_1(self):
        code, _, err = dat("hello_world", "--emphasis")
        assert code == 1 and "KEY=VALUE" in err

    def test_do_with_no_target_exits_1(self):
        code, _, err = dat("--dry-run")
        assert code == 1 and "TARGET" in err


class TestArguments:
    def test_keyword_values_are_json_else_the_text(self):
        """DAT 1041: one k=v grammar; v is JSON, else the string exactly as typed."""
        code, out, _ = dat("echo_args", "n=12", "x=1.5", "flag=true", "z=null", "ids=[1,2]",
                           'cfg={"a":1}', "start=2026-01-01", "name=foo", 'q="12"', "e=",
                           "nan=NaN", "y=yes")
        assert code == 0
        assert out == ("args=[] kwargs={cfg={'a': 1}, e='', flag=True, ids=[1, 2], "
                       "n=12, name='foo', nan='NaN', q='12', start='2026-01-01', "
                       "x=1.5, y='yes', z=None}")

    def test_fixed_args_are_json_else_the_text(self):
        code, out, _ = dat("echo_args", "7", "true", "[1, 2]", '"x"', "bare", "2026-01-01")
        assert (code, out) == (0, "args=[7, True, [1, 2], 'x', 'bare', '2026-01-01'] kwargs={}")

    def test_colon_equals_is_no_notation(self):
        """`k:=v` is gone (DAT 1041): it is not NAME=, so it is a fixed word, as typed."""
        assert dat("echo_args", "k:=3") == (0, "args=['k:=3'] kwargs={}", "")

    def test_arg_value_is_the_one_grammar(self):
        from dvc_dat.do import arg_value
        cases = {"12": 12, "1.5": 1.5, "true": True, "null": None, "[1,2]": [1, 2],
                 '{"a":1}': {"a": 1}, "2026-01-01": "2026-01-01", "foo": "foo", '"12"': "12",
                 "": "", "NaN": "NaN", "Infinity": "Infinity", "yes": "yes", "1e3": 1000.0}
        assert {text: arg_value(text) for text in cases} == cases
        assert type(arg_value("12")) is int and type(arg_value('"12"')) is str

    def test_set_value_is_json_else_the_text(self):
        from dvc_dat.do import _parse_argv
        overrides, _, _, _ = _parse_argv(["t", "--set", "a.d=2026-01-01", "--set", "a.n=3"])
        assert overrides == [("a.d", "2026-01-01"), ("a.n", 3)]

    def test_fixed_and_keyword_args_together(self):
        code, out, _ = dat("echo_args", "one", "2", "k=3")
        assert (code, out) == (0, "args=['one', 2] kwargs={k=3}")

    def test_double_dash_ends_the_options(self):
        code, out, _ = dat("echo_args", "--", "--not-an-option", "k=3")
        assert (code, out) == (0, "args=['--not-an-option', 'k=3'] kwargs={}")

    def test_target_name_is_not_a_scalar(self):
        code, out, _ = dat("hello_world")
        assert (code, out) == (0, "hello world!\nhello world!")

    def test_keyword_args_reach_a_function(self):
        code, out, _ = dat("hello_again.salutation", "Maxim",
                           "emphasis=true", "lucky_number=7")
        assert code == 0
        assert out.endswith("(7, 'Maxim, My lucky number is 7')")

    def test_print_shows_the_call(self):
        code, out, _ = dat("echo_args", "7", "k=1", "--dry-run")
        assert (code, out) == (0, "Dat.manager.run('echo_args', 7, k=1)")

    def test_set(self):
        line = ["my_letters", "--set", "dat.title=Re-configured letterator",
                "--json", 'rules=[[2, "my_letters.triple_it"]]']
        code, out, _ = dat(*line)
        assert code == 0
        assert out.endswith("a  bbb  c  ddd  e  fff  g  hhh  i  jjj  k  lll  m"
                            "  nnn  o  ppp  q  rrr  s  ttt  u  vvv  w  xxx  y")

    def test_set_repeats(self):
        code, out, _ = dat("my_letters", "--set", "dat.title=Quickie",
                           "--set", "start=100", "--set", "end=110")
        assert code == 0
        assert out.endswith("D  e  fff  g  h  JACKPOT JACKPOT JACKPOT   j  k  lll  m")

    def test_illegal_json_exits_1(self):
        code, _, err = dat("my_letters", "--json", "rules=[not json")
        assert code == 1 and "JSON" in err

    def test_json_needs_key_equals_value(self):
        code, _, err = dat("my_letters", "--json", "rules", "[[2, 3]]")
        assert code == 1 and "--json needs DOTTED.KEY=VALUE" in err

    def test_json_repeats_and_mixes_with_set(self):
        code, out, _ = dat("my_letters", "--json", "start=100", "--json", "end=110",
                           "--set", "dat.title=Quickie", "--dry-run")
        assert code == 0 and "'start': 100" in out and "'end': 110" in out

    def test_set_on_a_function_exits_1(self):
        code, _, err = dat("hello_world", "--set", "a.b=1")
        assert code == 1 and "--set" in err

    def test_missing_operand_exits_1(self):
        code, _, err = dat("my_letters", "--set", "dat.title")   # no '='
        assert code == 1 and "--set" in err

    def test_usage_of_a_target_without_one(self):
        code, out, _ = dat("hello_world", "--usage")
        assert code == 0 and "SYNOPSIS" in out

    def test_usage_with_no_target(self):
        code, out, _ = dat("--usage")
        assert code == 0 and "SYNOPSIS" in out


@needs_just
class TestRun:
    def test_no_args_prints_the_same_usage(self, tmp_path):
        nested = make_project(tmp_path, python=sys.executable)
        code, out, _ = run_x(cwd=nested)
        assert code == 0 and "SYNOPSIS" in out

    def test_verbs_pass_through(self, tmp_path):
        nested = make_project(tmp_path, python=sys.executable)
        code, out, _ = run_x("--list", "greet", cwd=nested)
        assert code == 0 and "greet" in out

    def test_the_main_is_its_own_without_the_bootstrap(self, tmp_path):
        """DAT_CLI_CONFIG tells a main it was launched by `just run`; run directly
        it does its own thing."""
        make_project(tmp_path)
        env = _env()
        env.pop("DAT_CLI_CONFIG", None)
        done = subprocess.run([sys.executable, "-m", "project_main"], cwd=str(tmp_path),
                              capture_output=True, text=True, env=env)
        assert (done.returncode, done.stdout.strip()) == (0, "own main")

    def test_no_config_above_exits_3(self, no_config_dir):
        code, out, err = run_x("greet", cwd=no_config_dir)
        assert code == 3 and out == ""
        assert ".datconfig.yaml" in err

    def test_end_to_end_from_a_nested_folder(self, tmp_path):
        nested = make_project(tmp_path, python=sys.executable)
        code, out, err = run_x("greet", "dan", "loud=true", cwd=nested)
        assert (code, out, err) == (0, "HELLO DAN", "")

    def test_run_key_is_a_command(self, tmp_path):
        make_wrapper(tmp_path / "myenv", "COMMAND-FORM")
        nested = make_project(tmp_path, python=f"{tmp_path}/myenv/bin/python")
        code, out, _ = run_x("greet", cwd=nested)
        assert code == 0 and out.splitlines() == ["COMMAND-FORM", "hello world"]

    def test_run_key_is_relative_to_the_config(self, tmp_path):
        make_wrapper(tmp_path / "myenv", "RELATIVE-FORM")
        nested = make_project(tmp_path, python="myenv/bin/python")
        code, out, _ = run_x("greet", cwd=nested)
        assert code == 0 and out.splitlines() == ["RELATIVE-FORM", "hello world"]

    def test_mounts_is_list(self, tmp_path):
        nested = make_project(tmp_path, python=sys.executable)
        done = subprocess.run(["just", "mounts", "greet"], cwd=str(nested), capture_output=True,
                              text=True, env=_env())
        assert done.returncode == 0 and "greet" in done.stdout

    def test_venv_beside_the_config_is_the_default(self, tmp_path):
        """No `run:` -> `.venv/bin/python -m dvc_dat`: the library's own main, so
        the namespace is Python's and nothing of the project's is mounted."""
        make_wrapper(tmp_path / ".venv", "DOT-VENV")
        nested = make_project(tmp_path)
        code, out, _ = run_x("os.sep", cwd=nested)
        assert code == 0 and out.splitlines() == ["DOT-VENV", os.sep]
        code, _, err = run_x("greet", cwd=nested)
        assert code == 2 and "cannot load 'greet'" in err

    def test_dat_run_overrides_the_config(self, tmp_path):
        make_wrapper(tmp_path / "override", "ENV-FORM")
        nested = make_project(tmp_path, python=sys.executable)
        env = _env(DAT_RUN=f"{tmp_path}/override/bin/python -m project_main")
        code, out, _ = run_x("greet", cwd=nested, env=env)
        assert code == 0 and out.splitlines() == ["ENV-FORM", "hello world"]

    def test_a_missing_command_fails_visibly(self, tmp_path):
        nested = make_project(tmp_path, python="/no/such/python")
        code, _, err = run_x("greet", cwd=nested)
        assert code == 1 and "/no/such/python" in err


class TestImportRoot:
    """The config folder is the project's import root (T010)."""

    @staticmethod
    def _project(root: Path) -> Path:
        (root / ".datconfig.yaml").write_text("dat_folders: data/\n")
        (root / "mypkg").mkdir()
        (root / "mypkg" / "__init__.py").write_text("")
        (root / "mypkg" / "job.py").write_text("def run():\n    return 42\n")
        notes = root / "notes"
        notes.mkdir()
        return notes

    def test_a_projects_own_module_resolves_from_a_subfolder(self, tmp_path):
        notes = self._project(tmp_path)
        code, out, err = dat("mypkg.job.run", cwd=notes)
        assert (code, out) == (0, "42"), err

    def test_a_projects_own_module_resolves_from_the_root(self, tmp_path):
        self._project(tmp_path)
        code, out, err = dat("mypkg.job.run", cwd=tmp_path)
        assert (code, out) == (0, "42"), err

    @needs_just
    def test_x_from_a_subfolder(self, tmp_path):
        notes = self._project(tmp_path)
        justfile(tmp_path)
        code, out, err = run_x("mypkg.job.run", cwd=notes,
                               env=_env(DAT_RUN=f"{sys.executable} -m dvc_dat"))
        assert (code, out) == (0, "42"), err


def make_ledger_project(root: Path, hand: str = "", targets: bool = True) -> None:
    """A project with a ledger: `ledger:` in the config and the package `proj` mounted on it
    (`mounts:`, its db/mount rows: its names are the ledger's, DAT 1046), a main handing the line to
    `cli_main`, and a justfile importing the generated commands."""
    from dvc_dat.ledger import Ledger
    (root / ".datconfig.yaml").write_text(
        f"ledger: .dat/ledger\nmounts:\n  proj: proj\nrun: {sys.executable} -m ledger_main\n")
    Ledger(root / ".dat" / "ledger", create=True)
    targets_line = "import? '.dat/targets.just'\n" if targets else ""
    (root / "justfile").write_text(f"import '{RECIPES}'\n{targets_line}{hand}")
    (root / "proj").mkdir()
    (root / "proj" / "__init__.py").write_text("")
    (root / "proj" / "fns.py").write_text(
        "from dvc_dat.just import command\n"
        "from dvc_dat.ledger import ledger_fn\n"
        "\n"
        "@command(args='n=…', help='double n')\n"
        "@ledger_fn\n"
        "def double(rev, *, n: int) -> int:\n"
        "    return n * 2\n"
        "\n"
        "@command(args='', help='a name the justfile already has')\n"
        "@ledger_fn\n"
        "def hand(rev) -> int:\n"
        "    return 0\n"
        "\n"
        "@ledger_fn\n"
        "def span(rev, *, start: str, end: str, n: int) -> str:\n"
        "    return f'{type(start).__name__} {start} {end} {type(n).__name__}'\n"
        "\n"
        "def plain(dat, n=1):\n"
        "    dat.get_results()['out'] = n\n"
        "    dat.save()\n"
    )
    (root / "ledger_main.py").write_text(
        "import sys\n"
        "from dvc_dat import Dat\n"
        "if __name__ == '__main__':\n"
        "    sys.exit(Dat.cli_main())\n"
    )
    (root / ".gitignore").write_text(".dat/\ndata/\n")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "project"]):
        subprocess.run(git + args, cwd=str(root), check=True, capture_output=True)


@needs_just
class TestLedgerRun:
    """With `ledger:` in the config, `just run` is `rev.run` (F447 Q40 (A), DAT 1046)."""

    def test_a_function_runs_then_hits(self, tmp_path):
        make_ledger_project(tmp_path)
        code, out, err = run_x("proj.fns.double", "n=3", cwd=tmp_path)
        assert code == 0 and out.startswith("ran  "), err
        code, out, err = run_x("proj.fns.double", "n=3", cwd=tmp_path)
        assert code == 0 and out.startswith("hit  "), err

    def test_a_spec_file_names_its_function_in_main(self, tmp_path):
        make_ledger_project(tmp_path)
        (tmp_path / "d.yaml").write_text("main: proj.fns.double\nn: 3\n")
        assert run_x("proj.fns.double", "n=3", cwd=tmp_path)[0] == 0
        code, out, err = run_x("d.yaml", cwd=tmp_path)
        assert code == 0 and out.startswith("hit  "), err
        code, out, err = run_x("d.yaml", "n=4", cwd=tmp_path)        # the line's key wins
        assert code == 0 and out.startswith("ran  "), err

    def test_alias_names_the_result(self, tmp_path):
        make_ledger_project(tmp_path)
        code, out, err = run_x("proj.fns.double", "n=5", "alias=ten", cwd=tmp_path)
        assert code == 0 and out.split()[:2] == ["ran", "ten"], err
        from dvc_dat.ledger import Ledger
        assert Ledger(tmp_path / ".dat" / "ledger").at().load("ten").obj == 10

    def test_an_undecorated_function_is_a_dats_run_function(self, tmp_path):
        make_ledger_project(tmp_path)
        code, out, err = run_x("proj.fns.plain", "n=2", cwd=tmp_path)
        assert code == 0 and out.split()[:2] == ["ran", "anonymous/Dat"] and "out=2" in out, err
        code, out, err = run_x("proj.fns.plain", "n=2", cwd=tmp_path)
        assert code == 0 and out.split()[:2] == ["hit", "anonymous/Dat"], err

    def test_an_unknown_name_does_not_load(self, tmp_path):
        make_ledger_project(tmp_path)
        code, _, err = run_x("proj.fns.nothing", cwd=tmp_path)
        assert code == 2 and "nothing" in err

    def test_a_date_reaches_the_function_as_a_string(self, tmp_path):
        """DAT 1041: `start=2026-01-01` was a YAML date, refused as not JSON-encodable."""
        make_ledger_project(tmp_path)
        code, out, err = run_x("proj.fns.span", "start=2026-01-01", "end=2027-01-01", "n=2",
                               "alias=year", cwd=tmp_path)
        assert code == 0 and out.startswith("ran  "), err
        from dvc_dat.ledger import Ledger
        assert Ledger(tmp_path / ".dat" / "ledger").at().load("year").obj == "str 2026-01-01 2027-01-01 int"

    def test_dry_run_shows_the_eval(self, tmp_path):
        make_ledger_project(tmp_path)
        code, out, _ = run_x("proj.fns.double", "n=3", "--dry-run", cwd=tmp_path)
        assert (code, out) == (0, "rev.run('proj.fns.double', n=3)")


def make_dat_spec_project(root: Path) -> None:
    """The ledger project with a dat spec at `proj.specs.twice` (a declared command) and its run
    function in `proj.runs`, both under the ledger's mount."""
    make_ledger_project(root)
    (root / "proj" / "runs.py").write_text(
        "from pathlib import Path\n"
        "\n"
        "def twice(dat, n=1):\n"
        "    Path(dat.get_path(), 'out.txt').write_text(str(2 * n))\n"
        "    dat.get_results()['out'] = 2 * n\n"
        "    dat.save()\n"
    )
    (root / "proj" / "specs").mkdir()
    (root / "proj" / "specs" / "twice.yaml").write_text(
        "dat:\n  name: twice/n{unique}\n  do: proj.runs.twice\n  kwargs: {n: 1}\ncommand: true\n")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    for args in (["add", "."], ["commit", "-q", "-m", "specs"]):
        subprocess.run(git + args, cwd=str(root), check=True, capture_output=True)


@needs_just
class TestLedgerDatRun:
    """With `ledger:` in the config, `just run <dat spec>` is `rev.run` of the spec (DAT 1038, 1046)."""

    def test_a_spec_runs_then_hits(self, tmp_path):
        make_dat_spec_project(tmp_path)
        code, out, err = run_x("proj.specs.twice", "n=3", cwd=tmp_path)
        assert code == 0 and out.split() == ["ran", "twice/n", "n=3", "out=6"], err
        code, out, err = run_x("proj.specs.twice", "n=3", cwd=tmp_path)
        assert code == 0 and out.split() == ["hit", "twice/n", "n=3", "out=6"], err
        code, out, err = run_x("proj.specs.twice", "n=4", cwd=tmp_path)
        assert code == 0 and out.split()[:2] == ["ran", "twice/n_2"], err

    def test_alias_names_the_dat(self, tmp_path):
        make_dat_spec_project(tmp_path)
        code, out, err = run_x("proj.specs.twice", "n=5", "alias=ten", cwd=tmp_path)
        assert code == 0 and out.split()[:2] == ["ran", "ten"], err
        from dvc_dat.ledger import Ledger
        assert Ledger(tmp_path / ".dat" / "ledger").at().load("ten").get_results()["out"] == 10

    def test_a_spec_with_command_is_a_recipe(self, tmp_path):
        make_dat_spec_project(tmp_path)
        assert run_x("proj.specs.twice", cwd=tmp_path)[0] == 0
        text = (tmp_path / ".dat" / "targets.just").read_text()
        assert "twice *args:" in text and "run 'proj.specs.twice'" in text
        done = subprocess.run(["just", "twice"], cwd=str(tmp_path), capture_output=True, text=True, env=_env())
        assert done.returncode == 0 and done.stdout.startswith("hit  twice/n"), done.stderr

    def test_dry_run_shows_the_run(self, tmp_path):
        make_dat_spec_project(tmp_path)
        code, out, _ = run_x("proj.specs.twice", "n=3", "--dry-run", cwd=tmp_path)
        assert (code, out) == (0, "rev.run('proj.specs.twice', n=3)")


@needs_just
class TestTargets:
    """`.dat/targets.just`: one recipe per mounted `@command` (A64, A65, A67)."""

    def test_run_writes_the_commands_and_skips_a_hand_recipe(self, tmp_path):
        make_ledger_project(tmp_path, hand="hand:\n    @echo hand\n")
        code, _, err = run_x("proj.fns.double", "n=2", cwd=tmp_path)
        assert code == 0, err
        text = (tmp_path / ".dat" / "targets.just").read_text()
        assert "double *args:" in text and "hand *args:" not in text
        assert "1 command(s)" in err and "fns.hand (hand is a recipe in the justfile)" in err
        done = subprocess.run(["just", "double", "n=2"], cwd=str(tmp_path), capture_output=True,
                              text=True, env=_env())
        assert done.returncode == 0 and done.stdout.startswith("hit  "), done.stderr
        listing = subprocess.run(["just", "--list"], cwd=str(tmp_path), capture_output=True,
                                 text=True, env=_env()).stdout
        assert "double *args" in listing and "# n=…  double n" in listing

    def test_a_hand_recipe_added_after_generation_wins(self, tmp_path):
        """cli.md: a name the justfile already has is skipped, the hand recipe wins, also when the
        hand recipe arrives after `.dat/targets.just` generated that name."""
        make_ledger_project(tmp_path)
        code, _, err = run_x("proj.fns.double", "n=2", cwd=tmp_path)
        assert code == 0, err
        assert "double *args:" in (tmp_path / ".dat" / "targets.just").read_text()
        jf = tmp_path / "justfile"
        jf.write_text(jf.read_text() + "double:\n    @echo by-hand\n")
        done = subprocess.run(["just", "double"], cwd=str(tmp_path), capture_output=True, text=True,
                              env=_env())
        assert done.returncode == 0 and done.stdout.strip() == "by-hand", done.stderr
        code, _, err = run_x("proj.fns.double", "n=2", cwd=tmp_path)     # the next run skips it
        assert code == 0 and "fns.double (double is a recipe in the justfile)" in err, err
        assert "double *args:" not in (tmp_path / ".dat" / "targets.just").read_text()

    def test_a_fresh_file_is_not_rewritten(self, tmp_path):
        make_ledger_project(tmp_path)
        run_x("proj.fns.double", "n=2", cwd=tmp_path)
        _, _, err = run_x("proj.fns.double", "n=2", cwd=tmp_path)
        assert "targets:" not in err

    def test_no_import_no_file(self, tmp_path):
        make_ledger_project(tmp_path, targets=False)
        code, _, err = run_x("proj.fns.double", "n=2", cwd=tmp_path)
        assert code == 0, err
        assert not (tmp_path / ".dat" / "targets.just").exists()


class TestCommand:
    def test_budgets(self):
        from dvc_dat.just import ARGS_MAX, HELP_MAX, command
        command(args="a" * ARGS_MAX, help="h" * HELP_MAX + "\n" + "h" * HELP_MAX)
        for args, help in [("a" * (ARGS_MAX + 1), "h"), ("", "h" * (HELP_MAX + 1)),
                           ("", "one\ntwo\nthree"), ("", "")]:
            with pytest.raises(ValueError):
                command(args=args, help=help)

    def test_a_spec_is_a_command_by_its_key(self):
        from dvc_dat.just import declared
        assert declared({"main": "m.f", "command": True}) == {"args": "", "help": ""}
        assert declared({"main": "m.f", "command": {"help": "h"}}) == {"args": "", "help": "h"}
        assert declared({"main": "m.f"}) is None
