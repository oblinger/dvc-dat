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
    from .do_fn import DoManager, do_argv
    __all__.extend(["DoManager", "do_argv"])
except ImportError:
    pass  # do_fn not available in this environment


# Convenience property to access the do manager from the Dat singleton
# This allows: from dvc_dat import do; do("some_command")
@property
def _do_property(self):
    return Dat.manager.do


# Create a module-level 'do' that proxies to Dat.manager.do
class _DoProxy:
    """Proxy object that delegates to Dat.manager.do."""
    def __getattr__(self, name):
        return getattr(Dat.manager.do, name)

    def __call__(self, *args, **kwargs):
        return Dat.manager.do(*args, **kwargs)


do = _DoProxy()
__all__.append("do")
