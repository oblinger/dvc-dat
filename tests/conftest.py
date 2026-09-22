"""Pytest configuration for dvc_dat tests.

Configures the do-system (and with it `Dat.manager`) from `tests/.dataconfig.yaml`
before any test imports.  `import dvc_dat` itself reads no config -- configuring is
always explicit.
"""
import sys
from pathlib import Path

tests_dir = Path(__file__).parent
sys.path.insert(0, str(tests_dir.parent))

from dvc_dat import do  # noqa: E402

do.configure(tests_dir)
