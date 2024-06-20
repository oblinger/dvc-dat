__version__ = "1.00.05"
DAT_VERSION = f"{__version__} (2024-06-20)"

from .dvc_dat_config import DatConfig, _DAT_MOUNT_COMMANDS
from .do_fn import DoManager, do_argv

dat_config = DatConfig()
do = DoManager()  # not available during load of do_fn

from .dat import Dat, DatContainer
from . import dat_tools

cmds = dat_config.config.get(_DAT_MOUNT_COMMANDS, [])
do.mount_all(cmds, relative_to=dat_config.folder)
do.mount(module=dat_tools, at="dat_tools")
do.mount(module=dat_tools, at="dt")
do.mount(value=dat_tools.cmd_list, at="dt.list")
do.mount(value=dat_tools.cmd_list, at="dat_tools.list")

__all__ = [
    "DAT_VERSION",
    "dat_config",
    "Dat",
    "DatContainer",
    "DatConfig",
    "DoManager",
    "do",
    "do_argv",
    "dat_tools",
]
