"""2.3: a `DatManager` owns its `do`; two worlds in one process stay apart.

The 1.x ownership restored (Dan, 2026-09-22): the manager holds the folders and
the namespace, `Dat.create` / `Dat.load` trampoline to `Dat.manager`, and the
module-level `do` forwards to that manager's namespace.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dvc_dat import Dat, DatManager, Do, do  # noqa: E402
from dvc_dat.core import DAT_CONFIG_FILE  # noqa: E402


def echo(dat, *args, **kwargs):
    return {"name": dat.get_path_name(), "args": list(args), "kwargs": dict(kwargs)}


def world(root: Path, tag: str) -> DatManager:
    """A manager on `root`, whose namespace holds a base-chained template that
    only it can see -- the same names in every world, different content."""
    manager = DatManager(dat_folders=[str(root / "dats")])
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
        global_folder, global_names = Dat.manager._dat_folders, set(do.keys())

        assert ma.do("tmpl") == {"name": "run_a", "args": [], "kwargs": {"tag": "a"}}
        assert mb.do("tmpl", 7) == {"name": "run_b", "args": [7], "kwargs": {"tag": "b"}}

        dat_a, dat_b = ma.load("run_a"), mb.load("run_b")
        assert dat_a.get_path().startswith(ma._dat_folders[0])
        assert dat_b.get_path().startswith(mb._dat_folders[0])
        assert dat_a.get_spec()["who"] == "world a"        # `{}` through its own namespace
        assert dat_b.get_spec()["who"] == "world b"
        assert dat_b.get_spec()["dat"]["kwargs"] == {"tag": "b"}   # `dat.base` through its own
        assert not ma.exists("run_b") and not mb.exists("run_a")
        with pytest.raises(KeyError):
            ma.load("run_b")

        assert Dat.manager._dat_folders == global_folder    # the default world: untouched
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
        assert ma.do is not do


class TestAdoption:
    def test_a_second_manager_adopting_a_namespace_keeps_its_mounts(self, tmp_path):
        before = Dat.manager
        m = DatManager(dat_folders=[str(tmp_path / "one")])
        m.do.mount(value=1, at="kept")
        m2 = DatManager(dat_folders=[str(tmp_path / "two")], do=m.do)
        assert m2._dat_folders[0].endswith("/two")
        assert m2.do is m.do and m2.do.manager is m2       # the namespace moved
        assert m2.do.load("kept") == 1                     # mounts survive
        assert Dat.manager is before                       # not the default's do

    def test_a_bare_do_mounts_and_loads_but_cannot_run(self, tmp_path):
        probe = Do()
        probe.mount(value={"x": 1}, at="bare")
        assert probe.load("bare.x") == 1
        with pytest.raises(Exception) as caught:
            probe({"dat": {"do": "bare"}})
        assert isinstance(caught.value.__cause__, RuntimeError)
        assert "no manager" in str(caught.value.__cause__)
        m = DatManager(dat_folders=[str(tmp_path)], do=probe)
        assert probe.manager is m and probe.load("bare.x") == 1


class TestTheDefaultWorld:
    def test_dat_create_and_load_trampoline_to_the_manager(self):
        assert Dat.manager is do.manager
        assert do._current() is Dat.manager.do
        name = "managers/trampoline"
        if Dat.manager.exists(name):
            Dat.load(name).delete()
        dat = Dat.create(path=name, spec={"k": "v"})
        assert dat.get_path().startswith(Dat.manager._dat_folders[0])
        assert Dat.load(name) is Dat.manager.load(name)
        assert Dat.manager.exists(name)
        dat.delete()

    def test_first_use_builds_the_default_world(self, tmp_path):
        (tmp_path / DAT_CONFIG_FILE).write_text("dat_folders: warehouse/\n")
        probe = (
            "from dvc_dat import do, Dat\n"
            "from dvc_dat import core\n"
            "assert core._default_manager is None\n"       # import read nothing
            "do.mount(value={'x': 1}, at='early')\n"        # first use builds it
            "assert core._default_manager is not None\n"
            "assert Dat.manager is do.manager\n"
            "assert do.load('early.x') == 1\n"
            "assert do.load('dt.list') is not None\n"
            "print(Dat.manager._dat_folders[0])\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe], cwd=tmp_path,
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().rstrip("/").endswith("warehouse")
