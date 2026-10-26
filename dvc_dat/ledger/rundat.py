"""``rev.dat_run(target, **kwargs)``: a dat made, run and sealed through the ledger, memoised (DAT 1038, 1045).

``Dat.do(target, **kwargs)`` makes a dat outside the ledger: a fresh folder every
time, nothing recorded. ``rev.dat_run`` is its memoised form, the run function
executed for a dat, as ``rev.run`` executes a ``@ledger_fn``. The question is the
spec ``Dat.do`` would create from: ``target`` resolved (a mounted spec name, a
spec dict, or a dotted run function, which is the spec ``{dat: {do: <name>}}``),
its ``dat.base`` merged in, the kwargs merged into ``dat.kwargs``, ``dat.kind``
the class it makes, every ``{}`` expanded, and ``dat.name`` removed (the folder
template is not part of the question). ``db/fn`` is the run function's dotted
name, ``db/keys`` the question, ``db/returns`` the dat's class.

A hit is the sealed dat, its folder a view in the data folder at its name (at
``path=`` when given). A miss creates the dat in a work folder, runs it
(``manager.execute``), seals the folder, which the run function saved, as the
memo entry, and names it ``path=`` or the spec's ``dat.name`` template expanded
(``{unique}`` counting up in the data folder), else ``anonymous/Dat``. ``seal=``
and ``clean=`` are a run's (``Fn.__call__``). The dat's recorded dependencies
that are names on the ledger enter the trace as alias reads.

Where it runs is a ledger function's rule. A run function under a ``db/mount``
runs in the sandbox worker (``sandbox.run_dat_sandboxed``, DAT 1045): imported
there from the mounted tree (this process never imports it), confined to the
mounts, the dats and its work folder, its code the modules it loaded (the
mount's ``Code`` with the run's loads beside it), provenance ``eval:sandbox``.
Any other (installed) run function runs in this process, its code the static
closure of its module, recorded with ``code/<repo>`` at the checkout's commit
(a clean checkout to save), provenance ``eval:unsandboxed``.
"""

from __future__ import annotations

import copy
import os
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from .codec import canonical, ref_text
from .env import current_env, repo_of
from .fn import (ANONYMOUS, Fn, attach_run, check_clean, drop_work, encode_keys, fresh_name, installed_code,
                 lookup, mounts_at, place, run_trace, seal_entry, seal_level, source_of, work_folder)
from .value import dotted

if TYPE_CHECKING:
    from ..core import Dat
    from .rev import Rev


def _mounted(name: str, mounts: Dict[str, Dict[str, str]]) -> bool:
    """Is the dotted ``name`` under a ``db/mount`` prefix (so it is loaded in the worker, never here)."""
    return any(name.startswith(prefix + ".") for prefix in mounts)


def _load(name: str, mounts: Dict[str, Dict[str, str]]) -> Any:
    """What ``name`` names for ``Dat.do``: a name mounted in the dat world, else, under a ``db/mount``,
    the name itself (a run function the worker imports), else the object imported here."""
    from ..core import Dat
    from ..do import _DO_NULL

    do = Dat.manager.do
    obj = do._load_mounted(name)
    if obj is not _DO_NULL:
        return obj
    if _mounted(name, mounts):
        return _RunName(name)
    return do._load_static(name)


class _RunName(str):
    """A run function's dotted name under a ``db/mount``: never imported in this process."""


def question_of(target: Any, kwargs: Dict[str, Any],
                mounts: Dict[str, Dict[str, str]]) -> Tuple[Dict[str, Any], Optional[str], Dict[str, Any]]:
    """``(spec, template, question)``: the spec ``Dat.do(target, **kwargs)`` creates from (base merged,
    kwargs merged, ``dat.kind`` set, unexpanded), its ``dat.name`` template, and the question: that spec
    expanded with ``dat.name`` removed."""
    from ..core import Dat, _builtins, _kind_name

    manager = Dat.manager
    do = manager.do
    obj = _load(target, mounts) if isinstance(target, str) else target
    if isinstance(obj, Dat):
        raise TypeError(f"rev.dat_run takes a spec, a spec's name or a run function's name, not the dat {obj!r}")
    if callable(obj) or isinstance(obj, _RunName):
        if not isinstance(target, str):
            raise TypeError("rev.dat_run takes a run function by its dotted name; a function object would "
                            "resolve in this process only")
        obj = {"dat": {"do": target}}
    if not isinstance(obj, dict):
        raise TypeError(f"rev.dat_run: {target!r} is {type(obj).__name__}, not a spec or a run function")
    spec = do.resolve(copy.deepcopy(obj))
    spec = do._fork_spec(spec, (), kwargs)
    if not isinstance(spec.setdefault("dat", {}), dict):
        raise TypeError(f"rev.dat_run: spec['dat'] is a mapping, got {spec['dat']!r}")
    spec["dat"]["kind"] = _kind_name(manager._class_of(spec["dat"].get("kind")))
    template = spec["dat"].get("name")
    plain = copy.deepcopy(spec)
    plain["dat"].pop("name", None)
    question = manager.expand_spec(plain, _builtins())
    return spec, template, question


def run_fn(rev: "Rev", spec: Dict[str, Any], template: Optional[str],
           mounts: Dict[str, Dict[str, str]]) -> Fn:
    """The ``Fn`` naming the run function ``spec``'s ``dat.do`` names: its dotted name, its ``Code``. Under a
    ``db/mount`` it is found in the mounted file and runs in the worker (``sandbox.load_mounted_run``)."""
    from ..core import Dat

    target = Dat.get(spec, "dat.do", None)
    if target is None:
        raise TypeError("rev.dat_run: the spec names no run function (dat.do); a dat with nothing to run is "
                        "Dat.create's")
    do = Dat.manager.do
    obj = _load(target, mounts) if isinstance(target, str) else target
    returns = spec["dat"]["kind"]
    if isinstance(obj, _RunName):
        name = str(obj)
    else:
        if not callable(obj):
            raise TypeError(f"rev.dat_run: dat.do {target!r} is {obj!r}, not callable")
        name = do.name_of(obj)
        if getattr(obj, "__ledger_fn__", False):
            raise TypeError(f"rev.dat_run: {name} is a ledger function; rev.run({name!r}, ...) runs it")
    if _mounted(name, mounts):
        from .sandbox import load_mounted_run

        return load_mounted_run(rev, name, returns, template)
    import inspect

    modname, src = source_of(name, obj)
    env = current_env()
    return Fn(name=name, module=src, mount=None, signature=inspect.Signature(), env=env,
              code=installed_code(modname, src, env), _rev=rev, _obj=obj, _template=template, _returns=returns)


def dat_run(rev: "Rev", target: Any, *, seal: Any, clean: bool, path: Any,
            kwargs: Dict[str, Any]) -> Optional["Dat"]:
    """``Rev.dat_run``: see the module doc."""
    from ..core import Dat
    from .txn import Transaction

    plain = rev._plain()
    mounts = mounts_at(plain)
    spec, template, question = question_of(target, kwargs, mounts)
    fn = run_fn(rev, spec, template, mounts)
    level = seal_level(fn.name, plain, seal, clean, path)
    if clean:
        check_clean(fn, plain, current_env())
    enc = canonical(encode_keys(question))
    item = f"eval:{fn.name}{enc}"
    name = None if path is None else os.fspath(path)
    if level not in (True, False):
        hit = lookup(plain, fn.name, enc)
        if hit is not None or level == "get":
            rev._record(item, ref_text(dotted(type(hit)), hit.hash) if hit is not None else "<none>")
            if hit is not None and (name or hit.name):
                return place(plain.ledger, hit, name or hit.name)     # its folder at its name, a view
            return hit  # type: ignore[return-value]
    into = level if isinstance(level, Transaction) else None
    save: Any = True if isinstance(level, str) and level == "save" else (into if into is not None else False)
    keys = dict(Dat.get(spec, "dat.kwargs", None) or {})
    if into is not None and name is None:
        name = fresh_name(plain.ledger, template or ANONYMOUS, keys)
    if into is not None and os.path.isabs(name or ""):
        raise ValueError(f"{fn.name}: path={name!r} is absolute; with seal=t the dat is saved at commit, so it "
                         "takes a name (a relative path) or none")
    if fn.code.sandboxed:
        from .sandbox import run_dat_sandboxed

        shipped = copy.deepcopy(question)          # expanded here, through this world's mounts
        shipped["dat"]["do"] = fn.name              # the worker imports the run function by its dotted name
        if template is not None:
            shipped["dat"]["name"] = template
        value: Any = run_dat_sandboxed(fn, plain, shipped, enc, save, name if into is not None else None)
    else:
        value = _run_in_process(fn, plain, spec, enc, save, name if into is not None else None)
    if level is True:
        value.seal()
    rev._record(item, ref_text(dotted(type(value)), value.hash))
    if into is not None:
        return value
    if name is None:
        name = fresh_name(plain.ledger, template or ANONYMOUS, keys)
    return place(plain.ledger, value, name)


def _run_in_process(fn: Fn, plain: "Rev", spec: Dict[str, Any], enc: str, save: Any,
                    name: Optional[str]) -> Any:
    """An installed run function, run here: ``manager.execute`` on a dat made in a work folder; the code
    vouched for by a clean checkout (``code/<repo>`` at its commit), provenance ``eval:unsandboxed``."""
    from ..core import Dat
    from .rev import Ref, Rev
    from .txn import code_token

    env = current_env()
    repo = repo_of(env, fn.module)
    if save is not False:
        fn._check_code(plain, env, repo)
    rec: Dict[str, str] = {}
    work = work_folder()
    value: Any = None
    manager = Dat.manager
    try:
        dat = manager.create(spec, path=str(work / "dat"))
        manager.execute(dat)
        value = dat
        recording = Rev(plain.ledger, plain.id, _rec=rec)
        head = plain.ledger.at()
        for dep in sorted(Dat.get(dat.get_results(), "dat.dependencies", None) or {}):
            if head._held(dep, "db/alias"):
                Ref(recording, dep)                     # records `<dep> db/alias`, the binding it read
        trace = dict(rec)
        trace.update({"code": fn.code.subject, "fn": fn.name, "platform": env.platform})
        if repo is not None:
            trace[f"code/{repo}"] = code_token(env.code[repo].commit if repo in env.code else None)
        if save is False:
            dirty = bool(repo is not None and repo in env.code and env.code[repo].dirty)
            value = attach_run(dat, run_trace(fn, plain, trace, enc, "eval:unsandboxed", fn.code, repo=repo,
                                              dirty=dirty))
        else:
            value = seal_entry(fn, plain, dat, trace, enc, "eval:unsandboxed", fn.code, into=save,
                               name=name, repo=repo)
    finally:
        drop_work(work, value)
        if not work.exists():                           # its folder is gone: so is the dat world's index of it
            manager._index_forget(str(work / "dat"))
    return value
