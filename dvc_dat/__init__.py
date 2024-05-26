import sys

from .dvc_dat_config import DatConfig
from .do_fn import DoManager, do_argv

VERSION = "1.0.00 (2024-05-25)"
dat_config = DatConfig()
do = DoManager()  # not available during load of do_fn

from .dat import Dat, DatContainer
from . import dat_tools

do.mount_all(dat_config.config.get("mount_commands", []), relative_to=dat_config.folder)
do.mount(module=dat_tools, at="dat_tools")
do.mount(module=dat_tools, at="dt")
do.mount(value=dat_tools.cmd_list, at="dt.list")
do.mount(value=dat_tools.cmd_list, at="dat_tools.list")

__all__ = ["VERSION", "dat_config", "Dat", "DatContainer", "DatConfig", "DoManager",
           "do", "do_argv", "dat_tools"]
