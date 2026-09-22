"""Configuration: DataConfig discovery, precedence, and the DatManager built from it."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dvc_dat import Dat, DataConfig, DatManager  # noqa: E402
from dvc_dat.core import DATA_CONFIG_FILE  # noqa: E402


class TestDataConfig:
    def test_dataconfig_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataConfig.new(cwd=tmpdir)
            assert config.cwd == os.path.realpath(tmpdir)
            assert config.local_prefix.endswith("/")

    def test_new_searches_from_cwd_argument(self, monkeypatch):
        """`new(cwd=X)` finds the config above X, not above the process cwd."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.realpath(tmpdir)
            with open(os.path.join(root, DATA_CONFIG_FILE), "w") as f:
                f.write("local_prefix: from_arg/\n")
            nested = os.path.join(root, "a", "b")
            os.makedirs(nested)
            with tempfile.TemporaryDirectory() as elsewhere:
                monkeypatch.chdir(elsewhere)
                config = DataConfig.new(cwd=nested)
            assert config.cwd == nested
            assert config.local_prefix == os.path.join(nested, "from_arg/")

    def test_only_dat_prefixed_environment_keys_override(self, monkeypatch):
        """`DAT_LOCAL_PREFIX` overrides `local_prefix`; a bare `local_prefix` does not."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("local_prefix", "bare/")
            monkeypatch.setenv("DAT_UNKNOWN", "ignored")
            assert DataConfig.new(cwd=tmpdir).local_prefix.endswith("/data/")
            monkeypatch.setenv("DAT_LOCAL_PREFIX", "prefixed/")
            assert DataConfig.new(cwd=tmpdir).local_prefix.endswith("/prefixed/")

    def test_unknown_config_key_is_an_error(self):
        """2.0: an unrecognized key in a config file is named, not silently ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, DATA_CONFIG_FILE)
            path.write_text("local_prefix: data/\nremote_prefix: sv-ai-data/\n")
            with pytest.raises(ValueError) as caught:
                DataConfig.new(cwd=tmpdir)
            message = str(caught.value)
            assert "remote_prefix" in message
            assert str(path) in message
            assert "local_prefix" in message   # names the known keys

    def test_datmanager_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataConfig(cwd=tmpdir)
            manager = DatManager(config=config)
            assert manager.main_sync_folder == config.local_prefix

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
                "local_prefix: my_custom_data_folder/\n"
                "extra_local_prefixes: [/tmp/elsewhere]\n"
            )
            subdir = Path(tmpdir) / "some" / "nested" / "path"
            subdir.mkdir(parents=True)

            original_cwd = os.getcwd()
            try:
                os.chdir(subdir)
                config = DataConfig.new()
                assert "my_custom_data_folder" in config.local_prefix
                assert config.extra_local_prefixes == ["/tmp/elsewhere"]
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
            assert "test_sync_folder" in config.local_prefix
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
