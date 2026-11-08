"""dvc_dat — dats are folders whose `_spec_.yaml` is a complete, argumentless recipe.

    from dvc_dat import Dat, DatManager

    Dat.manager.run("catalog.experiment", epochs=10)  # forks a new spec, creates a dat, runs it
    Dat.create("catalog.experiment", epochs=10)       # the same dat, not run
    Dat.load("runs/2026-09/exp")             # opens a dat on disk
    Dat.manager = DatManager(dat_folders=["/work"])   # replaces the default world
    ns = Dat.ns                              # the namespace: ns.load, ns.mount, ns.mounts()

``import dvc_dat`` loads the ledger, ``L``, ``ledgers`` and ``dat``; the classes load on first use (1519 R1). The
package exports four classes, the two ledger handles, `L` (the active
ledger) and `ledgers` (the project's ledgers by name, `ledgers.record`), and `dat`,
the decorators (`@dat.fn`, `@dat.warm`, `@dat.command`); the
ledger, the dat's record in time, is its own subpackage: `from dvc_dat.ledger import Ledger`.
"""

__version__ = "3.0.0"

from . import ledger  # noqa: F401  (the ledger first: core's Dat is a ledger Value)
from . import dat
from .ledger.named import L, ledgers

#: The names loaded on first use (PEP 562), so ``import dvc_dat`` (and ``dvc_dat.ledger``) loads no Dat layer.
_LAZY = {"Dat": "core", "DatContainer": "core", "DatManager": "core", "Namespace": "namespace"}


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        value = getattr(importlib.import_module(f"{__name__}.{_LAZY[name]}"), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["Dat", "DatContainer", "DatManager", "Namespace", "L", "ledgers", "dat"]
