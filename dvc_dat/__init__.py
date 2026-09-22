"""dvc_dat 2.0 — dats are folders whose `_spec_.yaml` is a complete, argumentless recipe.

    from dvc_dat import Dat, do, load, expand

    do("catalog.experiment", epochs=10)   # forks a new spec, creates a dat, runs it
    load("runs/2026-09/exp")              # opens a dat on disk
"""

__version__ = "2.0.0"

from .core import (
    DataConfig,
    Dat,
    DatContainer,
    DatManager,
    expand,
    expand_spec,
)
from .do import Do, cli_main, do, do_argv

load = Dat.load   # open a dat by path or name

__all__ = [
    "Dat",
    "DatContainer",
    "DatManager",
    "DataConfig",
    "Do",
    "cli_main",
    "do",
    "do_argv",
    "load",
    "expand",
    "expand_spec",
]
