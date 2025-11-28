"""Pytest configuration for dvc_dat tests.

This conftest.py ensures the Dat singleton is initialized with the test configuration
before any tests run. It loads the .dataconfig.yaml from the tests/ directory.
"""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Initialize Dat manager with test config BEFORE any test imports
tests_dir = Path(__file__).parent

from dvc_dat.config import DataConfig

# Load config from tests directory (where .dataconfig.yaml is located)
os.chdir(tests_dir)  # Temporarily change to tests dir for config discovery
config = DataConfig.new()
os.chdir(Path(__file__).parent.parent)  # Change back to project root

from dvc_dat.dat import Dat, DatManager

# Initialize the singleton with our test config
Dat._manager = DatManager(config=config)
