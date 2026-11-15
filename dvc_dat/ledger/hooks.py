"""The Dat layer as the ledger sees it: a registry the Dat side fills, so the ledger never imports it first.

``import dvc_dat.ledger`` loads no ``dvc_dat.core`` and no ``dvc_dat.do`` (1519 R1). ``dvc_dat.core`` registers
``Dat`` here when it is imported, and ``dvc_dat.datrun`` registers the dat branch of a sandboxed run; the ledger
asks through these functions:

    hooks.is_dat(v)       # False until the Dat layer is loaded: no value can be a Dat before then
    hooks.dat_class()     # Dat, or None while nothing registered it
    hooks.manager()       # Dat.manager, the Dat layer imported by name first when it is not loaded
    hooks.layer()         # every registered part, ``dvc_dat.datrun`` (and with it ``core``) imported first

A stored dat read back by its class name (``rev.py``, ``importlib.import_module``) imports ``dvc_dat.core``, which
registers itself, so the ``isinstance`` after the decode sees the class.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Optional

_LAYER: Dict[str, Any] = {}
_DAT_SIDE = "dvc_dat.datrun"         # imports dvc_dat.core: every part registered


def register_dat_layer(**parts: Any) -> None:
    """Register parts of the Dat layer by name: ``Dat`` (the class, from ``dvc_dat.core``), and ``run_dat``,
    ``install_world``, ``world_of`` (the dat branch of a sandboxed run, from ``dvc_dat.datrun``)."""
    _LAYER.update(parts)


def dat_class() -> Optional[type]:
    """``Dat``, or ``None`` while the Dat layer is not loaded."""
    return _LAYER.get("Dat")


def is_dat(value: Any) -> bool:
    """Whether ``value`` is a ``Dat``; ``False`` while the Dat layer is not loaded (nothing can be one yet)."""
    cls = _LAYER.get("Dat")
    return cls is not None and isinstance(value, cls)


def layer() -> Dict[str, Any]:
    """Every part of the Dat layer, ``dvc_dat.datrun`` imported by name first when a part is missing."""
    if "run_dat" not in _LAYER:
        importlib.import_module(_DAT_SIDE)
    return _LAYER


def manager() -> Any:
    """The default dat world, ``Dat.manager``; the Dat layer is imported by name when it is not loaded yet."""
    cls = _LAYER.get("Dat") or layer()["Dat"]
    return cls.manager


__all__ = ["register_dat_layer", "dat_class", "is_dat", "layer", "manager"]
