"""``ChannelDat``: a dat whose data is named channels, each a list of rows in ``<channel>.json``.

A row is a plain dataclass; a channel is written once, before the seal, and
read back as a pandas DataFrame, one column per field. That is all the demo
kinds need of a storage format: the dat mechanics (spec, seal, hash,
dependencies) are dvc-dat's own.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from dvc_dat import Dat

__all__ = ["ChannelDat", "kind"]

_FROZEN = ("sealed", "referenceable")


def kind(cls: type) -> str:
    """The ``dat.kind`` naming ``cls``: its dotted module path."""
    return f"{cls.__module__}.{cls.__qualname__}"


class ChannelDat(Dat):
    """A dat holding channels: ``write_channel`` before the seal, ``table`` after."""

    def write_channel(self, name: str, rows: Iterable[Any]) -> None:
        """Write ``rows`` (dataclass instances) as channel ``name``; a sealed dat refuses."""
        standing = Dat.standing(self)
        if standing in _FROZEN:
            raise RuntimeError(f"write_channel: {self.get_path_name()!r} is {standing}; a sealed dat is not written")
        data = [dataclasses.asdict(r) for r in rows]
        Path(self.get_path(), f"{name}.json").write_text(json.dumps(data))

    def table(self, name: str) -> pd.DataFrame:
        """Channel ``name`` as a DataFrame, one row per row written."""
        return pd.DataFrame(json.loads(Path(self.get_path(), f"{name}.json").read_text()))

    def kwargs(self) -> dict:
        """The call's parameters, ``dat.kwargs`` in the spec."""
        return dict(Dat.get(self.get_spec(), "dat.kwargs", {}))
