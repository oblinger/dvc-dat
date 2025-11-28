"""Simple test to verify the new DataConfig-based system works."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Prevent the old initialization from running
import __main__
__main__.NO_DAT_DVC_INIT = True

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestDataConfig:
    """Test the new DataConfig system."""

    def test_dataconfig_creation(self):
        """Test that DataConfig can be created."""
        from dvc_dat.config import DataConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataConfig.new(cwd=tmpdir)
            assert config.cwd == os.path.realpath(tmpdir)
            assert config.local_prefix.endswith("/")

    def test_datmanager_creation(self):
        """Test that DatManager can be created with DataConfig."""
        from dvc_dat.config import DataConfig
        from dvc_dat.dat import DatManager

        with tempfile.TemporaryDirectory() as tmpdir:
            # Explicitly no mount_commands - standalone mode
            config = DataConfig(cwd=tmpdir, mount_commands=None)
            manager = DatManager(config=config)
            assert manager.main_sync_folder == config.local_prefix

    def test_dat_create_and_load(self):
        """Test creating and loading a Dat."""
        from dvc_dat.config import DataConfig
        from dvc_dat.dat import Dat, DatManager

        with tempfile.TemporaryDirectory() as tmpdir:
            # Explicitly no mount_commands - standalone mode
            config = DataConfig(cwd=tmpdir, mount_commands=None)
            manager = DatManager(config=config)

            # Override the class-level manager
            original_manager = Dat._manager
            Dat._manager = manager

            try:
                # Create a dat
                dat = Dat.create(
                    path="test_dat",
                    spec={"dat": {"kind": "Dat"}, "my_key": "my_value"},
                )

                assert dat is not None
                assert dat.spec.dat.kind == "Dat"
                assert os.path.exists(dat.get_path())

                # Load it back
                loaded = Dat.load(dat.get_path())
                assert loaded.spec.dat.kind == "Dat"

                # Clean up
                dat.delete()
            finally:
                Dat._manager = original_manager


class TestDataConfigFileDiscovery:
    """Test that .dataconfig.yaml files are discovered and used."""

    def test_config_file_discovery(self):
        """Test that DataConfig finds .dataconfig.yaml in parent directories."""
        from dvc_dat.config import DataConfig, DATA_CONFIG_FILE

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a .dataconfig.yaml in the temp directory
            config_path = Path(tmpdir) / DATA_CONFIG_FILE
            config_path.write_text("""
local_prefix: my_custom_data_folder/
remote_prefix: my-remote/
default_remote: s3
""")
            # Create a subdirectory and run from there
            subdir = Path(tmpdir) / "some" / "nested" / "path"
            subdir.mkdir(parents=True)

            # Save current directory
            original_cwd = os.getcwd()
            try:
                os.chdir(subdir)
                config = DataConfig.new()

                # Should find the config file and use its values
                assert "my_custom_data_folder" in config.local_prefix
                assert config.remote_prefix == "/my-remote/"
                assert config.default_remote == "s3"
            finally:
                os.chdir(original_cwd)

    def test_tests_folder_config(self):
        """Test that the tests/.dataconfig.yaml is set up correctly."""
        from dvc_dat.config import DataConfig, DATA_CONFIG_FILE

        tests_dir = Path(__file__).parent
        config_file = tests_dir / DATA_CONFIG_FILE

        assert config_file.exists(), f"Expected {config_file} to exist"

        # Load and verify the config
        original_cwd = os.getcwd()
        try:
            os.chdir(tests_dir)
            config = DataConfig.new()
            assert "test_sync_folder" in config.local_prefix
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
