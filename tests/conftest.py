"""Pytest configuration for dvc_dat tests.

Builds the default world, `Dat.manager`, from `tests/.datconfig.yaml` before any
test imports.  `import dvc_dat` itself reads no config; the first use would
build it from the working directory, so the tests pin theirs here.
"""
import sys
from pathlib import Path

tests_dir = Path(__file__).parent
sys.path.insert(0, str(tests_dir.parent))

from dvc_dat import Dat, DatManager  # noqa: E402

do = Dat.do

Dat.manager = DatManager.load_dat_config(tests_dir, do=do)
import mounts  # noqa: E402,F401  -- the test namespace; a program imports its own
