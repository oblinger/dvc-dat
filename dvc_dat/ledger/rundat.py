"""``rev.run(target, **kwargs)``: one call for a ledger function and a dat (DAT 1038, 1045, 1046).

The target is resolved through the ledger's namespace (``rev.ns.load``): a
``@ledger_fn`` comes back its ``Fn`` and is called with the kwargs as its keys.
Anything else is a dat: a spec (a dict, or a name resolving to one, from a
mounted ``.yaml``/``.json`` or a literal in a mounted module) or a dat's run
function by its dotted name, which is the spec ``{dat: {do: <name>}}``. Its memo
key is the spec ``Dat.ns`` would create from: ``dat.base`` merged, the kwargs
merged into ``dat.kwargs``, ``dat.kind`` the class it makes, every ``{}``
expanded once here with names through the ledger's namespace, and ``dat.name``
removed (the folder template is not part of the key, it names the result). The
run function named by ``dat.do`` resolves to an ``Fn`` of kind ``"dat"``, called
with the memo key as its keys; ``Fn.__call__`` does the rest, as for any ledger
function: the lookup, and on a miss the run (in the sandbox worker when the run
function is mounted, in this process when installed), the seal and the place.
``db/fn`` is the run function's dotted name, ``db/keys`` the memo key,
``db/returns`` the dat's class.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from .fn import Fn, installed_fn

if TYPE_CHECKING:
    from .namespace import LedgerNamespace
    from .rev import Rev


def run(rev: "Rev", target: Any, *, seal: Any, clean: bool, path: Any, kwargs: Dict[str, Any],
        deterministic: bool = False) -> Any:
    """``Rev.run``: see the module doc."""
    from .namespace import LedgerNamespace

    ns = LedgerNamespace(rev=rev)
    if isinstance(target, str):
        obj = ns.load(target)
        if isinstance(obj, Fn) and obj.kind == "ledger":
            return obj(seal=seal, clean=clean, path=path, deterministic=deterministic, **kwargs)
    elif isinstance(target, dict):
        obj = target
    else:
        raise TypeError(f"run takes a dotted name or a spec dict, not {type(target).__name__}; a function "
                        "object would resolve in this process")
    fn, keys = memo_key(rev, ns, target, obj, kwargs)
    return fn(seal=seal, clean=clean, path=path, kwargs=keys, deterministic=deterministic)


def memo_key(rev: "Rev", ns: "LedgerNamespace", target: Any, obj: Any,
             kwargs: Dict[str, Any]) -> Tuple[Fn, Dict[str, Any]]:
    """``(fn, keys)`` of a dat run: the run function's ``Fn`` (its template and class set) and the memo key,
    the spec expanded with ``dat.name`` removed."""
    from ..core import Dat, _builtins, _kind_name, expand_spec

    if isinstance(obj, Dat):
        raise TypeError(f"run takes a spec, a spec's name or a function's name, not the dat {obj!r}")
    if isinstance(obj, Fn) or callable(obj):           # a run function alone
        obj = {"dat": {"do": target}}
    if not isinstance(obj, dict):
        raise TypeError(f"run: {target!r} is {type(obj).__name__}, not a spec or a function")
    spec = ns._merge_bases(copy.deepcopy(obj))
    spec = ns._fork_spec(spec, (), kwargs)
    if not isinstance(spec.setdefault("dat", {}), dict):
        raise TypeError(f"run: spec['dat'] is a mapping, got {spec['dat']!r}")
    spec["dat"]["kind"] = _kind_name(Dat.manager._class_of(spec["dat"].get("kind")))
    template: Optional[str] = spec["dat"].pop("name", None)
    keys = expand_spec(spec, _builtins(), resolver=ns.load)
    fn = run_fn(rev, ns, keys)
    return dataclasses.replace(fn, _template=template, _returns=keys["dat"]["kind"]), keys


def run_fn(rev: "Rev", ns: "LedgerNamespace", keys: Dict[str, Any]) -> Fn:
    """The ``Fn`` of kind ``"dat"`` the spec's ``dat.do`` names: mounted, read off its file (it runs in the
    worker); installed, imported here."""
    name = keys["dat"].get("do")
    if name is None:
        raise TypeError("run: the spec names no run function (dat.do); a dat with nothing to run is "
                        "Dat.create's")
    if not isinstance(name, str):
        raise TypeError(f"run: dat.do is a run function's dotted name, not {name!r}")
    obj = ns.load(name)
    if isinstance(obj, Fn):
        if obj.kind == "ledger":
            raise TypeError(f"run: {name} is a ledger function; rev.run({name!r}, **keys) runs it, not a spec")
        return obj
    if not callable(obj):
        raise TypeError(f"run: dat.do {name!r} is {obj!r}, not callable")
    return installed_fn(rev, name, obj)
