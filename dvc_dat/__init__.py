__version__ = "1.1.0"
DAT_VERSION = "1.1.0 (2025-11-28)"

from .dat import Dat, DatContainer, DatManager, DataConfig

__all__ = [
    "Dat",
    "DatContainer",
    "DatManager",
    "DataConfig",
    "DAT_VERSION",
]

# do_fn is part of this package and imports cleanly (stdlib + yaml + .dat, and
# .dat is already loaded above). It was guarded by `except ImportError: pass`,
# which could only ever have hidden a real bug inside do_fn -- handing callers a
# package silently missing `do`.
#
# Importing it here does not ACTIVATE the do-system: DatManager.do defaults to
# SimpleMethodManager, and dat.py imports do_fn lazily, only when mount_commands
# is configured. dat.py itself remains importable with no do_fn at all.
from .do_fn import DoManager, do_argv, do

__all__ += ["DoManager", "do_argv", "do"]
