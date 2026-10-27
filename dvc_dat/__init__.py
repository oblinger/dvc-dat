"""dvc_dat — dats are folders whose `_spec_.yaml` is a complete, argumentless recipe.

    from dvc_dat import Dat, DatManager

    Dat.manager.run("catalog.experiment", epochs=10)  # forks a new spec, creates a dat, runs it
    Dat.load("runs/2026-09/exp")             # opens a dat on disk
    Dat.manager = DatManager(dat_folders=["/work"])   # replaces the default world
    ns = Dat.ns                              # the namespace: ns.load, ns.mount, ns.mounts()

The package exports four classes; everything else hangs off them. The ledger,
the dat's record in time, is its own subpackage: `from dvc_dat.ledger import Ledger`.
"""

__version__ = "2.37.1"

from . import ledger  # noqa: F401  (first: core's Dat is a ledger Value, and the ledger names Dat)
from .core import Dat, DatContainer, DatManager
from .do import Namespace

__all__ = ["Dat", "DatContainer", "DatManager", "Namespace"]
