__version__ = "1.00.05"
DAT_VERSION = f"{__version__} (2024-06-20)"

from .dat import Dats, _DAT_MOUNT_COMMANDS
from .do_fn import DoManager, do_argv

dats = Dats()
do = DoManager()  # not available during load of do_fn

from .dat import Dat, DatContainer
from . import dat_tools

cmds = dats.config.get(_DAT_MOUNT_COMMANDS, [])
do.mount_all(cmds, relative_to=dats.folder)
do.mount(module=dat_tools, at="dat_tools")
do.mount(module=dat_tools, at="dt")
do.mount(value=dat_tools.cmd_list, at="dt.list")
do.mount(value=dat_tools.cmd_list, at="dat_tools.list")

__all__ = [
    "DAT_VERSION",
    "dats",
    "Dat",
    "DatContainer",
    "Dats",
    "DoManager",
    "do",
    "do_argv",
    "dat_tools",
]
