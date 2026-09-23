"""Configuration: `DatManager.load_dat_config` discovery and precedence, the
constructor, and the default world `Dat.manager`."""
import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import dvc_dat  # noqa: E402
from dvc_dat import Dat, DatManager  # noqa: E402

do, cli_main = Dat.do, Dat.cli_main
from dvc_dat.core import DAT_CONFIG_FILE, DAT_CONFIG_OVERRIDE_FILE  # noqa: E402
from dvc_dat.do import Do  # noqa: E402


@pytest.fixture
def default_world():
    """Restore `Dat.manager` after a test that replaces it."""
    before = Dat.manager
    yield before
    Dat.manager = before


class TestLoadDatConfig:
    def test_no_file_means_data_under_start(self, tmp_path):
        manager = DatManager.load_dat_config(tmp_path)
        assert manager._dat_folders == [os.path.join(os.path.realpath(tmp_path), "data")]
        assert manager._config_dir == os.path.realpath(tmp_path)

    def test_searches_up_from_start(self, tmp_path, monkeypatch):
        """`load_dat_config(X)` finds the config above X, not above the process cwd."""
        root = os.path.realpath(tmp_path)
        Path(root, DAT_CONFIG_FILE).write_text("dat_folders: from_arg/\n")
        nested = os.path.join(root, "a", "b")
        os.makedirs(nested)
        with tempfile.TemporaryDirectory() as elsewhere:
            monkeypatch.chdir(elsewhere)
            manager = DatManager.load_dat_config(nested)
        assert manager._config_dir == root
        assert manager._dat_folders == [os.path.join(root, "from_arg")]
        assert sys.path[0] == root          # the config folder is the import root

    def test_a_config_file_names_itself(self, tmp_path):
        Path(tmp_path, "other.yaml").write_text("dat_folders: [x, y]\n")
        manager = DatManager.load_dat_config(tmp_path / "other.yaml")
        root = os.path.realpath(tmp_path)
        assert manager._dat_folders == [os.path.join(root, "x"), os.path.join(root, "y")]

    def test_override_file_wins_over_the_file(self, tmp_path):
        Path(tmp_path, DAT_CONFIG_FILE).write_text("dat_folders: base/\n")
        Path(tmp_path, DAT_CONFIG_OVERRIDE_FILE).write_text("dat_folders: over/\n")
        manager = DatManager.load_dat_config(tmp_path)
        assert manager._dat_folders[0].endswith("/over")

    def test_only_dat_prefixed_environment_keys_override(self, tmp_path, monkeypatch):
        """`DAT_FOLDERS` overrides `dat_folders`; a bare `dat_folders` does not."""
        Path(tmp_path, DAT_CONFIG_OVERRIDE_FILE).write_text("dat_folders: over/\n")
        monkeypatch.setenv("dat_folders", "bare/")
        monkeypatch.setenv("DAT_UNKNOWN", "ignored")
        assert DatManager.load_dat_config(tmp_path)._dat_folders[0].endswith("/over")
        monkeypatch.setenv("DAT_FOLDERS", "prefixed/")
        assert DatManager.load_dat_config(tmp_path)._dat_folders[0].endswith("/prefixed")

    def test_unknown_config_key_is_an_error(self, tmp_path):
        """2.0: an unrecognized key in a config file is named, not silently ignored."""
        path = Path(tmp_path, DAT_CONFIG_FILE)
        path.write_text("dat_folders: data/\nremote_prefix: sv-ai-data/\n")
        with pytest.raises(ValueError) as caught:
            DatManager.load_dat_config(tmp_path)
        message = str(caught.value)
        assert "remote_prefix" in message
        assert str(path) in message
        assert "dat_folders" in message   # names the known keys

    def test_the_old_file_name_is_not_read(self, tmp_path):
        Path(tmp_path, ".dataconfig.yaml").write_text("dat_folders: old/\n")
        assert DatManager.load_dat_config(tmp_path)._dat_folders[0].endswith("/data")

    def test_config_file_discovery_from_the_working_directory(self, tmp_path, monkeypatch):
        """A `.datconfig.yaml` above the working directory is found and used."""
        Path(tmp_path, DAT_CONFIG_FILE).write_text(
            "dat_folders: [my_custom_data_folder/, /tmp/elsewhere]\n")
        subdir = tmp_path / "some" / "nested" / "path"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        manager = DatManager.load_dat_config()
        assert manager._dat_folders[0].endswith("/my_custom_data_folder")
        assert manager._dat_folders[1] == os.path.realpath("/tmp/elsewhere")
        assert manager._config_dir == os.path.realpath(tmp_path)

    def test_tests_folder_config(self, monkeypatch):
        tests_dir = Path(__file__).parent
        assert (tests_dir / DAT_CONFIG_FILE).exists()
        monkeypatch.chdir(tests_dir)
        assert "test_sync_folder" in DatManager.load_dat_config()._dat_folders[0]


class TestConstructor:
    def test_keyword_only_list_required(self, tmp_path):
        with pytest.raises(TypeError):
            DatManager([str(tmp_path)])                      # positional
        with pytest.raises(TypeError, match="list of folders"):
            DatManager(dat_folders=str(tmp_path))            # a string
        with pytest.raises(ValueError):
            DatManager(dat_folders=[])
        with pytest.raises(TypeError):
            DatManager()

    def test_nothing_is_read_from_disk(self, tmp_path):
        Path(tmp_path, DAT_CONFIG_FILE).write_text("dat_folders: [ignored]\n")
        manager = DatManager(dat_folders=[str(tmp_path / "dats")])
        assert manager._dat_folders == [os.path.realpath(tmp_path / "dats")]
        assert manager._config_dir is None

    def test_the_only_public_attribute_is_do(self, tmp_path):
        manager = DatManager(dat_folders=[str(tmp_path)])
        public = [n for n in vars(manager) if not n.startswith("_")]
        assert public == ["do"]
        for gone in ("config", "dat_folder", "dat_folders", "cwd"):
            assert not hasattr(manager, gone)
        assert not hasattr(dvc_dat, "DataConfig")
        assert not hasattr(Do, "configure") and not hasattr(Do, "config")

    def test_dat_create_and_load(self, tmp_path):
        manager = DatManager(dat_folders=[str(tmp_path)])
        dat = manager.create({"dat": {"kind": "Dat"}, "my_key": "my_value"}, path="test_dat")
        assert dat.get_spec()["dat"]["kind"] == "dvc_dat.core.Dat"
        assert dat.get_path_name() == "test_dat"
        assert manager.load("test_dat") is dat


class TestDefaultWorld:
    def test_assigning_redirects_dat_load_and_do(self, tmp_path, default_world):
        mine = DatManager(dat_folders=[str(tmp_path)])
        mine.create({"dat": {"kind": "Dat"}}, path="here")
        Dat.manager = mine
        assert Dat.load("here").get_path() == os.path.join(os.path.realpath(tmp_path), "here")
        assert do.manager is mine
        assert do.load("dt.list") is mine.do.load("dt.list")

    def test_a_bound_shortcut_follows_a_reassignment(self, tmp_path, default_world):
        shortcut = Dat.do
        replaced = DatManager(dat_folders=[str(tmp_path)])
        Dat.manager = replaced
        assert shortcut.manager is replaced

    def test_the_package_exports_the_four_classes(self):
        assert sorted(dvc_dat.__all__) == ["Dat", "DatContainer", "DatManager", "Do"]
        for gone in ("cli_main", "expand", "expand_spec", "merge_dicts"):
            assert not hasattr(dvc_dat, gone)

    def test_subclasses_share_it(self, default_world):
        class Run(Dat):
            pass
        assert Run.manager is Dat.manager

    def test_adopting_the_default_do_keeps_mounts(self, tmp_path, default_world):
        do.mount(value={"x": 1}, at="adopt_probe")
        replaced = DatManager(dat_folders=[str(tmp_path)], do=do)
        assert Dat.manager is replaced
        assert do.load("adopt_probe.x") == 1
        assert replaced.do is default_world.do

    def test_a_plain_manager_does_not_replace_it(self, tmp_path, default_world):
        DatManager(dat_folders=[str(tmp_path)])
        assert Dat.manager is default_world

    def test_only_a_manager_may_be_assigned(self, default_world):
        with pytest.raises(TypeError):
            Dat.manager = "nope"

    def test_first_use_builds_it_from_the_working_directory(self, tmp_path, monkeypatch,
                                                            default_world):
        Path(tmp_path, DAT_CONFIG_FILE).write_text("dat_folders: warehouse/\n")
        monkeypatch.chdir(tmp_path)
        Dat.manager = None
        assert Dat.manager._dat_folders == [os.path.join(os.path.realpath(tmp_path), "warehouse")]
        assert do.manager is Dat.manager


class TestDatCliConfigVariable:
    def test_cli_main_reads_the_file_it_names(self, tmp_path, monkeypatch, capsys,
                                              default_world):
        """`DAT_CLI_CONFIG` (set by the bootstrap) is read by `cli_main`, not by
        discovery: `load_dat_config()` still walks up from the working directory."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / DAT_CONFIG_FILE).write_text("dat_folders: pinned/\n")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / DAT_CONFIG_FILE).write_text("dat_folders: here/\n")
        monkeypatch.chdir(elsewhere)
        monkeypatch.setenv("DAT_CLI_CONFIG", str(project / DAT_CONFIG_FILE))
        assert DatManager.load_dat_config()._dat_folders[0].endswith("/here")
        assert cli_main(["dat", "--info"]) == 0
        assert "/pinned" in capsys.readouterr().out
        assert Dat.manager._config_dir == os.path.realpath(project)
        assert sys.path[0] == os.path.realpath(project)

    def test_a_missing_file_is_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DAT_CLI_CONFIG", str(tmp_path / "nope.yaml"))
        with pytest.raises(ValueError, match="DAT_CLI_CONFIG"):
            cli_main(["dat", "--info"])


class TestFolderMountPaths:
    """A folder mount answers to dotted paths: `at`, then the file's path under the
    folder, as `docs/mount-commands.md` § folder promises."""

    @pytest.fixture
    def catalog(self, tmp_path):
        (tmp_path / "models").mkdir()
        (tmp_path / "experiment.yaml").write_text("dat:\n  kwargs: {game: G1}\n")
        (tmp_path / "models" / "baseline.yaml").write_text("lr: 0.1\n")
        (tmp_path / "models" / "helpers.py").write_text("def double(x):\n    return 2 * x\n")
        return tmp_path

    def test_at_prefixes_the_folder(self, catalog):
        probe = Do()
        probe.mount(folder=str(catalog), at="catalog")
        assert probe.load("catalog.experiment")["dat"]["kwargs"] == {"game": "G1"}
        assert probe.load("catalog.experiment.dat.kwargs.game") == "G1"

    def test_nested_files_answer_to_their_path(self, catalog):
        probe = Do()
        probe.mount(folder=str(catalog), at="catalog")
        assert probe.load("catalog.models.baseline") == {"lr": 0.1}
        assert probe.load("catalog.models.baseline.lr") == 0.1
        assert probe.load("catalog.models.helpers.double")(4) == 8

    def test_without_at_the_folder_is_the_root(self, catalog):
        probe = Do()
        probe.mount(folder=str(catalog))
        assert probe.load("models.baseline.lr") == 0.1

    def test_a_missing_key_under_a_nested_file_is_named(self, catalog):
        probe = Do()
        probe.mount(folder=str(catalog), at="catalog")
        with pytest.raises(KeyError, match="'nope' is missing from"):
            probe.load("catalog.models.baseline.nope")


def test_merge_dicts_is_the_base_zipper():
    merge_dicts = Dat.merge_dicts
    base = {"a": {"x": 1, "y": 2}, "l": [1, 2]}
    over = {"a": {"x": 9}, "l": [3]}
    assert merge_dicts(base, over) == {"a": {"x": 9, "y": 2}, "l": [3]}
    assert base == {"a": {"x": 1, "y": 2}, "l": [1, 2]}      # inputs untouched



class TestMergeByName:
    """Dan, 2026-09-23 (SVP T150 Q1): named list entries merge by name."""
    stages = {"stages": [{"name": "detect", "fps": 30}, {"name": "track", "k": 5},
                         {"name": "score"}]}

    def test_a_named_entry_merges_into_its_namesake(self):
        out = Dat.merge_dicts(self.stages, {"stages": [{"name": "track", "k": 9}]})
        assert out["stages"] == [{"name": "detect", "fps": 30}, {"name": "track", "k": 9},
                                 {"name": "score"}]

    def test_a_new_name_appends_in_order(self):
        out = Dat.merge_dicts(self.stages, {"stages": [{"name": "viz"}, {"name": "zip"}]})
        assert [e["name"] for e in out["stages"]] == ["detect", "track", "score", "viz", "zip"]

    def test_remove_deletes_by_name(self):
        out = Dat.merge_dicts(self.stages, {"stages": [{"name": "track", "remove": True}]})
        assert [e["name"] for e in out["stages"]] == ["detect", "score"]

    def test_entries_merge_recursively(self):
        base = {"s": [{"name": "p", "cfg": {"a": 1, "b": 2}}]}
        out = Dat.merge_dicts(base, {"s": [{"name": "p", "cfg": {"b": 3}}]})
        assert out["s"] == [{"name": "p", "cfg": {"a": 1, "b": 3}}]

    def test_an_unnamed_list_is_still_replaced_whole(self):
        base = {"s": [{"name": "p"}], "l": [1, 2]}
        assert Dat.merge_dicts(base, {"s": [{"x": 1}], "l": [3]}) == {"s": [{"x": 1}], "l": [3]}

    def test_dat_base_uses_it(self, tmp_path):
        m = DatManager(dat_folders=[str(tmp_path)])
        m.do.mount(value=self.stages, at="parent")
        dat = m.create({"dat": {"base": "parent"}, "stages": [{"name": "viz"}]}, path="child")
        assert [e["name"] for e in dat.get_spec()["stages"]] == ["detect", "track", "score", "viz"]


class TestMountRefusesImportClash:
    """A mounted name is never also an importable one (Dan, 2026-09-22, F012 Q2)."""

    @pytest.fixture
    def importable(self, tmp_path, monkeypatch):
        site = tmp_path / "site"
        (site / "configs").mkdir(parents=True)
        (site / "configs" / "__init__.py").write_text("X = 'installed'\n")
        (site / "helpers.py").write_text("WHO = 'installed'\n")
        monkeypatch.syspath_prepend(str(site))
        mounted = tmp_path / "mounted"
        mounted.mkdir()
        (mounted / "helpers.py").write_text("WHO = 'mounted'\n")
        (mounted / "base.yaml").write_text("a: 1\n")
        forget = ("configs", "configs2", "helpers")   # each test has its own site
        for name in forget:
            sys.modules.pop(name, None)
        yield site, mounted
        for name in forget:
            sys.modules.pop(name, None)

    def test_a_root_folder_mount_may_not_shadow_a_module(self, importable):
        _, mounted = importable
        with pytest.raises(ValueError, match="'helpers' is an importable module"):
            Do().mount(folder=str(mounted))

    def test_at_may_not_be_an_importable_package(self, importable):
        _, mounted = importable
        with pytest.raises(ValueError, match="'configs' is an importable module"):
            Do().mount(folder=str(mounted), at="configs")

    def test_a_clear_name_mounts(self, importable):
        _, mounted = importable
        probe = Do()
        probe.mount(folder=str(mounted), at="templates")
        assert probe.load("templates.helpers.WHO") == "mounted"
        assert probe.load("helpers.WHO") == "installed"

    def test_values_and_files_are_checked_too(self, importable):
        _, mounted = importable
        with pytest.raises(ValueError, match="'json' is an importable module"):
            Do().mount(value={"a": 1}, at="json.settings")
        with pytest.raises(ValueError, match="'helpers'"):
            Do().mount(file=str(mounted / "base.yaml"), at="helpers")

    def test_a_module_at_its_own_name_is_not_a_clash(self, importable):
        probe = Do()
        probe.mount(module="helpers", at="helpers")
        probe.mount(module="configs", at="configs")
        assert probe.load("configs.X") == "installed"

    def test_a_package_folder_at_its_own_name_is_not_a_clash(self, importable):
        site, _ = importable
        probe = Do()
        probe.mount(folder=str(site / "configs"), at="configs")

    def test_a_symlinked_package_folder_at_its_own_name_is_not_a_clash(
            self, importable, tmp_path):
        site, _ = importable
        (site / "configs" / "base.yaml").write_text("a: 1\n")
        link = tmp_path / "link"
        link.symlink_to(site / "configs")
        probe = Do()
        probe.mount(folder=str(link), at="configs")
        assert probe.load("configs.base") == {"a": 1}

    def test_a_sibling_sharing_a_string_prefix_is_a_clash(self, importable):
        site, _ = importable
        (site / "configs2").mkdir()
        (site / "configs2" / "__init__.py").write_text("")
        (site / "configs" / "base.yaml").write_text("a: 1\n")
        importlib.invalidate_caches()
        with pytest.raises(ValueError, match="'configs2' is an importable module"):
            Do().mount(folder=str(site / "configs"), at="configs2")


class TestValueMountPaths:
    def test_a_value_mount_answers_below_itself(self):
        probe = Do()
        probe.mount(value={"pi": 3.14159, "deep": {"e": 2.71828}}, at="consts")
        assert probe.load("consts.pi") == 3.14159
        assert probe.load("consts.deep.e") == 2.71828
        assert probe.load("consts")["pi"] == 3.14159

    def test_a_missing_key_is_named(self):
        probe = Do()
        probe.mount(value={"pi": 3.14159}, at="consts")
        with pytest.raises(KeyError, match="'tau' is missing"):
            probe.load("consts.tau")


def test_the_constructor_points_at_create_and_load():
    with pytest.raises(TypeError, match=r"Dat.create\(spec=...\) makes one"):
        Dat({"dat": {"kind": "Dat"}})
