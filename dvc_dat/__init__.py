__version__ = "1.2.0"
DAT_VERSION = "1.2.0 (2026-08-27)"

from .dat import Dat, DatContainer, DatManager, DataConfig

__all__ = [
    "Dat",
    "DatContainer",
    "DatManager",
    "DataConfig",
    "DAT_VERSION",
]

# Optional: expose do_fn exports if available
try:
    from .do_fn import DoManager, do_argv, do
    __all__.extend(["DoManager", "do_argv", "do"])
except ImportError:
    pass  # do_fn not available in this environment
