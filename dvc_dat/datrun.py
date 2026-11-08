"""The dat branch of a sandboxed run (DAT 1045, 1046): the Dat layer's side of ``dvc_dat.ledger.sandbox``.

The sandbox imports nothing of the Dat layer (1519 R1); it reaches these through ``dvc_dat.ledger.hooks``, which
imports this module by name the first time a dat runs in a process. Importing it imports ``dvc_dat.core``, which
registers ``Dat``; this module registers the three parts below:

    run_dat(fn, run, spec, work)   # the dat made from the spec in the work folder, run with ``run`` as its dat.do
    world_of()                     # the caller's dat world, as shipped to the worker
    install_world(w, plain)        # in the worker: Dat.manager rebuilt from it, its names the run's rev's
"""

from __future__ import annotations

import functools
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterator

from .core import Dat, DatManager
from .ledger import hooks
from .ledger.fn import Fn, dat_spec
from .ledger.sandbox import STATE, unguarded

if TYPE_CHECKING:
    from .ledger.rev import Rev


class _WorkerWorld(DatManager):
    """The dat world of a dat run in the worker (DAT 1045): the caller's dat folders and art folder. Its
    index (a dat's hash to its name) is the dat world's own machinery, so its writes stand outside the
    guard, as the ledger's own. Its ``ns`` is a ``LedgerNamespace`` bound to the run's rev (DAT 1047): a name the
    body looks up (``Dat.manager.ns.load``, a spec's ``base``/``do``, ``{}`` expansion) walks the same
    ``db/mount`` rows the caller resolved the run through, read from the worker's checkout; ``mount`` is
    refused."""

    @contextmanager
    def _index_update(self) -> Iterator[Dict[str, Dict[str, str]]]:
        with unguarded():
            with super()._index_update() as index:
                yield index


def run_dat(fn: Fn, run: Any, spec: Dict[str, Any], work: Path) -> Dat:
    """The dat branch of ``sandbox.run_here``: ``Dat.manager.create`` from the spec in ``work``, then ``_execute`` with
    ``run`` (imported from the mounts) as its ``dat.do``, its body confined (writes only in the work
    folder); the world's own machinery around it unguarded."""
    manager = Dat.manager

    @functools.wraps(run)
    def confined(*args: Any, **kwargs: Any) -> Any:
        old = STATE.guard
        STATE.guard = True
        try:
            return run(*args, **kwargs)
        finally:
            STATE.guard = old
    registered = manager.ns._registered_values or {}
    before = registered.get(fn.name, _NONE)
    manager.ns._reg_value(fn.name, confined)       # _execute loads dat.do through the world
    try:
        dat = manager.create(dat_spec(spec, fn._template), path=str(work / "dat"))
        manager._execute(dat)
    finally:
        values = manager.ns._registered_values or {}
        if before is _NONE:
            values.pop(fn.name, None)
        else:
            values[fn.name] = before
    return dat


_NONE = object()


def world_of() -> Dict[str, Any]:
    """The caller's dat world (``Dat.manager``) as a dat run ships it to the worker: its folders, index and
    verify flag, built afresh there (``install_world``)."""
    world = Dat.manager
    return {"dat_folders": list(world._dat_folders), "art_folder": world._art_folder,
            "index": world._index_file, "verify": world._verify}


def install_world(w: Dict[str, Any], plain: "Rev") -> None:
    """In the worker: ``Dat.manager`` is the caller's dat world ``w`` (``world_of``), its namespace the run's rev's."""
    from .ledger.namespace import LedgerNamespace

    Dat.manager = _WorkerWorld(dat_folders=w["dat_folders"], art_folder=w["art_folder"],
                               index=w["index"], verify=w["verify"], ns=LedgerNamespace(rev=plain))


hooks.register_dat_layer(run_dat=run_dat, world_of=world_of, install_world=install_world)
