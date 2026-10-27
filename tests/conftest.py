"""Pytest configuration for dvc_dat tests.

Builds the default world, `Dat.manager`, from `tests/.datconfig.yaml` before any
test imports.  `import dvc_dat` itself reads no config; the first use would
build it from the working directory, so the tests pin theirs here.
"""
import sys
from pathlib import Path

import pytest

tests_dir = Path(__file__).parent
sys.path.insert(0, str(tests_dir.parent))

from dvc_dat import Dat, DatManager  # noqa: E402

ns = Dat.ns

Dat.manager = DatManager.load_dat_config(tests_dir, ns=ns)
import mounts  # noqa: E402,F401  -- the test namespace; a program imports its own


# Under pytest-xdist (`-n N --dist loadgroup`, as CI runs it) a group runs on one
# worker, in order.  The top-level test files share `test_sync_folder/` and the
# default `Dat.manager` (anonymous-dat numbering, cleanup tests that delete a
# prefix), so they run as one group; the demo notebooks share `doc/DAT Demos/`.
# Everything else builds its world under `tmp_path` and spreads across workers.
# `tryfirst`: xdist reads the marks in its own collection hook.
_OWN_WORLD = {"test_capture_and_artifacts.py"}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    for item in items:
        path = item.path
        if path.parent != tests_dir or path.name in _OWN_WORLD:
            continue
        group = "demo_notebooks" if path.name == "test_demo_notebooks.py" else "sync_folder"
        item.add_marker(pytest.mark.xdist_group(group))
