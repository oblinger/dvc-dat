"""The `dat` command line and the `bin/dat` bootstrap, exercised as processes.

Every case runs a real subprocess: the exit code is half of the contract.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"
BOOT = REPO / "bin" / "dat"


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


def run_boot(*args: str, cwd, env=None):
    """Run the `bin/dat` bootstrap; returns (exit code, stdout, stderr)."""
    done = subprocess.run([str(BOOT), *args], cwd=str(cwd),
                          capture_output=True, text=True, env=env or _env())
    return done.returncode, done.stdout.strip(), done.stderr.strip()


@pytest.fixture
def no_config_dir(tmp_path: Path) -> Path:
    """A directory with no `.dataconfig.yaml` anywhere above it."""
    folder = tmp_path / "elsewhere"
    folder.mkdir()
    for parent in [folder, *folder.parents]:
        if (parent / ".dataconfig.yaml").exists():
            pytest.skip(f"a .dataconfig.yaml sits above {folder}")
    return folder


def make_project(root: Path, python: str = None) -> Path:
    """A minimal dat project: a config, and a main that mounts one script folder
    and hands the command line to `dat.cli_main()`.  `python` names the interpreter
    the config's `run:` uses; None leaves `run:` out."""
    config = ["dat_folders: data/"]
    if python is not None:
        config.append(f"run: {python} -m project_main")
    (root / ".dataconfig.yaml").write_text("\n".join(config) + "\n")
    (root / "project_main.py").write_text(
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "import dvc_dat as dat\n"
        "dat.do.mount(folder=str(Path(__file__).parent / 'scripts'))\n"
        "if __name__ == '__main__':\n"
        "    if os.environ.get('DAT_CLI_CONFIG'):   # launched by the dat bootstrap\n"
        "        sys.exit(dat.cli_main())\n"
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
    def test_bare_dat_prints_usage(self):
        code, out, _ = dat()
        assert code == 0 and "SYNOPSIS" in out and "dat list" in out

    @pytest.mark.parametrize("flag", ["-h", "--help"])
    def test_help(self, flag):
        code, out, _ = dat(flag)
        assert code == 0 and "SYNOPSIS" in out

    @pytest.mark.parametrize("form", ["--version", "version"])
    def test_version(self, form):
        from dvc_dat import __version__
        code, out, _ = dat(form)
        assert (code, out) == (0, __version__)

    def test_version_needs_no_config(self, no_config_dir):
        from dvc_dat import __version__
        code, out, err = dat("--version", cwd=no_config_dir)
        assert (code, out, err) == (0, __version__, "")

    def test_help_needs_no_config(self, no_config_dir):
        code, out, _ = dat("--help", cwd=no_config_dir)
        assert code == 0 and "SYNOPSIS" in out

    @pytest.mark.parametrize("form", ["info", "--info"])
    def test_info(self, form):
        code, out, _ = dat(form)
        assert code == 0
        assert "Dat version" in out and "test_sync_folder" in out
        assert str(TESTS / ".dataconfig.yaml") in out

    def test_list(self):
        code, out, _ = dat("list")
        assert code == 0 and "hello_world" in out and "my_letters" in out

    def test_list_with_prefix(self):
        code, out, _ = dat("list", "letter")
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
        assert "no_such_thing" in err and err.startswith("dat:")

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
    def test_keyword_values_are_yaml_scalars(self):
        code, out, _ = dat("echo_args", "n=7", "b=true", "l=[1, 2]",
                           'q="x"', "w=bare", "f=1.5", "e=")
        assert code == 0
        assert out == ("args=[] kwargs={b=True, e=None, f=1.5, l=[1, 2], "
                       "n=7, q='x', w='bare'}")

    def test_fixed_args_are_yaml_scalars(self):
        code, out, _ = dat("echo_args", "7", "true", "[1, 2]", '"x"', "bare")
        assert (code, out) == (0, "args=[7, True, [1, 2], 'x', 'bare'] kwargs={}")

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
        assert (code, out) == (0, "do('echo_args', 7, k=1)")

    def test_set(self):
        line = ["my_letters", "--set", "dat.title=Re-configured letterator",
                "--json", "rules", '[[2, "my_letters.triple_it"]]']
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
        code, _, err = dat("my_letters", "--json", "rules", "[not json")
        assert code == 1 and "JSON" in err

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


class TestBootstrap:
    def test_no_args_prints_the_same_usage(self, tmp_path):
        nested = make_project(tmp_path, python=sys.executable)
        code, out, _ = run_boot(cwd=nested)
        assert code == 0 and "SYNOPSIS" in out

    def test_verbs_pass_through(self, tmp_path):
        nested = make_project(tmp_path, python=sys.executable)
        code, out, _ = run_boot("list", "greet", cwd=nested)
        assert code == 0 and "greet" in out

    def test_the_main_is_its_own_without_the_bootstrap(self, tmp_path):
        """DAT_CLI_CONFIG tells a main it was launched by `dat`; run directly it
        does its own thing."""
        make_project(tmp_path)
        env = _env()
        env.pop("DAT_CLI_CONFIG", None)
        done = subprocess.run([sys.executable, "-m", "project_main"], cwd=str(tmp_path),
                              capture_output=True, text=True, env=env)
        assert (done.returncode, done.stdout.strip()) == (0, "own main")

    def test_no_config_above_exits_3(self, no_config_dir):
        code, out, err = run_boot("greet", cwd=no_config_dir)
        assert code == 3 and out == ""
        assert ".dataconfig.yaml" in err

    def test_end_to_end_from_a_nested_folder(self, tmp_path):
        nested = make_project(tmp_path, python=sys.executable)
        code, out, err = run_boot("greet", "dan", "loud=true", cwd=nested)
        assert (code, out, err) == (0, "HELLO DAN", "")

    def test_run_key_is_a_command(self, tmp_path):
        make_wrapper(tmp_path / "myenv", "COMMAND-FORM")
        nested = make_project(tmp_path, python=f"{tmp_path}/myenv/bin/python")
        code, out, _ = run_boot("greet", cwd=nested)
        assert code == 0 and out.splitlines() == ["COMMAND-FORM", "hello world"]

    def test_run_key_is_relative_to_the_config(self, tmp_path):
        make_wrapper(tmp_path / "myenv", "RELATIVE-FORM")
        nested = make_project(tmp_path, python="myenv/bin/python")
        code, out, _ = run_boot("greet", cwd=nested)
        assert code == 0 and out.splitlines() == ["RELATIVE-FORM", "hello world"]

    def test_venv_beside_the_config_is_the_default(self, tmp_path):
        """No `run:` -> `.venv/bin/python -m dvc_dat`: the library's own main, so
        the namespace is Python's and nothing of the project's is mounted."""
        make_wrapper(tmp_path / ".venv", "DOT-VENV")
        nested = make_project(tmp_path)
        code, out, _ = run_boot("os.sep", cwd=nested)
        assert code == 0 and out.splitlines() == ["DOT-VENV", os.sep]
        code, _, err = run_boot("greet", cwd=nested)
        assert code == 2 and "cannot load 'greet'" in err

    def test_dat_run_overrides_the_config(self, tmp_path):
        make_wrapper(tmp_path / "override", "ENV-FORM")
        nested = make_project(tmp_path, python=sys.executable)
        env = _env(DAT_RUN=f"{tmp_path}/override/bin/python -m project_main")
        code, out, _ = run_boot("greet", cwd=nested, env=env)
        assert code == 0 and out.splitlines() == ["ENV-FORM", "hello world"]

    def test_a_missing_command_fails_visibly(self, tmp_path):
        nested = make_project(tmp_path, python="/no/such/python")
        code, _, err = run_boot("greet", cwd=nested)
        assert code == 1 and "/no/such/python" in err


class TestImportRoot:
    """The config folder is the project's import root (T010)."""

    @staticmethod
    def _project(root: Path) -> Path:
        (root / ".dataconfig.yaml").write_text("dat_folders: data/\n")
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

    def test_x_from_a_subfolder(self, tmp_path):
        notes = self._project(tmp_path)
        code, out, err = run_boot("mypkg.job.run", cwd=notes,
                               env=_env(DAT_RUN=f"{sys.executable} -m dvc_dat"))
        assert (code, out) == (0, "42"), err
