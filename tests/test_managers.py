"""2.3: a `DatManager` owns its `do`; two worlds in one process stay apart.

The 1.x ownership restored (Dan, 2026-09-22): the manager holds the config and
the namespace, `Dat.create` / `Dat.load` trampoline to `Dat.manager`, and the
module-level `do` is that manager's namespace.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dvc_dat import Dat, DataConfig, DatManager, Do, do  # noqa: E402
from dvc_dat.core import DATA_CONFIG_FILE  # noqa: E402


def echo(dat, *args, **kwargs):
    return {"name": dat.get_path_name(), "args": list(args), "kwargs": dict(kwargs)}


def world(root: Path, tag: str) -> DatManager:
    """A manager on `root`, whose namespace holds a base-chained template that
    only it can see -- the same names in every world, different content."""
    manager = DatManager(DataConfig(cwd=str(root), dat_folders="dats/"))
    manager.do.mount(value=echo, at="fn")
    manager.do.mount(value={"tag": tag, "who": f"world {tag}"}, at="consts")
    manager.do.mount(value={"dat": {"do": "fn", "kwargs": {"tag": tag}}}, at="base")
    manager.do.mount(value={"dat": {"base": "base", "name": f"run_{tag}"},
                            "who": "{consts.who}"}, at="tmpl")
    return manager


@pytest.fixture
def worlds(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    return world(a, "a"), world(b, "b")


class TestTwoWorlds:
    def test_each_runs_its_own_template_into_its_own_folder(self, worlds):
        ma, mb = worlds
        global_folder, global_names = Dat.manager.dat_folder, set(do.keys())

        assert ma.do("tmpl") == {"name": "run_a", "args": [], "kwargs": {"tag": "a"}}
        assert mb.do("tmpl", 7) == {"name": "run_b", "args": [7], "kwargs": {"tag": "b"}}

        dat_a, dat_b = ma.load("run_a"), mb.load("run_b")
        assert dat_a.get_path().startswith(ma.dat_folder)
        assert dat_b.get_path().startswith(mb.dat_folder)
        assert dat_a.get_spec()["who"] == "world a"        # `{}` through its own namespace
        assert dat_b.get_spec()["who"] == "world b"
        assert dat_b.get_spec()["dat"]["kwargs"] == {"tag": "b"}   # `dat.base` through its own
        assert not ma.exists("run_b") and not mb.exists("run_a")
        with pytest.raises(KeyError):
            ma.load("run_b")

        assert Dat.manager.dat_folder == global_folder      # the default world: untouched
        assert set(do.keys()) == global_names
        assert do.load("tmpl", default=None) is None
        assert not Dat.manager.exists("run_a") and not Dat.manager.exists("run_b")

    def test_neither_sees_the_others_mounts(self, worlds):
        ma, mb = worlds
        assert ma.do.load("consts.tag") == "a"
        assert mb.do.load("consts.tag") == "b"
        ma.do.mount(value=1, at="only_a")
        assert mb.do.load("only_a", default=None) is None
        assert do.load("only_a", default=None) is None

    def test_a_dotted_spec_and_its_base_resolve_in_the_managers_namespace(self, worlds):
        ma, mb = worlds
        dat = ma.create("tmpl")
        assert dat.get_path_name() == "run_a"
        assert dat.get_spec()["dat"]["kwargs"] == {"tag": "a"}
        assert "base" not in dat.get_spec()["dat"]
        with pytest.raises(Exception):                     # the default world has no `tmpl`
            Dat.create(spec="tmpl")
        assert mb.expand("{consts.who}") == "world b"
        assert ma.expand_spec({"x": "{consts.tag}"}) == {"x": "a"}

    def test_a_managers_do_is_bound_to_it(self, worlds):
        ma, _ = worlds
        assert ma.do.manager is ma
        assert ma.do.config is ma.config
        assert ma.do is not do


class TestReconfiguration:
    def test_reconfiguring_a_second_manager_leaves_the_default_alone(self, tmp_path):
        before = Dat.manager.dat_folder
        m = DatManager(DataConfig(cwd=str(tmp_path), dat_folders="one/"))
        m.do.mount(value=1, at="kept")
        m.do.configure(DataConfig(cwd=str(tmp_path), dat_folders="two/"))
        assert m.dat_folder.endswith("/two/")
        assert m.do.manager is m                           # same world, new config
        assert m.do.load("kept") == 1                      # mounts survive
        assert Dat.manager.dat_folder == before

    def test_a_bare_do_configures_a_world_of_its_own(self, tmp_path):
        before = Dat.manager.dat_folder
        (tmp_path / DATA_CONFIG_FILE).write_text("dat_folders: mine/\n")
        probe = Do()
        assert probe.config is None
        probe.configure(tmp_path)
        assert probe.manager.dat_folder.endswith("/mine/")
        assert probe.manager is not Dat.manager
        assert Dat.manager.dat_folder == before


class TestTheDefaultWorld:
    def test_dat_create_and_load_trampoline_to_the_manager(self):
        assert Dat.manager is do.manager
        assert Dat.manager.do is do
        name = "managers/trampoline"
        if Dat.manager.exists(name):
            Dat.load(name).delete()
        dat = Dat.create(path=name, spec={"k": "v"})
        assert dat.get_path().startswith(Dat.manager.dat_folder)
        assert Dat.load(name) is Dat.manager.load(name)
        assert Dat.manager.exists(name)
        dat.delete()

    def test_early_mounts_survive_first_use_configuration(self, tmp_path):
        (tmp_path / DATA_CONFIG_FILE).write_text("dat_folders: warehouse/\n")
        probe = (
            "from dvc_dat import do, Dat\n"
            "do.mount(value={'x': 1}, at='early')\n"
            "assert do.config is None and do._manager is None\n"
            "assert do.load('early.x') == 1\n"              # first use configures
            "assert do.config is not None\n"
            "assert Dat.manager is do.manager and Dat.manager.do is do\n"
            "assert do.load('early.x') == 1\n"
            "assert do.load('dt.list') is not None\n"
            "print(Dat.manager.dat_folder)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe], cwd=tmp_path,
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().rstrip("/").endswith("warehouse")
