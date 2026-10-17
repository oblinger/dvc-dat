"""Four dat kinds for the ETL demo: datasets built on datasets.

``Gamey`` is "a game": one channel, ``values``, a seeded list of integers.
``Binning`` is the model: fit over named gameys, it drops the ``trim`` fraction
from each end of the pooled values and writes ``bins`` equal-width bins as one
channel, ``edges``. ``Trial`` places one gamey into one binning: channel
``placements`` (each value's bin and its position inside it), and in the result
the ``podium``, the three fullest bins. ``Metrics`` summarises a trial in its
result alone. Each stage loads its inputs inside a recording, so the seal lists
them in ``dat.dependencies`` (trimmed to the roots).
"""

from __future__ import annotations

import random
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any, List, Sequence, Tuple

from dvc_dat import Dat

from demo_kinds.channels import ChannelDat, kind
from demo_kinds.compute import Value

__all__ = ["Edge", "Placement", "Gamey", "Binning", "Trial", "Metrics"]


@dataclass
class Edge:
    """One bin edge: the row of an ``edges`` channel (``bins + 1`` rows)."""

    pos: int
    edge: float


@dataclass
class Placement:
    """One value placed: its bin and its position in [0, 1) inside that bin."""

    pos: int
    value: int
    bin: int
    residual: float


def _create(cls: type, name: str, **kwargs: Any) -> Any:
    return Dat.manager.create({"dat": {"name": name, "kind": kind(cls), "kwargs": kwargs}})


def _load(name: str, cls: type) -> Any:
    dat = Dat.manager.load(name)
    if not isinstance(dat, cls):
        raise TypeError(f"{name}: a {cls.__name__} dat, not {type(dat).__name__}")
    return dat


class Gamey(ChannelDat):
    """A game: ``n`` integers in 0..999 from two overlapping clusters, reproducible from ``seed``."""

    @classmethod
    def make(cls, name: str, n: int = 200, seed: int = 0) -> "Gamey":
        """Create ``name`` from ``seed`` and seal it."""
        dat = _create(cls, name, n=n, seed=seed)
        rng = random.Random(seed)
        values = []
        for _ in range(n):
            mu, sigma = (350, 90) if rng.random() < 0.6 else (620, 70)
            values.append(min(999, max(0, round(rng.gauss(mu, sigma)))))
        dat.write_channel("values", [Value(i, v) for i, v in enumerate(values)])
        dat.save()
        return dat

    def values(self) -> List[int]:
        """The integers, in order."""
        return [int(v) for v in self.table("values")["value"].to_list()]


class Binning(ChannelDat):
    """The model: ``bins`` equal-width bins over the pooled ``games``, ``trim`` dropped from each end."""

    @classmethod
    def make(cls, name: str, games: Sequence[str], bins: int = 8, trim: float = 0.05) -> "Binning":
        """Create ``name``, fit it (every game load recorded), seal it."""
        dat = _create(cls, name, games=list(games), bins=bins, trim=trim)
        with Dat.manager.recording(dat):
            pooled = sorted(v for g in games for v in _load(g, Gamey).values())
            k = int(len(pooled) * trim)
            kept = pooled[k:len(pooled) - k]
            lo, hi = float(kept[0]), float(kept[-1])
            edges = [lo + i * (hi - lo) / bins for i in range(bins + 1)]
            dat.write_channel("edges", [Edge(i, e) for i, e in enumerate(edges)])
        dat.save()
        return dat

    def edges(self) -> List[float]:
        """The ``bins + 1`` edges, ascending."""
        return [float(e) for e in self.table("edges")["edge"].to_list()]


class Trial(ChannelDat):
    """One gamey placed into one binning; the result's ``podium`` is the three fullest bins, first to third."""

    @classmethod
    def make(cls, name: str, game: str, binning: str) -> "Trial":
        """Create ``name``, place every value (both loads recorded), seal it."""
        dat = _create(cls, name, game=game, binning=binning)
        with Dat.manager.recording(dat):
            values = _load(game, Gamey).values()
            edges = _load(binning, Binning).edges()
            rows = [Placement(i, v, *_place(v, edges)) for i, v in enumerate(values)]
            dat.write_channel("placements", rows)
        counts = Counter(r.bin for r in rows)
        dat.get_results()["podium"] = [b for b, _ in sorted(counts.items(), key=lambda bc: (-bc[1], bc[0]))[:3]]
        dat.save()
        return dat

    def podium(self) -> List[int]:
        """First, second and third place: the bins holding the most values."""
        return list(self.get_results()["podium"])


def _place(v: int, edges: Sequence[float]) -> Tuple[int, float]:
    """``(bin, residual)``: outside values go to the first / last bin, residual clamped into [0, 1)."""
    bins, width = len(edges) - 1, (edges[-1] - edges[0]) / (len(edges) - 1)
    pos = (v - edges[0]) / width if width > 0 else 0.0
    b = min(bins - 1, max(0, int(pos // 1)))
    return b, min(max(pos - b, 0.0), 0.999999)


class Metrics(ChannelDat):
    """A trial summarised: ``max``, ``min``, ``mean`` of the values; ``residual`` min, mean, spread (std)."""

    @classmethod
    def make(cls, name: str, trial: str) -> "Metrics":
        """Create ``name`` over ``trial`` (recorded), write the summary into the result, seal."""
        dat = _create(cls, name, trial=trial)
        with Dat.manager.recording(dat):
            table = _load(trial, Trial).table("placements")
        values, residuals = table["value"].to_list(), table["residual"].to_list()
        res = dat.get_results()
        res.update(max=int(max(values)), min=int(min(values)), mean=statistics.fmean(values))
        res["residual"] = {"min": float(min(residuals)), "mean": statistics.fmean(residuals),
                           "spread": statistics.pstdev(residuals)}
        dat.save()
        return dat
