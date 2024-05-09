# do = "do is not defined"
# print(f"__init__:  type of do is {type(do)}")
import sys

from .ml_dat_config import DatConfig
from .do_fn import DoManager, do_argv

dat_config = DatConfig()
do = DoManager(do_folder=dat_config.do_folder)  # not available during load of do_fn

from .dat import Dat, DatContainer, load_dat
from . import dat_tools

do.register_module("dat_tools", dat_tools)
do.register_module("dt", dat_tools)
do.register_value("dt.list", dat_tools.cmd_list)

__all__ = ["dat_config", "Dat", "DatContainer", "load_dat", "DoManager",
           "do", "do_argv", "dat_tools"]
