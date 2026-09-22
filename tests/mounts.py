"""The test namespace: imported by `.dataconfig.yaml`'s `main:` key."""
from pathlib import Path

from dvc_dat import do

HERE = Path(__file__).parent

do.mount(folder=str(HERE.parent / "standard_do_scripts"))
do.mount(folder=str(HERE / "test_mounted_folder" / "dat_tools_examples"))
do.mount(folder=str(HERE / "test_mounted_folder" / "script"))
do.mount(folder=str(HERE / "test_mounted_folder"))
