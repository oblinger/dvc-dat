__version__ = "1.00.05"
DAT_VERSION = f"{__version__} (2024-06-20)"

import __main__ as main
from .dat import DatManager
from .do_fn import DoManager, do_argv
from .dat import Dat, DatContainer


# Initialize the 'do' manager unless explicitly disabled
if not hasattr(main, "NO_DAT_DVC_INIT"):
    from . import dat_tools

    # Create the DoManager instance
    do = DoManager()
    Dat._manager.do = do

    # Mount dat_tools module at convenient locations
    do.mount(module=dat_tools, at="dat_tools")
    do.mount(module=dat_tools, at="dt")
    do.mount(value=dat_tools.cmd_list, at="dt.list")
    do.mount(value=dat_tools.cmd_list, at="dat_tools.list")
else:
    do = None


__all__ = [
    "DAT_VERSION",
    "Dat",
    "DatContainer",
    "DatManager",
    "DoManager",
    "do",
    "do_argv",
]
