"""The test namespace: `conftest.py` imports it, as any program imports its own;
run as a main it is the `dat` command inside that namespace."""
import sys
from pathlib import Path

from dvc_dat import Dat

ns = Dat.ns

HERE = Path(__file__).parent

ns.mount(folder=str(HERE / "test_mounted_folder" / "dat_tools_examples"))
ns.mount(folder=str(HERE / "test_mounted_folder" / "script"))
ns.mount(folder=str(HERE / "test_mounted_folder"))

if __name__ == "__main__":
    sys.exit(Dat.cli_main())
