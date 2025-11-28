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
            config = DataConfig.new(cwd=tmpdir)
            manager = DatManager(config=config)
            assert manager.main_sync_folder == config.local_prefix

    def test_dat_create_and_load(self):
        """Test creating and loading a Dat."""
        from dvc_dat.config import DataConfig
        from dvc_dat.dat import Dat, DatManager

        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataConfig.new(cwd=tmpdir)
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
