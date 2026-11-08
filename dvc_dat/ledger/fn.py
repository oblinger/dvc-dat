"""``dat.fn``, ``Fn`` and ``run`` (``Fn.__call__``): a revision function resolved at a ``Rev``.

``@dat.fn`` (``from dvc_dat import dat``) declares and returns the function unchanged (A52): a plain call
runs the body and returns an unsealed ``Value``, recording nothing;
``@dat.fn(reproducible=...)`` adds a claim about the function (``FnMark``, ``claim``, SVP 251 Q2).
``rev.ns.load(name)`` resolves a dotted name at a revision; a function comes
back an ``Fn``: under a mounted prefix (``db/mount/<prefix>`` rows) a sandboxed
function, read off the mounted file and run in a worker (``sandbox``);
otherwise an installed one, resolved in this process. Its ``kind`` is
``"ledger"`` for a ``@dat.fn`` (its keys are its memo key and it receives
them) and ``"dat"`` for an undecorated function, a dat's run function (its memo
key is the expanded spec, and it receives the dat made from it; DAT 1046).
Calling the ``Fn`` is ``run``: a memo lookup over
every entry at the top whose ``db/fn`` and ``db/keys`` rows match, each
candidate's dependencies matched against the rev, the latest-sealed match winning
(Q20, A20); on a miss, run, trace its reads, and send the result where ``seal=``
says (DAT 1028): ``"get"`` never runs; ``False`` keeps nothing; ``True`` seals it
locally; a ``Ledger`` (the default: the fn's own) or an open ``Transaction`` saves
it as the memo entry, ``db/fn``, ``db/keys`` and ``db/provenance
eval:unsandboxed|eval:sandbox``. Every run attaches its trace to the result
(``RunTrace``, ``v.__dict__["_run"]``), so a draft sealed later with ``v.seal(L)``
or ``v.seal(t)`` becomes the same memo entry.
"""

from __future__ import annotations

import inspect
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple

from .claim import PREDICATE as REPRODUCIBLE, claim_text, clauses, widens
from .codec import canonical, dotted_get, hash_text, ref_text, sha256
from .env import Env, current_env, platform_items, repo_of
from .errors import ConfinedWrite, NotClean, NotEvaluated
from .policy import EXACT_FIELDS
from .code import Code
from .value import Blob, Value, check_loadable, dotted
from . import hooks

if TYPE_CHECKING:
    from .rev import Rev

#: The control options of a call (Q41): never keys, never hashed. A function may declare one as a
#: key and is then called through ``kwargs=``; a declared ``path`` is the folder it builds (Q36).
RESERVED_KEYS = ("seal", "clean", "path", "kwargs")
#: The name a folder-producing miss gets with neither ``path=`` nor a template (as ``Dat.create``).
ANONYMOUS = "anonymous/Dat${unique:}"


class _Own:
    """``seal=``'s default: the ledger the function was loaded from."""

    def __repr__(self) -> str:
        return "<the fn's ledger>"


#: A run's result: the revision its run read (SVP 245), beside ``db/fn`` and ``db/keys``; read back as ``v.at``.
AT = "db/at"

#: The default of ``seal=`` (``Fn.__call__``, ``Rev.run``): save to the fn's own ledger.
OWN: Any = _Own()


def ledger_key(ledger: Any) -> str:
    """One ledger, however it was opened: its DSN, or its folder's real path."""
    from .pgstore import is_dsn

    text = str(ledger.path)
    return text if is_dsn(text) else os.path.realpath(text)


@dataclass(frozen=True)
class RunTrace:
    """What one run knew, kept on its unsaved result (``v.__dict__["_run"]``): enough for a later
    ``v.seal(L)`` / ``v.seal(t)`` to write the memo entry a memoised run writes (DAT 1028).

    ``trace`` is the dependencies (``code``, ``fn``, platform, ``code/<repo>``, every read); ``code_rows``
    the ``db/code/<hash 16>`` item's rows; ``repo`` and ``dirty`` the checkout that vouches for an
    unsandboxed run (``repo`` ``None`` outside any), for the code check at a late save. ``clock`` is
    ``(repo, package, version, commit)`` of the code that ran, sandboxed or not, for the
    ``db/repo/<repo>/<package> db/version`` and ``db/repo/<repo> db/commit`` a seal advances (DAT 1043, 1044);
    ``None`` outside any checkout or when the code declares no version. ``reproducible`` is the function's claim as
    its ``db/reproducible`` row holds it (``claim``), ``None`` for no row. ``at`` is the revision the run read, its
    ``db/at`` row (SVP 245); ``None`` only on a seal record written before the row existed."""

    name: str
    enc: str
    trace: Dict[str, str]
    provenance: str
    code_subject: str
    code_rows: Tuple[Tuple[str, str], ...]
    ledger: str
    sandboxed: bool
    repo: Optional[str] = None
    dirty: bool = False
    returns: str = ""
    clock: Optional[Tuple[str, str, str, str]] = None
    reproducible: Optional[str] = None
    at: Optional[int] = None

    def record(self) -> Dict[str, Any]:
        """As JSON, for a ``v.seal()`` seal record."""
        d = dict(self.__dict__)
        d["code_rows"] = [list(r) for r in self.code_rows]
        d["clock"] = list(self.clock) if self.clock is not None else None
        return d

    @classmethod
    def from_record(cls, d: Dict[str, Any]) -> "RunTrace":
        d = dict(d)
        d["code_rows"] = tuple(tuple(r) for r in d["code_rows"])
        d["clock"] = tuple(d["clock"]) if d.get("clock") else None
        return cls(**d)


def clock_of(fn: "Fn", code: Code) -> Optional[Tuple[str, str, str, str]]:
    """``(repo, package, version, commit)`` of ``code`` as ``fn`` ran it: the repo its checkout is (the
    mount's for sandboxed code), the package whose declared version it is (``code.package``), that version
    and the checkout's commit at load; ``None`` outside any checkout or with no declared version."""
    repo = fn._info.get("repo") if fn.code.sandboxed else repo_of(fn.env, fn.module)
    if not repo or not code.commit or code.package is None:
        return None
    return (repo, code.package, code.version, code.commit)


def run_trace(fn: "Fn", plain: "Rev", trace: Dict[str, str], enc: str, provenance: str,
              code: Code, repo: Optional[str] = None, dirty: bool = False) -> RunTrace:
    """``code`` is what ran: ``fn.code``, with a sandboxed run's run-time loads beside its own."""
    return RunTrace(name=fn.name, enc=enc, trace=dict(trace), provenance=provenance, code_subject=code.subject,
                    code_rows=tuple(code._rows()), ledger=ledger_key(plain.ledger), sandboxed=fn.code.sandboxed,
                    repo=repo, dirty=dirty, returns=fn._returns, clock=clock_of(fn, code),
                    reproducible=claim_text(fn.reproducible), at=plain.id)


def attach_run(value: Value, run: RunTrace) -> Value:
    """A draft: its trace on it, as ``dependencies`` and as the ``RunTrace`` a later save uses."""
    value.dependencies = dict(run.trace)  # type: ignore[misc]
    if not value.sealed:                    # a body's own v.seal() is refused at any save
        value.__dict__["_run"] = run
    return value


def check_late_code(run: RunTrace, env: Env) -> None:
    """A late save of an unsandboxed run (DAT 1028): the code that ran is vouched for by a clean
    checkout at the commit the trace names, as a memoised run's ``_check_code``; ``NotEvaluated``."""
    if run.sandboxed:
        return                              # the code item records the bytes it loaded
    if run.repo is None:
        raise NotEvaluated(f"{run.name}: its code is outside any git checkout, so no commit can vouch "
                           "for a result")
    if run.dirty:
        raise NotEvaluated(f"{run.name}: it ran on a checkout of {run.repo} with uncommitted changes; "
                           "the result would carry false provenance")
    code = env.code.get(run.repo)
    if code is None or code.dirty:
        raise NotEvaluated(f"{run.name}: the checkout of {run.repo} has uncommitted changes (or is "
                           "gone); a result would carry false provenance")
    want = run.trace.get(f"code/{run.repo}", "")
    if not (code.commit and want and code.commit.startswith(want)):
        raise NotEvaluated(f"{run.name}: it ran at {run.repo} {want or '?'}; the checkout is at "
                           f"{(code.commit or '?')[:8]}")


def save_run(t: Any, value: Value, run: RunTrace, name: Optional[str],
             refuse_held: bool = False, plan: Optional[List[Any]] = None) -> str:
    """Write ``value`` as ``run``'s memo entry into the open transaction ``t``; its subject.

    The entry ``seal_entry`` always wrote: ``db/fn`` (the dotted name), ``db/keys``, ``db/returns``
    (the function's return annotation), ``db/reproducible`` (its claim, when it makes one), ``db/at`` (the
    revision the run read: provenance, outside the subject's hash and the hit test, SVP 245), the trace as
    ``db/deps/*`` (``code`` naming the ``db/code/<hash 16>`` item, written once), ``db/value``, under
    ``<hash of (fn, keys, trace, preds, value)>``, its subdats with it (``plan``, ``Transaction._subdat_plan``).
    ``refuse_held``: an identical entry already on the ledger raises ``_AlreadySealed`` (the caller loads it)."""

    if value.sealed and value.subject is None and "_run" not in value.__dict__:
        raise TypeError(f"{run.name} returned a {type(value).__name__} sealed by v.seal(); run seals its "
                        "own result, so return it unsealed")
    t._open("seal")
    value._sealable()
    check_loadable(value)
    plan = t._subdat_plan(value, None) if plan is None else plan
    if ledger_key(t._ledger) != run.ledger:
        raise ValueError(f"{run.name}: the result ran against {run.ledger}; its memo entry goes there, "
                         f"not to {ledger_key(t._ledger)}")
    pred_rows, canon = t._encode_preds(value)
    vtext = ref_text(dotted(type(value)), t._hash_of(value))
    subject = hash_text(canonical({"fn": run.name, "keys": json.loads(run.enc), "trace": run.trace,
                                   "preds": canon, "value": vtext}))
    if refuse_held and t._snapshot()._held(subject, "db/value") and not _spec_only(t._snapshot(), subject):
        raise _AlreadySealed(subject)           # a spec-only entry takes the bytes of this run (SVP 251)
    t._ensure_code(run.code_subject, run.code_rows)
    if run.clock is not None:
        t._advance_clock(*run.clock)
    extra = [("db/fn", "str:" + run.name), ("db/keys", "json:" + run.enc), ("db/returns", "str:" + run.returns)]
    if run.reproducible is not None:
        extra.append((REPRODUCIBLE, "json:" + run.reproducible))
    if run.at is not None:
        extra.append((AT, "str:" + str(run.at)))
    if value.sealed and value.subject is None:
        extra.append(("db/sealed-at", "str:" + str(value.sealed)))
    if name is None:
        name = value.__dict__.get("_name")
    value.__dict__["_run"] = run            # an abandoned transaction leaves a draft that can be saved again
    t._seal(value, subject, run.trace, run.provenance, pred_rows, extra, name)
    t._freeze(value, subject, run.trace)
    t._seal_subdats(plan, value, subject, name, run.provenance)
    return subject


#: The attribute ``@dat.fn`` leaves on a function: its ``FnMark``.
MARK = "__dat_fn__"


@dataclass(frozen=True)
class FnMark:
    """What ``@dat.fn`` declares of a function, held on the function object: ``reproducible``, its claim as
    written (``claim``, SVP 251 Q2). A run writes it as the ``db/reproducible`` row."""

    reproducible: Any = None


def fn(func: Optional[Callable] = None, *, reproducible: Any = None) -> Any:
    """``@dat.fn`` / ``@dat.fn(reproducible=...)``: mark a value function.

    It takes the ``Rev`` first and keywords after, and returns a ``Value``. ``func`` comes back unchanged and still
    callable (A52): a plain call runs the body with whatever ``Rev`` it is given, records nothing and seals nothing,
    which is how it is unit-tested; nothing is written on import.

    The return annotation is required (``TypeError`` at decoration): a ``Value`` subclass means the result must be
    one; any other annotation means a bare result is wrapped in ``Value.Blob`` (A31). A non-callable or a class is
    ``TypeError`` too.

    ``reproducible`` (``FnMark``, the grammar in ``claim``) is how far a rerun of it can be trusted
    ([Reproducibility][reproducibility]); a run writes it as the ``db/reproducible`` row: ``"exact"`` (bit-identical;
    every memo lookup of it also asks for the same card and driver, and a rerun that differs is an error), ``True``
    (good enough: a rerun that differs is allowed), ``None`` (default, unknown), ``False`` (flaky), a clause ``(level,
    predicate, ...)``, or a list of clauses, first match wins. ``TypeError`` for anything else.
    """
    if func is None:
        clauses(reproducible)
        return lambda f: fn(f, reproducible=reproducible)
    if not callable(func) or isinstance(func, type):
        raise TypeError(f"@dat.fn goes on a function, not {func!r}")
    clauses(reproducible)
    ann = getattr(func, "__annotations__", {})
    if "return" not in ann:
        raise TypeError(f"@dat.fn {getattr(func, '__qualname__', func)!r}: a return annotation is required "
                        "(-> a Value subclass, or any type to be wrapped in Value.Blob)")
    setattr(func, MARK, FnMark(reproducible))
    return func


def fn_mark(obj: Any) -> Optional[FnMark]:
    """The ``FnMark`` of a function marked ``@dat.fn``, else ``None`` (an undecorated function: a dat's run
    function)."""
    mark = getattr(obj, MARK, None)
    return mark if isinstance(mark, FnMark) else None


def _dat_names(tree: Any) -> Tuple[set, set]:
    """``(names bound to dvc_dat.dat, names bound to dvc_dat.dat.fn)`` by a module's top-level imports."""
    import ast

    dats, fns = {"dat"}, set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.module == "dvc_dat":
                dats.update(a.asname or a.name for a in node.names if a.name == "dat")
            elif node.module in ("dvc_dat.dat", "dvc_dat.ledger.fn"):
                fns.update(a.asname or a.name for a in node.names if a.name == "fn")
        elif isinstance(node, ast.Import):
            dats.update(a.asname for a in node.names if a.name == "dvc_dat.dat" and a.asname)
    return dats, fns


def fn_mark_in_source(tree: Any, fdef: Any) -> Optional[FnMark]:
    """The ``FnMark`` a function definition carries, read off its source (a mounted function is never imported
    in the caller): ``@dat.fn``, ``@dat.fn(reproducible=...)``, ``dat`` being any name the module binds to
    ``dvc_dat.dat`` (``from dvc_dat import dat``), or ``@dvc_dat.dat.fn``; ``None`` when unmarked."""
    import ast

    dats, fns = _dat_names(tree)

    def is_fn(node: Any) -> bool:
        if isinstance(node, ast.Name):
            return node.id in fns
        if isinstance(node, ast.Attribute) and node.attr == "fn":
            v = node.value
            return (isinstance(v, ast.Name) and v.id in dats) or (
                isinstance(v, ast.Attribute) and v.attr == "dat" and isinstance(v.value, ast.Name)
                and v.value.id == "dvc_dat")
        return False
    for d in fdef.decorator_list:
        if is_fn(d):
            return FnMark()
        if isinstance(d, ast.Call) and is_fn(d.func):
            claim = None
            for kw in d.keywords:
                if kw.arg == "reproducible":
                    try:
                        claim = ast.literal_eval(kw.value)
                    except ValueError:
                        raise TypeError(f"@dat.fn on {fdef.name}: a mounted function is read off its file, so "
                                        "reproducible= is a literal") from None
                    clauses(claim)
            return FnMark(claim)
    return None


def returns_text(func: Callable) -> str:
    """The return annotation's source text, for ``db/returns``."""
    ann = func.__annotations__["return"]
    if isinstance(ann, str):
        return ann
    if isinstance(ann, type):
        return ann.__qualname__
    return repr(ann).replace("typing.", "")


def returns_class(func: Callable) -> Optional[type]:
    """The ``Value`` subclass the annotation names, or ``None`` (wrap a bare result in ``Value.Blob``)."""
    ann = func.__annotations__["return"]
    if isinstance(ann, str):
        try:
            ann = eval(ann, func.__globals__)  # noqa: S307 - the function's own annotation
        except Exception:
            return None
    if isinstance(ann, type) and issubclass(ann, Value):
        return ann
    return None


def encode_keys(kw: Dict[str, Any]) -> Dict[str, Any]:
    """``db/keys``: a ``Value``/``Ref`` top-level key as ``ref:<class>:<hash>``, the rest native JSON (A17, A38)."""
    from .rev import Ref

    def nested(x: Any, k: str) -> Any:
        # what JSON would turn into another value is refused, never collapsed into another call's memo
        # key: a non-str dict key (1 as "1"), a NaN or an infinity; a tuple is its list, as documented
        if isinstance(x, (Value, Ref)):
            raise TypeError(f"key {k!r}: a Value or Ref is a key only at the top level, never nested (A44)")
        if isinstance(x, dict):
            bad = [a for a in x if not isinstance(a, str)]
            if bad:
                raise TypeError(f"key {k!r}: a dict key is a str, not {bad[0]!r}: JSON would make it {str(bad[0])!r}")
            return {a: nested(b, k) for a, b in x.items()}
        if isinstance(x, (list, tuple)):
            return [nested(b, k) for b in x]
        if isinstance(x, float) and not math.isfinite(x):
            raise TypeError(f"key {k!r}: {x!r} is not JSON")
        if x is None or isinstance(x, (str, int, float, bool)):
            return x
        raise TypeError(f"key {k!r}: {type(x).__name__} is not JSON-encodable")
    out: Dict[str, Any] = {}
    for k, v in kw.items():
        if isinstance(v, Ref):
            if v.hash is None:
                raise TypeError(f"key {k!r}: {v.name!r} holds no value")
            out[k] = v._text()
        elif isinstance(v, Value):
            if v.subject is None:
                raise ValueError(f"key {k!r}: an unsaved {type(v).__name__}; seal it first")
            out[k] = ref_text(dotted(type(v)), v.hash)
        else:
            out[k] = nested(v, k)
    return out


MNT = "mnt"
"""The reserved top segment of a ledger-mounted name (1467 Q14 (B)): ``mnt.<at>...`` names what the mount
``db/mount/<at>`` serves; a name not starting ``mnt.`` is never a mount and is imported. A mount is named with
it, ``t.ns.mount("mnt.<at>", ...)`` and a ``.datconfig.yaml`` ``mounts:`` key ``mnt.<at>`` alike (1505 Q1); the
rows, ``mounts()`` and the in-process module names never carry it."""


def mounted_name(dotted: str) -> str:
    """The ledger name of ``dotted`` under a mount: ``plane.measure.length`` -> ``mnt.plane.measure.length``."""
    return f"{MNT}.{dotted}"


def mount_prefix(at: str, where: str) -> str:
    """The prefix of the ``db/mount/<prefix>`` rows a mount named ``at`` writes: ``at`` is ``mnt.<prefix>``
    (1505 Q1), and anything outside ``mnt.`` (``mnt`` alone included) is ``ValueError``; nothing is prefixed for
    you."""
    rest = at[len(MNT) + 1:] if at.startswith(MNT + ".") else ""
    if not rest or not all(rest.split(".")):
        hint = mounted_name(at) if at and at != MNT and all(at.split(".")) else MNT + ".<prefix>"
        raise ValueError(f"{where}: a mount is named {MNT}.<prefix>, got {at!r} (write {hint!r}); a mount is "
                         f"outside {MNT}. never")
    return rest


def mounts_at(rev: "Rev") -> Dict[str, Dict[str, str]]:
    """``prefix -> {"root", "repo", "salt"}``: the ``db/mount/<prefix>`` rows as of ``rev``."""
    from .codec import show

    out: Dict[str, Dict[str, str]] = {}
    for s, p, h in rev._held_rows(prefix="db/mount/"):
        out.setdefault(s[len("db/mount/"):], {})[p[len("db/"):]] = show(h.obj)
    return {k: v for k, v in out.items() if "root" in v}


def mounts_hash(rev: "Rev") -> Optional[str]:
    m = mounts_at(rev)
    return hash_text(canonical(m), 16) if m else None


def resolve_in_process(name: str) -> Any:
    import importlib

    parts = name.split(".")
    errors = []
    for i in range(len(parts) - 1, 0, -1):
        modname = ".".join(parts[:i])
        try:
            obj: Any = importlib.import_module(modname)
        except ImportError as e:
            errors.append(str(e))
            continue
        try:
            for a in parts[i:]:
                obj = getattr(obj, a)
        except AttributeError:
            continue
        return obj
    raise ImportError(f"{name!r} does not resolve in this process ({'; '.join(errors[:1]) or 'no attribute'})")


def path_template(default: Any) -> Optional[str]:
    """A declared ``path`` parameter's default, the path template (Q36); ``None`` for no default."""
    if default is inspect.Parameter.empty or default is None:
        return None
    if not isinstance(default, (str, os.PathLike)):
        raise TypeError(f"a path parameter's default is a path template, a str, not {default!r}")
    return os.fspath(default)


def signature_of(name: str, obj: Callable) -> Tuple[inspect.Signature, bool, Optional[str]]:
    """The keys a function takes (the ``Rev`` and ``path`` excluded), whether it takes ``path`` (the
    folder it builds), and that parameter's default (the path template)."""
    sig = inspect.signature(obj)
    params = list(sig.parameters.values())
    if not params or params[0].kind not in (inspect.Parameter.POSITIONAL_ONLY,
                                            inspect.Parameter.POSITIONAL_OR_KEYWORD):
        raise TypeError(f"{name!r}: a revision function takes the Rev as its first parameter")
    rest = params[1:]
    folder = next((p for p in rest if p.name == "path"), None)
    keep = [p for p in rest if p.name != "path"]
    template = path_template(folder.default) if folder is not None else None
    return sig.replace(parameters=keep, return_annotation=inspect.Signature.empty), folder is not None, template


def installed_fn(rev: "Rev", name: str, obj: Any) -> "Fn":
    """The ``Fn`` of a function resolved in this process (no mount): ``kind`` ``"ledger"`` when it is a
    ``@dat.fn``, else ``"dat"`` (a dat's run function), its ``Code`` the static closure of its module."""
    if not callable(obj):
        raise TypeError(f"{name!r} is {obj!r}, not a function")
    modname, src = source_of(name, obj)
    env = current_env()
    code = installed_code(modname, src, env)
    mark = fn_mark(obj)
    if mark is None:
        return Fn(name=name, module=src, mount=None, signature=inspect.Signature(), env=env, code=code,
                  _rev=rev, _obj=obj, _takes_path=True, kind="dat")
    sig, takes_path, template = signature_of(name, obj)
    return Fn(name=name, module=src, mount=None, signature=sig, env=env, code=code,
              _rev=rev, _obj=obj, _takes_path=takes_path, _template=template, _returns=returns_text(obj),
              reproducible=mark.reproducible)


def source_of(name: str, obj: Any) -> Tuple[str, Path]:
    """The module name and source file of a function resolved in this process."""
    modname = getattr(obj, "__module__", None) or name.rpartition(".")[0]
    src = inspect.getsourcefile(obj)
    if not src or not os.path.exists(src):
        raise ImportError(f"{name!r}: no source file to hash")
    return modname, Path(src)


def _closure_files(modname: str, src: Path, env: Env) -> Tuple[Path, Path, List[Path]]:
    """The installed function's static import closure (Q37 (iii)): ``(root, within, files)``, ``root`` the
    ``sys.path`` entry its top-level package sits in, ``within`` its checkout (else ``root``)."""
    from .sandbox import static_closure

    parts = modname.split(".")
    root = src.parent if src.name != "__init__.py" else src.parent.parent
    for _ in parts[1:]:
        root = root.parent
    repo = repo_of(env, src)
    co = env.code.get(repo) if repo else None
    within = co.path if co is not None and co.path is not None else root
    return root, within, list(static_closure(root, modname, within).values())


def installed_code(modname: str, src: Path, env: Env) -> Code:
    """An installed function's ``Code`` (DAT 1037): its top-level package at the version its environment
    carries; ``modules`` the static import closure within its checkout (Q37 (iii)), relative to the
    top-level package's parent, each by its sha256 (outside any checkout, the module file alone); never
    sandboxed, no mounts."""
    from .code import declared_version, identity_hash, installed_version, lock_of
    from .sandbox import unguarded

    with unguarded():                       # the ledger's own reads, also inside a sandboxed body
        root, _within, files = _closure_files(modname, src, env)
        real = os.path.realpath(root)
        modules = {os.path.relpath(os.path.realpath(f), real).replace(os.sep, "/"): sha256(f.read_bytes())
                   for f in files} \
            or {os.path.relpath(os.path.realpath(src), real).replace(os.sep, "/"): sha256(src.read_bytes())}
        repo = repo_of(env, src)
        co = env.code.get(repo) if repo else None
        top = modname.split(".")[0]
        version = installed_version(top, env, repo, identity_hash(modules, None))
        declared = version == declared_version(top)
        lock = lock_of(co.path) if co is not None else None
    return Code({"modules": modules, "mounts_hash": None, "mounts": {},
                 "commit": co.commit if co is not None else None,
                 "lock": lock, "sandboxed": False, "version": version,
                 "package": top if declared else None}, unit=top)


@dataclass(frozen=True)
class Fn:
    """A revision function, resolved at ``_rev``; calling it is ``run``. Not on the timeline: no subject.
    ``name`` is the dotted string it was loaded by; ``code`` the snapshot it is looked up in, which alone
    has identity (``code.subject``, DAT 1037). ``kind`` is read off the function: ``"ledger"`` for a
    ``@dat.fn``, ``"dat"`` for an undecorated one, a dat's run function, which runs only through a
    spec (``rev.run(spec)``; its keys are the expanded spec, DAT 1046). ``reproducible`` is the function's
    own claim as written (``@dat.fn(reproducible=...)``, SVP 251 Q2)."""

    name: str
    """The dotted name it was resolved by."""
    module: Path
    """The function's source file."""
    mount: Optional[str]
    """The mounted prefix the name resolved under; ``None`` for installed code."""
    signature: inspect.Signature
    """The keys the function takes, without the leading ``Rev`` and without ``path``."""
    env: Env
    """The environment the function resolved in: repos and commits, platform."""
    code: Code
    """The code it is loaded from, at a version: the snapshot, which alone has identity.

    A ``Code(Value)`` (DAT 1037), computed at ``rev.ns.load``; a run writes its identity as the ``db/code/<16 hex>``
    item, and the rest of it is not written to the ledger. Its name is ``<unit>@<version>``: the unit is the mount
    prefix for mounted code (``plane``, ``algs.ocr``) and the function's top-level package for installed code
    (``geometry``).

    Its identity is the bytes: ``encode()`` is the canonical ``{"modules": relpath -> sha256, "mounts": <hash of the
    db/mount rows, or null>}``, ``hash`` its sha256, and ``subject`` ``db/code/<16 hex>``, the first 16 of the hash
    (the 16 hex the memo key carried as ``db/fn/<name>/<16 hex>`` before); two functions in one snapshot share it, and
    any changed byte in a module makes a new one.

    Read-only properties describe it, fixed at load and not hashed: ``sandboxed`` (True for mounted code), ``version``
    (the name after ``@``), ``modules`` (the relpaths the loader walked: under the repo root when mounted, under the
    top-level package's parent when installed), ``mounts`` (``prefix -> {repo, root}``, empty when installed),
    ``commit`` (the checkout's at load, or ``None``), ``lock`` (the git blob id of that checkout's ``uv.lock``, or
    ``None``) and ``package`` (the dotted root whose declared version ``version`` is, the unit, or ``None`` when the
    version came from a commit or the hash: the ``<package>`` of the ``db/repo/<repo>/<package>`` clock a clean run
    moves, DAT 1044).

    The version is read as a module attribute after import, never parsed from source, and a declared version counts
    only from a clean checkout (DAT 1043): when the checkout holding the code has modified tracked files, the version
    is ``<commit 8>+dirty`` whatever ``__version__`` says (mounted: the last commit touching the loaded files, else
    HEAD; installed: HEAD).

    Clean, mounted: the root package's ``__version__`` (imported in the worker); else the last commit touching the
    loaded files, 8 hex, ``+dirty`` when one differs from HEAD; else ``#`` + the first 8 hex of ``hash``. Clean or
    outside any checkout (a wheel), installed: ``__version__`` on the top-level package; else the version of the
    distribution providing it; else the short commit (8 hex) of the checkout holding it; else ``#`` + 8 hex of
    ``hash``.

    The version is a name for people over the hash, and the commit is a result's ``code/<repo>`` dependency item, so
    neither moves ``subject``, the identity and the memo key.
    """
    _rev: Any = field(repr=False, compare=False)
    _obj: Any = field(repr=False, compare=False, default=None)
    _takes_path: bool = field(repr=False, compare=False, default=False)
    _template: Optional[str] = field(repr=False, compare=False, default=None)
    _returns: str = field(repr=False, compare=False, default="")
    _info: Dict[str, Any] = field(repr=False, compare=False, default_factory=dict)
    kind: str = "ledger"
    """``"ledger"`` or ``"dat"``, read off the function.

    ``"ledger"`` for a ``@dat.fn``: its keys are its memo key and it receives them. ``"dat"`` for an undecorated
    function, a dat's run function (DAT 1046): its memo key is the expanded spec, and it receives the dat made from
    that spec in its work folder; it runs only through a spec (``rev.run(spec)``, ``rev.run(name, **kwargs)``), and a
    direct call is ``TypeError``. A plain ``Dat.manager.run`` in a ledger project runs a mounted one in the calling
    process, nothing memoised.
    """
    reproducible: Any = None
    """The claim ``@dat.fn(reproducible=...)`` made about the function, as written.

    Read off the function object (installed) or its source, a literal (mounted). A run writes it as the
    ``db/reproducible`` row, which is what ``rerun`` and ``safe`` read ([Reproducibility][reproducibility]).
    """

    def __repr__(self) -> str:
        """``<Fn plane.measure.length@2.7.1>``: the name, ``@`` its code's version (DAT 1036, 1037)."""
        return f"<Fn {self}>"

    def __str__(self) -> str:
        """``plane.measure.length@2.7.1``: the dotted name, ``@`` its code's version (``fn.code.version``)."""
        return f"{self.name}@{self.code.version}"

    def _bind(self, keys: Dict[str, Any]) -> Dict[str, Any]:
        if self.kind == "dat":
            dat = keys.get("dat")
            if not isinstance(dat, dict) or dat.get("do") != self.name:
                raise TypeError(f"{self.name} is a dat's run function: it runs through a spec, "
                                f"rev.run({self.name!r}, **kwargs) or rev.run(spec)")
            return dict(keys)
        if self._takes_path and "path" in keys:
            raise TypeError(f"{self.name}: 'path' is the folder it builds, a control option (path=), never a key")
        bound = self.signature.bind(**keys)
        bound.apply_defaults()
        out: Dict[str, Any] = {}
        for k, v in bound.arguments.items():
            if self.signature.parameters[k].kind is inspect.Parameter.VAR_KEYWORD:
                out.update(v)
            else:
                out[k] = v
        return out

    def __call__(self, *, seal: Any = OWN, clean: bool = False, path: Any = None,
                 kwargs: Optional[Dict[str, Any]] = None, **keys: Any) -> Optional[Value]:
        """``f(k=v, ...)`` or ``f(kwargs={...})``: eval.

        The control options are exactly ``seal``, ``clean``, ``path`` and ``kwargs``, never keys and never hashed
        (Q41).

        ``seal``: where the result goes (DAT 1028, [Running][running]). ``"get"``: the saved result if one holds, else
        ``None``; never runs. ``False``: run, keep nothing; the trace is on the result. ``True``: run, seal it locally
        (``v.seal()``), off the ledger. A ``Ledger`` (default: the one the fn was loaded from): the saved result if
        one holds, else run and save it as the memo entry in a transaction of its own, the value's subject fixed at
        once and its revision at commit. An open ``Transaction`` on that ledger: the same, saved into it. Another
        ledger, or anything else, is ``ValueError``. A later ``v.seal(L)`` or ``v.seal(t)`` of a ``False``/``True``
        result writes the same memo entry. With ``seal=t``, ``path=`` must be relative: it is the name the entry is
        saved under.

        ``clean=True``: the code must be a clean representation of a version, the checkout clean and at the commit the
        rev's ``db/repo/<repo> db/commit`` row names, else ``NotClean`` (Q39), before any lookup; ``False`` (default):
        a sandboxed call runs at HEAD, clean or dirty. An unsandboxed call needs the function's code in a clean git
        checkout regardless, else ``NotEvaluated``.

        ``path``: the result's name, relative to the data folder (``<art store>/dats``), its folder there a view when
        it is a ``Dat``; an absolute path makes the folder there and names nothing (Q36). A hit asked for under a new
        name takes that name. Keys bind to the signature with defaults applied; ``kwargs={...}`` passes the whole key
        set instead, for a key that is also a control option's name; inline keys beside it are ``TypeError``.

        A function claiming ``exact`` in any clause (``@dat.fn(reproducible="exact")``, SVP 251 Q2): the lookup also
        asks that the entry ran on the same ``card`` and ``driver``
        ([``reproducible``][dvc_dat.ledger.Fn.reproducible]), on top of the ledger's memo policy ([Memoization and the
        platform][memoization-and-the-platform], SVP 1474); the entry written is the same either way.

        A result that is not an instance of a ``Value``-subclass return annotation is ``TypeError``.
        """
        from .txn import Transaction

        rev = self._rev
        plain = rev._plain()
        read_only = plain.ledger.read_only          # read by name in a sandboxed body: a lookup, never a run
        if not self.code.sandboxed and not read_only:
            from . import sandbox

            if sandbox.IN_WORKER and sandbox.STATE.frames:
                raise NotEvaluated(f"{self.name} is unsandboxed (under no mount): it does not run nested inside "
                                   f"the sandboxed body of mount {sandbox.STATE.frames[-1].mount!r}; mount it")
        level = seal_level(self.name, plain, seal, clean, path)
        if read_only and (level is True or level is False or path is not None):
            raise ConfinedWrite(f"{self.name}: {plain.ledger._store.name} is read-only here: seal='get' or the "
                                "default reads an entry; seal=True, seal=False and path= do not apply")
        if kwargs is not None:
            if keys:
                raise TypeError(f"{self.name}: the keys go inline or in kwargs=, never both "
                                f"(inline: {', '.join(sorted(keys))})")
            if not isinstance(kwargs, dict) or not all(isinstance(k, str) for k in kwargs):
                raise TypeError(f"kwargs is a dict of str keys, not {kwargs!r}")
            keys = dict(kwargs)
        if clean:
            check_clean(self, plain, current_env())
        kw = self._bind(keys)
        enc = canonical(encode_keys(kw))
        item = f"eval:{self.name}{enc}"
        target = None if path is None else os.fspath(path)
        if level not in (True, False):
            hit = lookup(plain, self.name, enc, widen=EXACT_FIELDS if widens(self.reproducible) else ())
            if hit is not None or level == "get":
                rev._record_run(item, ref_text(dotted(type(hit)), hit.hash) if hit is not None else "<none>")
                at = target if target is not None or hit is None or self.kind != "dat" else hit.name
                if read_only:
                    return hit
                return place(plain.ledger, hit, at) if hit is not None and at is not None else hit
            if read_only:
                raise ConfinedWrite(f"{self.name}: no entry for these keys at {plain.ledger._store.name}@{plain.id}, "
                                    "a read-only ledger here; it runs nothing (seal='get' asks without refusing)")
        into = level if isinstance(level, Transaction) else None
        # False: a draft; True: the memo entry in a transaction of its own; a Transaction: into it
        save: Any = True if isinstance(level, str) and level == "save" else (into if into is not None else False)
        if into is not None and target is None and self._takes_path:
            target = fresh_name(into.ns, self._template or ANONYMOUS, kw)
        name = target if into is not None and target is not None and not os.path.isabs(target) else None
        if into is not None and target is not None and name is None:
            raise ValueError(f"{self.name}: path={target!r} is absolute; with seal=t the result is saved at "
                             "commit, so it takes a name (a relative path) or none")
        if self.code.sandboxed:
            from .sandbox import run_sandboxed

            value = run_sandboxed(self, plain, kw, enc, save, name)
        else:
            value = self._run_base(plain, kw, enc, save, name)
        if level is True:
            if value.sealed:
                raise TypeError(f"{self.name} returned a {type(value).__name__} sealed by v.seal(); run seals "
                                "its own result, so return it unsealed")
            value.seal()
        rev._record_run(item, ref_text(dotted(type(value)), value.hash))
        if into is not None:
            return value
        if target is None and self._takes_path and hooks.is_dat(value):
            target = fresh_name(plain.ns, self._template or ANONYMOUS, kw)
        return place(plain.ledger, value, target) if target is not None else value

    def _function(self) -> Callable:
        """The function itself, for a plain ``Dat.ns`` run (nothing memoised): installed, the object;
        mounted, imported in this process through the mounts as of ``_rev`` (``sandbox.import_mounted``)."""
        if self._obj is not None:
            return self._obj
        from .sandbox import import_mounted

        return import_mounted(self)

    def _check_code(self, plain: "Rev", env: Env, repo: Optional[str]) -> str:
        """The base-mode gate, always (no byte record of what ran): code in a clean checkout."""
        if repo is None:
            raise NotEvaluated(f"{self.name}: its code ({self.module}) is outside any git checkout, so no "
                               "commit can vouch for a result")
        code = env.code[repo]
        if code.dirty:
            raise NotEvaluated(f"{self.name}: the checkout of {repo} has uncommitted changes; a result would "
                               "carry false provenance")
        return repo         # a db/repo/<repo> db/commit row names a clean run, not where evals may run

    def _run_base(self, plain: "Rev", kw: Dict[str, Any], enc: str, save: Any,
                  name: Optional[str] = None) -> Value:
        """Run in this process. ``save``: ``False``, a draft carrying its ``RunTrace``; ``True``, the
        memo entry in a transaction of its own; a ``Transaction``, the memo entry in it (named ``name``)."""
        from .sandbox import base_confined
        from .trace import RunFrame, running
        from .txn import code_token

        env = current_env()
        repo = repo_of(env, self.module)
        if save is not False:                       # a draft simply runs (Eval § 2)
            self._check_code(plain, env, repo)
        if self.kind == "dat":
            return self._run_dat(plain, kw, enc, save, name, env, repo)
        rec: Dict[str, str] = {}
        frame = RunFrame(plain, rec, enc)
        work = work_folder() if self._takes_path else None
        args = dict(kw, path=work) if work is not None else kw
        value = None
        try:
            with base_confined(_checkout(env, repo), _dats(plain, work)), running(frame):
                out = self._obj(frame.rev, **args)
            value = wrap_result(self.name, self._obj, out)
            trace = dict(rec)
            trace.update({"code": self.code.subject, "fn": self.name, **platform_items(env)})
            if repo is not None:
                trace[f"code/{repo}"] = code_token(env.code[repo].commit)
            if save is False:
                dirty = bool(repo is not None and env.code[repo].dirty)
                return attach_run(value, run_trace(self, plain, trace, enc, "eval:unsandboxed", self.code,
                                                   repo=repo, dirty=dirty))
            value = seal_entry(self, plain, value, trace, enc, "eval:unsandboxed", self.code, into=save,
                               name=name, repo=repo)
            return value
        finally:
            drop_work(work, value)

    def _run_dat(self, plain: "Rev", spec: Dict[str, Any], enc: str, save: Any, name: Optional[str],
                 env: Env, repo: Optional[str]) -> Value:
        """A dat's run function, run here (``_run_base``): the dat made from the spec in a work folder and
        run (``manager._execute``), its recorded dependencies that are ledger names entered as alias reads.
        The run is the current run, so the manager's namespace and ``dat.at`` are at ``plain`` (SVP 1521)."""
        from .sandbox import base_confined
        from .trace import RunFrame, running
        from .txn import code_token

        rec: Dict[str, str] = {}
        work = work_folder()
        value: Any = None
        manager = hooks.manager()
        try:
            with base_confined(_checkout(env, repo), _dats(plain, work)), running(RunFrame(plain, rec, enc)):
                dat = manager.create(dat_spec(spec, self._template), path=str(work / "dat"))
                manager._execute(dat)
            value = dat
            alias_reads(plain, dat, rec)
            trace = dict(rec)
            trace.update({"code": self.code.subject, "fn": self.name, **platform_items(env)})
            if repo is not None:
                trace[f"code/{repo}"] = code_token(env.code[repo].commit if repo in env.code else None)
            if save is False:
                dirty = bool(repo is not None and repo in env.code and env.code[repo].dirty)
                value = attach_run(dat, run_trace(self, plain, trace, enc, "eval:unsandboxed", self.code,
                                                  repo=repo, dirty=dirty))
            else:
                value = seal_entry(self, plain, dat, trace, enc, "eval:unsandboxed", self.code, into=save,
                                   name=name, repo=repo)
        finally:
            drop_work(work, value)
            if not work.exists():                       # its folder is gone: so is the dat world's index of it
                manager._index_forget(str(work / "dat"))
        return value


def _checkout(env: Env, repo: Optional[str]) -> Optional[Path]:
    """The checkout an unsandboxed body's repo is, for its open hook (``None``: none, nothing checked)."""
    co = env.code.get(repo) if repo else None
    return co.path if co is not None else None


def _dats(plain: "Rev", work: Optional[Path]) -> List[Any]:
    """Where an unsandboxed body may read inside its repo (Eval § 5.3): the dats (the dat world's folders
    and art folder, the ledger's art store), the ledger's own folder, and the body's path folder."""
    from .pgstore import is_dsn

    manager = hooks.manager()
    out: List[Any] = [*manager._dat_folders, manager._art_folder, plain.ledger._store.art.root, work]
    if not is_dsn(str(plain.ledger.path)):
        out.append(plain.ledger.path)
    return out


def dat_spec(keys: Dict[str, Any], template: Optional[str]) -> Dict[str, Any]:
    """The spec a dat is created from: its memo key (the expanded spec) quoted, so ``create``'s expansion hands
    its values back as they are, with its ``dat.preds`` template (SVP 1508) and its ``dat.name`` template
    back, which that expansion fills."""
    from ..expand import quote_spec

    spec = quote_spec(keys)
    preds = keys["dat"].get("preds")
    if preds is not None:
        spec["dat"]["preds"] = preds
    if template is not None:
        spec["dat"]["name"] = template
    return spec


def alias_reads(plain: "Rev", dat: Any, rec: Dict[str, str]) -> None:
    """The dat's recorded dependencies that are names on the ledger, recorded as the bindings they read."""
    from .rev import Ref, Rev

    recording = Rev(plain.ledger, plain.id, _rec=rec)
    for dep in sorted(dotted_get(dat.get_results(), "dat.dependencies", None) or {}):
        if plain._held(dep, "db/alias"):
            Ref(recording, dep)                     # records `<dep> db/alias`, the binding it read


def seal_level(name: str, plain: "Rev", seal: Any, clean: Any, path: Any) -> Any:
    """``seal=`` of a run as a level: ``"save"`` (the fn's ledger), ``True``, ``False``, ``"get"``, or the
    open ``Transaction``; ``clean`` and ``path`` checked for type on the way."""
    from .ledger import Ledger
    from .txn import Transaction

    if seal is OWN:
        level: Any = "save"
    elif seal is True or seal is False:
        level = seal
    elif isinstance(seal, str) and seal == "get":
        level = "get"
    elif isinstance(seal, Ledger):
        if ledger_key(seal) != ledger_key(plain.ledger):
            raise ValueError(f"{name}: seal= names a ledger other than the one it was loaded from "
                             f"({plain.ledger.path}); its memo entries live there")
        level = "save"
    elif isinstance(seal, Transaction):
        seal._open("seal")
        if ledger_key(seal._ledger) != ledger_key(plain.ledger):
            raise ValueError(f"{name}: seal= is a transaction on another ledger than the one it was "
                             f"loaded from ({plain.ledger.path})")
        level = seal
    else:
        raise ValueError(f"seal is 'get', False, True, a Ledger or an open Transaction, not {seal!r}")
    if not isinstance(clean, bool):
        raise TypeError(f"clean is True or False, not {clean!r}")
    if path is not None and not isinstance(path, (str, os.PathLike)):
        raise TypeError(f"path is a str or a path, not {type(path).__name__}")
    return level


def check_clean(fn: Fn, plain: "Rev", env: Env) -> None:
    """``clean=True`` (Q39): the checkout clean and at the commit ``plain``'s ``db/repo/<repo> db/commit`` row names."""
    repo = fn._info.get("repo") if fn.code.sandboxed else repo_of(env, fn.module)
    code = env.code.get(repo) if repo else None
    if code is None:
        raise NotClean(f"{fn.name}: clean=True, and its code ({fn.module}) is in no git checkout here")
    if code.dirty:
        raise NotClean(f"{fn.name}: clean=True, and the checkout of {repo} has uncommitted changes")
    c = plain.get(f"db/repo/{repo}", "db/commit")
    if c is None:
        raise NotClean(f"{fn.name}: clean=True, and rev {plain.id} names no db/repo/{repo} db/commit "
                       "(the first clean run of code with a __version__ writes it)")
    if not (code.commit and (code.commit.startswith(c) or c.startswith(code.commit))):
        raise NotClean(f"{fn.name}: clean=True, and rev {plain.id} binds db/repo/{repo} to {c[:8]}; "
                       f"the checkout is at {(code.commit or '?')[:8]}")


def fresh_name(ns: Any, template: str, keys: Dict[str, Any]) -> str:
    """The path template expanded with the call's keys through the ledger namespace ``ns`` (Q36):
    ``ns.expand`` counts ``${unique:}`` until no name holds a value there and no folder is at it; without
    ``${unique:}`` the name moves to the new value (A70)."""
    text = ns.expand(template, **keys)
    if not text:
        raise TypeError(f"path template {template!r} expanded to {text!r}, not a path")
    return text


def place(ledger: Any, value: Value, target: str) -> Value:
    """``path=`` on a result (Q36, A70): relative, the value's name, its folder (a ``Dat``) rebuilt at
    ``<data folder>/<name>`` as a view; absolute, the folder made there, no name. Unsaved
    (``seal=False`` or ``True``): the name is set on the object, saved with it."""
    if os.path.isabs(target):
        if hooks.is_dat(value) and value.subject is not None:
            art = ledger._store.art
            value._forget()
            value.path = value._materialise(value.hash, value._stored_manifest(art, value.hash), art, target)
        elif hooks.is_dat(value):
            raise ValueError(f"path={target!r}: an unsaved Dat stays where it was built (seal=False or True)")
        return value
    if value.subject is None:
        value.name = target
        return value
    value._rename(ledger, target)
    return value


def work_root() -> Path:
    """Where an eval's ``path`` folders are made: ``$DAT_WORK``, else ``~/.cache/dvc-dat/work``."""
    env = os.environ.get("DAT_WORK")
    return Path(env) if env else Path.home() / ".cache" / "dvc-dat" / "work"


def work_folder() -> Path:
    """A fresh ``ledger-work-*`` folder under ``work_root()``."""
    root = work_root()
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="ledger-work-", dir=root))


def drop_work(work: Optional[Path], value: Any) -> None:
    """Remove an eval's folder once the call is done, sealed or not; a ``Dat`` not yet on the ledger
    that still lives in it (a draft, or one saved into a transaction still open) keeps it, since the
    folder is that value."""

    if work is None or not work.exists():
        return
    if hooks.is_dat(value) and value.rev is None:        # unsaved, or saved by a transaction still open
        p = os.path.realpath(value.path)
        if p == os.path.realpath(work) or p.startswith(os.path.realpath(work) + os.sep):
            return
    shutil.rmtree(work, ignore_errors=True)


def wrap_result(name: str, func: Callable, out: Any) -> Value:
    cls = returns_class(func)
    if cls is not None:
        if not isinstance(out, cls):
            raise TypeError(f"{name}: annotated -> {cls.__name__}, returned {type(out).__name__}")
        return out
    return out if isinstance(out, Value) else Blob(out)


class _AlreadySealed(Exception):
    def __init__(self, subject: str) -> None:
        self.subject = subject


def seal_entry(fn: Fn, plain: "Rev", value: Value, trace: Dict[str, str], enc: str, provenance: str,
               code: Code, into: Any = True, name: Optional[str] = None,
               repo: Optional[str] = None) -> Value:
    """Seal an eval's result as a memo entry: into the open transaction ``into``, or (``True``) in a
    transaction of its own, handing back the identical entry when one is sealed already."""
    from .rev import Ref

    if value.sealed and value.subject is None:
        raise TypeError(f"{fn.name} returned a {type(value).__name__} sealed by v.seal(); run seals its own "
                        "result, so return it unsealed")
    run = run_trace(fn, plain, trace, enc, provenance, code, repo=repo)
    if into is not True:
        save_run(into, value, run, name)
        return value
    ledger = plain.ledger
    try:
        with ledger.transaction(by=f"eval:{fn.name}") as t:
            save_run(t, value, run, None, refuse_held=True)
    except _AlreadySealed as e:
        return Ref(ledger.at(), e.subject)._load()
    return value


def _spec_only(rev: "Rev", subject: str) -> bool:
    from .rev import Ref

    return Ref(rev, subject)._spec_only()


def lookup(plain: "Rev", name: str, enc: str, widen: Sequence[str] = ()) -> Optional[Value]:
    """The latest-sealed entry for ``(name, keys)`` whose dependencies hold at ``plain``; never runs.
    The memo index (``policy.reduced``) skips a candidate whose platform the policy already rules out;
    every other candidate is judged in full (``trace_matches``, ``widen`` added to the policy). A spec-only copy
    (SVP 251) holds no bytes to hand back: it is no hit."""
    from .policy import judge, policy_at, reduced
    from .rev import Ref
    from .trace import trace_matches

    top = plain.ledger.at()
    pname, pfn = policy_at(top)
    keys = reduced(top, pname, pfn)
    want = judge(pfn, current_env().platform_record())
    cands = []
    for s in top._store.subjects(top.id, predicate="db/keys", obj="json:" + enc):
        fnh = top._held(s, "db/fn")
        val = top._held(s, "db/value")
        if fnh and fnh[0].obj == "str:" + name and val:
            cands.append((val[0].rev, val[0].ord, s))
    for _r, _o, s in sorted(cands, reverse=True):
        if s in keys and (keys[s] is None or keys[s] != want):
            continue                                # the policy rules its platform out: no row read
        if _spec_only(top, s):
            continue
        trace = {p[len("db/deps/"):]: h.obj.partition(":")[2]
                 for _s, p, h in top._held_rows(subject=s) if p.startswith("db/deps/")}
        if trace_matches(plain, trace, widen):
            return Ref(top, s)._load()
    return None


def lookup_encoded(rev: "Rev", name: str, enc: str) -> Optional[Value]:
    return lookup(rev._plain(), name, enc)


def code_holds(rev: "Rev", subject: str, name: Optional[str]) -> bool:
    """Does the ``code`` item still name the code function ``name`` resolves to at ``rev`` (memo only,
    nothing runs): mounted, the recorded modules re-hashed as they are now; installed, the static
    closure as loaded now."""
    from .codec import show

    if not name:
        return False
    top = rev.ledger.at()
    mounts = top._held(subject, "db/mounts")
    mods = top._held(subject, "db/modules")
    if not mounts or not mods:
        return False
    if show(mounts[0].obj) != "none":           # a mounts hash: sandboxed
        from .sandbox import sandbox_code_at

        if not name.startswith(MNT + "."):
            return False
        return sandbox_code_at(rev, name[len(MNT) + 1:], json.loads(show(mods[0].obj))) == subject
    try:
        modname, src = source_of(name, resolve_in_process(name))
        return installed_code(modname, src, current_env()).subject == subject
    except (ImportError, TypeError):
        return False
