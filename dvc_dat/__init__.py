__version__ = "1.00.05"

from .dat import Dat, DatContainer, DatManager
from .config import DataConfig

__all__ = [
    "Dat",
    "DatContainer",
    "DatManager",
    "DataConfig",
]

# Optional: expose do_fn exports if available
try:
    from .do_fn import DoManager, do_argv, do
    __all__.extend(["DoManager", "do_argv", "do"])
except ImportError:
    pass  # do_fn not available in this environment
