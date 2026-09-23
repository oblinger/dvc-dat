"""dvc_dat 2.6 — dats are folders whose `_spec_.yaml` is a complete, argumentless recipe.

    from dvc_dat import Dat, DatManager, do, expand

    do("catalog.experiment", epochs=10)   # forks a new spec, creates a dat, runs it
    Dat.load("runs/2026-09/exp")          # opens a dat on disk
    Dat.manager = DatManager(dat_folders=["/work"])   # replaces the default world
"""

__version__ = "2.6.0"

from .core import (
    Dat,
    DatContainer,
    DatManager,
    expand,
    expand_spec,
    merge_dicts,
)
from .do import Do, cli_main, do

__all__ = [
    "Dat",
    "DatContainer",
    "DatManager",
    "Do",
    "cli_main",
    "do",
    "expand",
    "expand_spec",
    "merge_dicts",
]
