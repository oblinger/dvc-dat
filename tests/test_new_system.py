"""Configuration: DataConfig discovery, precedence, and the DatManager built from it."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dvc_dat import Dat, DataConfig, DatManager, cli_main, do  # noqa: E402
from dvc_dat.core import DATA_CONFIG_FILE  # noqa: E402
from dvc_dat.do import Do  # noqa: E402


class TestDataConfig:
    def test_dataconfig_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataConfig.new(cwd=tmpdir)
            assert config.cwd == os.path.realpath(tmpdir)
            assert config.dat_folders[0].endswith("/")

    def test_new_searches_from_cwd_argument(self, monkeypatch):
        """`new(cwd=X)` finds the config above X, not above the process cwd."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.realpath(tmpdir)
            with open(os.path.join(root, DATA_CONFIG_FILE), "w") as f:
                f.write("dat_folders: from_arg/\n")
            nested = os.path.join(root, "a", "b")
            os.makedirs(nested)
            with tempfile.TemporaryDirectory() as elsewhere:
                monkeypatch.chdir(elsewhere)
                config = DataConfig.new(cwd=nested)
            assert config.cwd == nested
            assert config.dat_folders == [os.path.join(nested, "from_arg/")]

    def test_only_dat_prefixed_environment_keys_override(self, monkeypatch):
        """`DAT_FOLDERS` overrides `dat_folders`; a bare `dat_folders` does not."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("dat_folders", "bare/")
            monkeypatch.setenv("DAT_UNKNOWN", "ignored")
            assert DataConfig.new(cwd=tmpdir).dat_folders[0].endswith("/data/")
            monkeypatch.setenv("DAT_FOLDERS", "prefixed/")
            assert DataConfig.new(cwd=tmpdir).dat_folders[0].endswith("/prefixed/")

    def test_unknown_config_key_is_an_error(self):
        """2.0: an unrecognized key in a config file is named, not silently ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, DATA_CONFIG_FILE)
            path.write_text("dat_folders: data/\nremote_prefix: sv-ai-data/\n")
            with pytest.raises(ValueError) as caught:
                DataConfig.new(cwd=tmpdir)
            message = str(caught.value)
            assert "remote_prefix" in message
            assert str(path) in message
            assert "dat_folders" in message   # names the known keys

    def test_datmanager_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataConfig(cwd=tmpdir)
            manager = DatManager(config=config)
            assert manager.dat_folder == config.dat_folders[0]

    def test_dat_create_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataConfig(cwd=tmpdir)
            original_manager = Dat._manager
            Dat._manager = DatManager(config=config)
            try:
                dat = Dat.create(
                    path="test_dat",
                    spec={"dat": {"kind": "Dat"}, "my_key": "my_value"},
                )
                assert dat is not None
                assert dat.get_spec()["dat"]["kind"] == "Dat"
                assert os.path.exists(dat.get_path())

                loaded = Dat.load(dat.get_path())
                assert loaded.get_spec()["dat"]["kind"] == "Dat"
                dat.delete()
            finally:
                Dat._manager = original_manager


class TestDataConfigFileDiscovery:
    def test_config_file_discovery(self):
        """A `.dataconfig.yaml` above the working directory is found and used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, DATA_CONFIG_FILE).write_text(
                "dat_folders: [my_custom_data_folder/, /tmp/elsewhere]\n"
            )
            subdir = Path(tmpdir) / "some" / "nested" / "path"
            subdir.mkdir(parents=True)

            original_cwd = os.getcwd()
            try:
                os.chdir(subdir)
                config = DataConfig.new()
                assert "my_custom_data_folder" in config.dat_folders[0]
                assert config.dat_folders[1] == "/tmp/elsewhere/"
                assert config.cwd == os.path.realpath(tmpdir)
            finally:
                os.chdir(original_cwd)

    def test_tests_folder_config(self):
        tests_dir = Path(__file__).parent
        assert (tests_dir / DATA_CONFIG_FILE).exists()

        original_cwd = os.getcwd()
        try:
            os.chdir(tests_dir)
            config = DataConfig.new()
            assert "test_sync_folder" in config.dat_folders[0]
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestDatCliConfigVariable:
    def test_cli_main_reads_the_file_it_names(self, tmp_path, monkeypatch, capsys):
        """`DAT_CLI_CONFIG` (set by the bootstrap) is read by `cli_main`, not by
        discovery: `DataConfig.new()` still walks up from the working directory."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / DATA_CONFIG_FILE).write_text("dat_folders: pinned/\n")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / DATA_CONFIG_FILE).write_text("dat_folders: here/\n")
        monkeypatch.chdir(elsewhere)
        monkeypatch.setenv("DAT_CLI_CONFIG", str(project / DATA_CONFIG_FILE))
        before = do.config
        try:
            assert DataConfig.new().dat_folders[0].endswith("/here/")
            assert cli_main(["dat", "info"]) == 0
            assert "/pinned/" in capsys.readouterr().out
            assert do.config.cwd == os.path.realpath(project)
        finally:
            do.configure(before)

    def test_a_missing_file_is_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DAT_CLI_CONFIG", str(tmp_path / "nope.yaml"))
        with pytest.raises(ValueError, match="DAT_CLI_CONFIG"):
            cli_main(["dat", "info"])


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
