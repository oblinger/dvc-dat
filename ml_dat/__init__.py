from .ml_dat_config import DatConfig
from .inst import Inst, InstContainer, load_inst
from .do_fn import DoManager, do_argv
from . import dat_tools

dat_config = DatConfig()
do = DoManager(do_folder=dat_config.do_folder)
do.register_module("dat_tools", dat_tools)
do.register_module("dt", dat_tools)
#do.register_value("dt.list", df_tools.cmd_list)

__all__ = ["dat_config", "Inst", "InstContainer", "load_inst", "DoManager",
           "do", "do_argv", "dat_tools"]
