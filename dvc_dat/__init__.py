__version__ = "1.00.05"
DAT_VERSION = f"{__version__} (2024-06-20)"

import __main__ as main
from .dat import DatManager, _DAT_MOUNT_COMMANDS
from .do_fn import DoManager, do_argv
from .dat import Dat, DatContainer
from . import dat_tools


if not hasattr(main, "NO_DAT_DVC_INIT"):
    dats = Dat.manager
    do = Dat.manager.do = DoManager()  # not available during load of do_fn

    from .dat import Dat, DatContainer
    from . import dat_tools

    cmds = Dat.manager.config.get(_DAT_MOUNT_COMMANDS, [])
    do.mount_all(cmds, relative_to=Dat.manager.folder)
    do.mount(module=dat_tools, at="dat_tools")
    do.mount(module=dat_tools, at="dt")
    do.mount(value=dat_tools.cmd_list, at="dt.list")
    do.mount(value=dat_tools.cmd_list, at="dat_tools.list")


__all__ = [
    "DAT_VERSION",
    "Dat",
    "DatContainer",
    "DatManager",
    "DoManager",
    "do",
    "do_argv",
    "dat_tools",
]
