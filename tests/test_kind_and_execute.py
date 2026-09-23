"""2.3: the sidecar names the class, and every run goes through the manager.

SVP's handoff, 2026-09-22: `dat.kind` is a dotted `module.qualname`, imported
on load; `manager.load` / `manager.create` take no class; `Cls.load` is typed;
`manager.execute(dat)` is the run, nested runs included, and records the code.
"""
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dvc_dat import Dat, DatManager  # noqa: E402


class Run(Dat):
    pass


class Other(Dat):
    pass


def outer(dat, n):
    return dat._manager.do({"dat": {"do": "inner", "name": "inner{unique}"}}, n + 1)


def inner(dat, n):
    return n * 10


@pytest.fixture
def m(tmp_path):
    manager = DatManager(dat_folders=[str(tmp_path / "dats")])
    manager.do.mount(value=outer, at="outer")
    manager.do.mount(value=inner, at="inner")
    return manager


def kind_on_disk(dat):
    return yaml.safe_load(Path(dat.get_path(), "_spec_.yaml").read_text())["dat"]["kind"]


def write_spec(m, name, kind):
    folder = Path(m._dat_folders[0], name)
    folder.mkdir(parents=True)
    (folder / "_spec_.yaml").write_text(yaml.safe_dump({"dat": {"kind": kind}}))


class TestTheClassOfADat:
    def test_create_writes_the_dotted_path_and_load_imports_it(self, m):
        dat = m.create({"dat": {"name": "a", "kind": f"{__name__}.Run"}})
        assert type(dat) is Run
        assert kind_on_disk(dat) == f"{__name__}.Run"
        m._dat_cache.clear()
        assert type(m.load("a")) is Run

    def test_a_bare_kind_is_written_dotted(self, m):
        assert kind_on_disk(m.create({"dat": {"name": "a", "kind": "Run"}})) == f"{__name__}.Run"

    def test_no_kind_is_a_plain_dat(self, m):
        assert kind_on_disk(m.create({"dat": {"name": "a"}})) == "dvc_dat.core.Dat"

    def test_an_unimportable_kind_is_an_import_error_never_a_downgrade(self, m):
        write_spec(m, "gone", "no_such_pkg.mod.Run")
        with pytest.raises(ImportError):
            m.load("gone")
        write_spec(m, "attr", f"{__name__}.NoSuchClass")
        with pytest.raises(ImportError):
            m.load("attr")

    def test_a_kind_that_is_not_a_dat_is_a_type_error(self, m):
        write_spec(m, "notdat", "collections.OrderedDict")
        with pytest.raises(TypeError):
            m.load("notdat")

    def test_a_bare_kind_on_disk_reads_the_old_way(self, m):
        write_spec(m, "legacy", "Run")
        write_spec(m, "unknown", "run")
        assert type(m.load("legacy")) is Run
        assert type(m.load("unknown")) is Dat


class TestTypedTrampolines:
    def test_cls_create_gives_its_own_kind_and_cls_load_checks_it(self):
        name = "kind_and_execute/typed"
        if Dat.manager.exists(name):
            Dat.load(name).delete()
        run = Run.create(path=name, spec={"dat": {"target_exists": "overwrite"}})
        assert type(run) is Run and kind_on_disk(run) == f"{__name__}.Run"
        assert Run.load(name) is run
        assert Dat.load(name) is run
        with pytest.raises(TypeError):
            Other.load(name)
        run.delete()

    def test_cls_create_refuses_another_kind_before_writing(self):
        name = "kind_and_execute/refused"
        with pytest.raises(TypeError):
            Run.create(path=name, spec={"dat": {"kind": f"{__name__}.Other"}})
        assert not Dat.manager.exists(name)


class TestExecute:
    def test_nested_runs_all_go_through_the_managers_execute(self, tmp_path):
        seen = []

        class Recording(DatManager):
            def execute(self, dat):
                seen.append(dat.get_path_name())
                return super().execute(dat)

        m = Recording(dat_folders=[str(tmp_path / "dats")])
        m.do.mount(value=outer, at="outer")
        m.do.mount(value=inner, at="inner")
        assert m.do({"dat": {"do": "outer", "name": "outer"}}, 4) == 50
        assert seen == ["outer", "inner"]

    def test_a_run_records_the_checkout_of_the_code_it_ran(self, m):
        dat = m.create({"dat": {"do": "inner", "name": "a", "args": [1]}})
        assert m.execute(dat) == 10
        code = dat.get_results()["dat"]["code"]
        head = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        assert code["commit"] == head
        assert isinstance(code["dirty"], bool)
        assert "run_at" in dat.get_results()["dat"]

    def test_code_outside_a_checkout_records_nothing(self, m):
        m.do.mount(value=id, at="builtin")
        dat = m.create({"dat": {"do": "builtin", "name": "b"}})
        m.execute(dat)
        assert "code" not in dat.get_results()["dat"]

    def test_no_do_returns_the_dat(self, m):
        dat = m.create({"dat": {"name": "c"}})
        assert m.execute(dat) is dat
