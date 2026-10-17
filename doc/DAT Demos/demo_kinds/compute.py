"""Two dat kinds for the dats demo: a list of integers, and a compute over other dats.

``Numbers`` is one channel, ``values``, made from a literal list and sealed at
once. ``Compute`` carries an expression in its spec, a lisp-shaped list
``["+", a, b, ...]`` or ``["*", a, b, ...]`` whose arguments are dat names or
nested expressions; running it loads each named dat through ``Dat.manager``, so
every load lands in ``dat.dependencies``, evaluates elementwise, and writes its
own ``values``. A ``Compute`` over a ``Compute`` is what the demo is for: the
dependency map goes two deep and the chain can be followed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Sequence

from dvc_dat import Dat

from demo_kinds.channels import ChannelDat, kind

__all__ = ["Value", "Numbers", "Compute", "evaluate"]

OPS = {"+": lambda xs: sum(xs), "*": lambda xs: _product(xs)}


def _product(xs: Sequence[int]) -> int:
    out = 1
    for x in xs:
        out *= x
    return out


@dataclass
class Value:
    """One integer at one position: the row of a ``values`` channel."""

    pos: int
    value: int


class Numbers(ChannelDat):
    """A list of integers: one channel, ``values``."""

    @classmethod
    def make(cls, name: str, values: Sequence[int]) -> "Numbers":
        """Create ``name`` holding ``values`` and seal it."""
        dat = Dat.manager.create({"dat": {"name": name, "kind": kind(cls)}})
        dat.write_channel("values", [Value(i, int(v)) for i, v in enumerate(values)])
        dat.save()
        return dat

    def values(self) -> List[int]:
        """The integers, in order."""
        return [int(v) for v in self.table("values")["value"].to_list()]


class Compute(Numbers):
    """``values`` = an expression over other dats, recorded in the spec as ``dat.kwargs.expr``."""

    @classmethod
    def make(cls, name: str, expr: Any) -> "Compute":  # type: ignore[override]
        """Create ``name`` with ``expr``, run it (every load recorded), seal it."""
        dat = Dat.manager.create({"dat": {"name": name, "kind": kind(cls), "kwargs": {"expr": expr}}})
        dat.compute()
        return dat

    def expr(self) -> Any:
        return self.kwargs()["expr"]

    def compute(self) -> "Compute":
        """Evaluate the expression inside a recording, write ``values``, seal. (``run`` is dvc-dat's name for a run sub-dat.)"""
        with Dat.manager.recording(self):
            values = evaluate(self.expr())
            self.write_channel("values", [Value(i, v) for i, v in enumerate(values)])
        self.save()
        return self


def evaluate(expr: Any) -> List[int]:
    """``["+", a, b]`` / ``["*", a, b]`` elementwise over dat names and nested expressions.

    A name loads through ``Dat.manager`` (recorded when inside a recording);
    the lists must agree in length.
    """
    if isinstance(expr, str):
        dat = Dat.manager.load(expr)
        if not isinstance(dat, Numbers):
            raise TypeError(f"{expr}: a Numbers or Compute dat, not {type(dat).__name__}")
        return dat.values()
    if not isinstance(expr, (list, tuple)) or not expr or expr[0] not in OPS:
        raise ValueError(f"an expression is a dat name or [op, arg, ...] with op in {sorted(OPS)}, got {expr!r}")
    op, args = OPS[expr[0]], [evaluate(a) for a in expr[1:]]
    if len({len(a) for a in args}) > 1:
        raise ValueError(f"{expr[0]}: the arguments differ in length ({[len(a) for a in args]})")
    return [op(col) for col in zip(*args)]
