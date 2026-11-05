"""``@dat.warm``: a process-level memo for boot computations the author promises not to mutate (SVP 250 A7).

    from dvc_dat import dat

    @dat.warm
    def kit_at(ledger, rev) -> Kit: ...        # computed once per process per (ledger, rev)

    @dat.warm
    def load_model(asset: Value) -> Model: ... # once per model hash

A warm function's result is keyed by the canonical hash of its arguments, bound to its signature with
defaults applied: a ``Value`` by its hash (sealed; an unsealed one is refused, since its bytes may still
move), a ``Ref`` by its subject, a ``Rev`` by its ledger and revision, a ``Ledger`` by its location, and plain
data (a spec dict, a str, a number, a list) by ``canonical()``; anything else is ``TypeError`` at the call.
The result stays in this process and comes back to any later call with the same key; the process is at one
commit, so the commit is in the key by construction. The store is one bounded LRU per process (``warm.max_bytes``,
``DAT_WARM_BYTES``, 2 GiB by default), sizes estimated by ``size_of`` (numpy by ``nbytes``, torch by
``numel * element_size``, pandas by ``memory_usage(deep=True)``, bytes and str by length, containers and
objects summed); a result larger than the whole budget is returned and not kept.

The memo is invisible to the ledger: a ledger function calling a warm function records the same reads as if the
warm function had run, so rerunnability is untouched, and a fresh-process rerun is what catches a broken
promise, as a hash that differs. The promise is the author's: the result is never mutated.
"""

from __future__ import annotations

import functools
import inspect
import os
import sys
import threading
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Tuple

from .codec import canonical, hash_text, ref_text
from .value import Value, dotted

ENV_BYTES = "DAT_WARM_BYTES"
DEFAULT_BYTES = 2 ** 31


def key_of(v: Any, what: str) -> Any:
    """One argument's part of a warm key (module doc); ``TypeError`` for what has no stable identity."""
    from .fn import ledger_key
    from .ledger import Ledger
    from .rev import Ref, Rev

    if isinstance(v, Value):
        if v.subject is None and not v.sealed:
            raise TypeError(f"{what}: an unsealed {type(v).__name__} is no warm key; seal it first (its hash is "
                            "then fixed)")
        return ["value", ref_text(dotted(type(v)), v.hash)]
    if isinstance(v, Ref):
        return ["ref", v.subject or v._text()]
    if isinstance(v, Rev):
        return ["rev", ledger_key(v.ledger), v.id]
    if isinstance(v, Ledger):
        return ["ledger", ledger_key(v)]
    try:
        text = canonical(v, strict=True)
    except (TypeError, ValueError) as e:
        raise TypeError(f"{what}: a {type(v).__name__} is no warm key ({e}); a key is a sealed Value, a Ref, a Rev, "
                        "a Ledger or plain data") from None
    return ["data", text]


def size_of(obj: Any) -> int:
    """An estimate of the bytes ``obj`` holds (module doc): arrays, frames and tensors by their own count,
    bytes and str by length, containers and objects by their members, the rest ``sys.getsizeof``."""
    seen: set = set()

    def walk(o: Any) -> int:
        if id(o) in seen:
            return 0
        seen.add(id(o))
        nbytes = getattr(o, "nbytes", None)
        if isinstance(nbytes, int):
            return nbytes
        if callable(getattr(o, "numel", None)) and callable(getattr(o, "element_size", None)):
            try:
                return int(o.numel()) * int(o.element_size())
            except Exception:  # noqa: BLE001 - an estimate
                pass
        if callable(getattr(o, "memory_usage", None)):
            try:
                used = o.memory_usage(deep=True)
                return int(used.sum() if hasattr(used, "sum") else used)
            except Exception:  # noqa: BLE001 - an estimate
                pass
        if isinstance(o, (bytes, bytearray, str)):
            return len(o)
        if isinstance(o, dict):
            return sys.getsizeof(o) + sum(walk(k) + walk(v) for k, v in o.items())
        if isinstance(o, (list, tuple, set, frozenset)):
            return sys.getsizeof(o) + sum(walk(x) for x in o)
        d = getattr(o, "__dict__", None)
        if isinstance(d, dict) and not isinstance(o, type):
            return sys.getsizeof(o) + walk(d)
        return sys.getsizeof(o)
    return walk(obj)


class Warm:
    """The process's warm store and its decorator: ``@dat.warm`` on a function; ``warm.clear()``;
    ``warm.stats()`` (``entries``, ``bytes``, ``max_bytes``, ``hits``, ``misses``)."""

    def __init__(self, max_bytes: Optional[int] = None) -> None:
        env = os.environ.get(ENV_BYTES)
        self.max_bytes = int(max_bytes if max_bytes is not None else (env if env else DEFAULT_BYTES))
        self._cache: "OrderedDict[Tuple[str, str], Tuple[Any, int]]" = OrderedDict()
        self._lock = threading.Lock()
        self.bytes = 0
        self.hits = 0
        self.misses = 0

    def __call__(self, func: Callable) -> Callable:
        """Mark ``func`` warm: the decorator. Returns a wrapper with ``__wrapped__`` the function."""
        if not callable(func) or isinstance(func, type):
            raise TypeError(f"@dat.warm goes on a function, not {func!r}")
        sig = inspect.signature(func)
        ident = f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def warmed(*args: Any, **kwargs: Any) -> Any:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            parts = {k: key_of(v, f"{ident}: argument {k!r}") for k, v in bound.arguments.items()}
            key = (ident, hash_text(canonical(parts)))
            with self._lock:
                hit = self._cache.get(key)
                if hit is not None:
                    self._cache.move_to_end(key)
                    self.hits += 1
                    return hit[0]
                self.misses += 1
            out = func(*args, **kwargs)
            self._keep(key, out)
            return out
        warmed.__dat_warm__ = True  # type: ignore[attr-defined]
        return warmed

    def _keep(self, key: Tuple[str, str], out: Any) -> None:
        size = size_of(out)
        if size > self.max_bytes:
            return                                  # larger than the whole budget: handed back, not kept
        with self._lock:
            old = self._cache.pop(key, None)
            if old is not None:
                self.bytes -= old[1]
            self._cache[key] = (out, size)
            self.bytes += size
            while self.bytes > self.max_bytes and self._cache:
                _k, (_v, n) = self._cache.popitem(last=False)
                self.bytes -= n

    def clear(self) -> None:
        """Drop every kept result."""
        with self._lock:
            self._cache.clear()
            self.bytes = 0

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"entries": len(self._cache), "bytes": self.bytes, "max_bytes": self.max_bytes,
                    "hits": self.hits, "misses": self.misses}

    def __repr__(self) -> str:
        s = self.stats()
        return f"<warm {s['entries']} entries, {s['bytes']} of {s['max_bytes']} bytes, {s['hits']} hits>"


#: The process's one warm store; ``dat.warm`` is this object.
warm = Warm()

__all__ = ["Warm", "warm", "key_of", "size_of"]
