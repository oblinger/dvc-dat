"""The example namespace: imported by `.dataconfig.yaml`'s `main:` key."""
from pathlib import Path

import dvc_dat
from dvc_dat import do

TESTS = Path(__file__).parent.parent / "tests"

do.mount(folder=str(TESTS.parent / "standard_do_scripts"))
do.mount(folder=str(TESTS / "test_mounted_folder" / "dat_tools_examples"))
do.mount(folder=str(TESTS / "test_mounted_folder" / "script"))
do.mount(folder=str(TESTS / "test_mounted_folder"))
do.mount(file=str(TESTS / "test_mounted_folder" / "some_python_file.py"), at="foo")
do.mount(module=dvc_dat, at="the_dat_module")
do.mount(value=[11, 22, 33], at="foo.bar.baz")
