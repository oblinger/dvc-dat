"""The test namespace: `conftest.py` imports it, as any program imports its own;
run as a main it is the `dat` command inside that namespace."""
import sys
from pathlib import Path

from dvc_dat import cli, do

HERE = Path(__file__).parent

do.mount(folder=str(HERE.parent / "standard_do_scripts"))
do.mount(folder=str(HERE / "test_mounted_folder" / "dat_tools_examples"))
do.mount(folder=str(HERE / "test_mounted_folder" / "script"))
do.mount(folder=str(HERE / "test_mounted_folder"))

if __name__ == "__main__":
    sys.exit(cli())
