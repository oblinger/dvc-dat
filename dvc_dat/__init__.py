"""dvc_dat 2.11 — dats are folders whose `_spec_.yaml` is a complete, argumentless recipe.

    from dvc_dat import Dat, DatManager

    Dat.do("catalog.experiment", epochs=10)  # forks a new spec, creates a dat, runs it
    Dat.load("runs/2026-09/exp")             # opens a dat on disk
    Dat.manager = DatManager(dat_folders=["/work"])   # replaces the default world
    do = Dat.do                              # a shortcut that follows Dat.manager

The package exports four classes; everything else hangs off them.
"""

__version__ = "2.11.0"

from .core import Dat, DatContainer, DatManager
from .do import Do

__all__ = ["Dat", "DatContainer", "DatManager", "Do"]
