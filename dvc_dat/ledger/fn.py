"""``ledger_fn``, ``Fn`` and ``run`` (``Fn.__call__``): a revision function resolved at a ``Rev``.

``@ledger_fn`` declares and returns the function unchanged (A52): a plain call
runs the body and returns an unsealed ``Value``, recording nothing.
``rev.load_fn(name)`` resolves a dotted name at a revision: under a mounted
prefix (``db/mount/<prefix>`` rows) it is a sandboxed function, loaded from the
mounted tree and run in a worker (``sandbox``); otherwise a base function,
resolved in this process. Calling the ``Fn`` is ``run``: a memo lookup over
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
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from .codec import canonical, hash_text, ref_text, sha256
from .env import Env, current_env, repo_of
from .errors import NotClean, NotEvaluated
from .code import Code
from .value import Blob, Value, dotted
from ..core import Dat

if TYPE_CHECKING:
    from .rev import Rev

#: The control options of a call (Q41): never keys, never hashed. A function may declare one as a
#: key and is then called through ``kwargs=``; a declared ``path`` is the folder it builds (Q36).
RESERVED_KEYS = ("seal", "clean", "path", "kwargs")
#: The name a folder-producing miss gets with neither ``path=`` nor a template (as ``Dat.create``).
ANONYMOUS = "anonymous/Dat{unique}"


class _Own:
    """``seal=``'s default: the ledger the function was loaded from."""

    def __repr__(self) -> str:
        return "<the fn's ledger>"


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
    ``db/repo/<repo>/<package>`` version and ``db/repo/<repo>`` commit a seal advances (DAT 1043, 1044);
    ``None`` outside any checkout or when the code declares no version."""

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
                    repo=repo, dirty=dirty, returns=fn._returns, clock=clock_of(fn, code))


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
             refuse_held: bool = False) -> str:
    """Write ``value`` as ``run``'s memo entry into the open transaction ``t``; its subject.

    The entry ``seal_entry`` always wrote: ``db/fn`` (the dotted name), ``db/keys``, ``db/returns``
    (the function's return annotation), the trace as
    ``db/deps/*`` (``code`` naming the ``db/code/<hash 16>`` item, written once), ``db/value``, under
    ``<hash of (fn, keys, trace, preds, value)>``. ``refuse_held``: an
    identical entry already on the ledger raises ``_AlreadySealed`` (the caller loads it)."""

    if value.sealed and value.subject is None and "_run" not in value.__dict__:
        raise TypeError(f"{run.name} returned a {type(value).__name__} sealed by v.seal(); run seals its "
                        "own result, so return it unsealed")
    t._open("seal")
    value._sealable()
    if ledger_key(t._ledger) != run.ledger:
        raise ValueError(f"{run.name}: the result ran against {run.ledger}; its memo entry goes there, "
                         f"not to {ledger_key(t._ledger)}")
    pred_rows, canon = t._encode_preds(value)
    vtext = ref_text(dotted(type(value)), value.hash)
    subject = hash_text(canonical({"fn": run.name, "keys": json.loads(run.enc), "trace": run.trace,
                                   "preds": canon, "value": vtext}))
    if refuse_held and t._snapshot()._held(subject, "db/value"):
        raise _AlreadySealed(subject)
    t._ensure_code(run.code_subject, run.code_rows)
    if run.clock is not None:
        t._advance_clock(*run.clock)
    extra = [("db/fn", "str:" + run.name), ("db/keys", "json:" + run.enc), ("db/returns", "str:" + run.returns)]
    if value.sealed and value.subject is None:
        extra.append(("db/sealed-at", "str:" + str(value.sealed)))
    if name is None:
        name = value.__dict__.get("_name")
    value.__dict__["_run"] = run            # an abandoned transaction leaves a draft that can be saved again
    t._seal(value, subject, run.trace, run.provenance, pred_rows, extra, name)
    t._freeze(value, subject, run.trace)
    return subject


def ledger_fn(func: Callable) -> Callable:
    """Mark a value function: it takes the ``Rev`` first and keywords after, and returns a ``Value``.

    The return annotation is required (``TypeError`` at decoration): a ``Value`` subclass means the
    result must be one; any other annotation means a bare result is wrapped in ``Value.Blob`` (A31).
    The function comes back unchanged and still callable (A52); nothing is written on import.
    """
    if not callable(func):
        raise TypeError(f"@ledger_fn goes on a function, not {func!r}")
    ann = getattr(func, "__annotations__", {})
    if "return" not in ann:
        raise TypeError(f"@ledger_fn {getattr(func, '__qualname__', func)!r}: a return annotation is required "
                        "(-> a Value subclass, or any type to be wrapped in Value.Blob)")
    func.__ledger_fn__ = True  # type: ignore[attr-defined]
    return func


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
        if isinstance(x, (Value, Ref)):
            raise TypeError(f"key {k!r}: a Value or Ref is a key only at the top level, never nested (A44)")
        if isinstance(x, dict):
            return {str(a): nested(b, k) for a, b in x.items()}
        if isinstance(x, (list, tuple)):
            return [nested(b, k) for b in x]
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


def load_fn(rev: "Rev", name: str) -> "Fn":
    if not isinstance(name, str) or "." not in name:
        raise TypeError(f"a revision function is named by a dotted str, not {name!r}")
    plain = rev._plain()
    for prefix, info in sorted(mounts_at(plain).items(), key=lambda kv: -len(kv[0])):
        if name.startswith(prefix + "."):
            from .sandbox import load_sandboxed

            return load_sandboxed(rev, name, prefix, info)
    obj = resolve_in_process(name)
    if not callable(obj) or not getattr(obj, "__ledger_fn__", False):
        raise TypeError(f"{name!r} is not a ledger function (mark it @ledger_fn)")
    modname, src = source_of(name, obj)
    sig, takes_path, template = signature_of(name, obj)
    env = current_env()
    return Fn(name=name, module=src, mount=None, signature=sig, env=env,
              code=installed_code(modname, src, env),
              _rev=rev, _obj=obj, _takes_path=takes_path, _template=template, _returns=returns_text(obj))


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
    has identity (``code.subject``, DAT 1037)."""

    name: str
    module: Path
    mount: Optional[str]
    signature: inspect.Signature
    env: Env
    code: Code
    _rev: Any = field(repr=False, compare=False)
    _obj: Any = field(repr=False, compare=False, default=None)
    _takes_path: bool = field(repr=False, compare=False, default=False)
    _template: Optional[str] = field(repr=False, compare=False, default=None)
    _returns: str = field(repr=False, compare=False, default="")
    _info: Dict[str, Any] = field(repr=False, compare=False, default_factory=dict)

    def __repr__(self) -> str:
        """``<Fn plane.measure.length@2.7.1>``: the name, ``@`` its code's version (DAT 1036, 1037)."""
        return f"<Fn {self}>"

    def __str__(self) -> str:
        """``plane.measure.length@2.7.1``: the dotted name, ``@`` its code's version (``fn.code.version``)."""
        return f"{self.name}@{self.code.version}"

    def _bind(self, keys: Dict[str, Any]) -> Dict[str, Any]:
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
        """``f(k=v, ...)`` or ``f(kwargs={...})``: eval. The control options (Q41), never keys:

        ``seal``: where the result goes (DAT 1028). ``"get"``: the saved result if one holds, else
        ``None``; never runs. ``False``: run, keep nothing; the trace is on the result. ``True``: run,
        seal it locally (``v.seal()``), off the ledger. A ``Ledger`` (default: the one the fn was loaded
        from): the saved result if one holds, else run and save it as the memo entry in a transaction of
        its own. An open ``Transaction`` on that ledger: the same, saved into it. A later ``v.seal(L)``
        or ``v.seal(t)`` of a ``False``/``True`` result writes the same memo entry.
        ``clean=True``: the code must be a clean representation of a version,
        the checkout clean and at the commit the rev's ``db/repo/<repo>`` row names, else ``NotClean``
        (Q39), before any lookup; ``False`` (default): a sandboxed call runs at HEAD, clean or dirty.
        ``path``: the result's name, relative to the data folder (``<art store>/dats``), its folder
        there a view when it is a ``Dat``; an absolute path makes the folder there and names nothing
        (Q36). A hit asked for under a new name takes that name. ``kwargs``: the function's whole key
        set, for a key that is also a control option's name; inline keys beside it are ``TypeError``."""
        from .txn import Transaction

        rev = self._rev
        plain = rev._plain()
        level = seal_level(self.name, plain, seal, clean, path)
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
            hit = lookup(plain, self.name, enc)
            if hit is not None or level == "get":
                rev._record(item, ref_text(dotted(type(hit)), hit.hash) if hit is not None else "<none>")
                return place(plain.ledger, hit, target) if hit is not None and target is not None else hit
        into = level if isinstance(level, Transaction) else None
        # False: a draft; True: the memo entry in a transaction of its own; a Transaction: into it
        save: Any = True if isinstance(level, str) and level == "save" else (into if into is not None else False)
        if into is not None and target is None and self._takes_path:
            target = fresh_name(plain.ledger, self._template or ANONYMOUS, kw)
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
        rev._record(item, ref_text(dotted(type(value)), value.hash))
        if into is not None:
            return value
        if target is None and self._takes_path and isinstance(value, Dat):
            target = fresh_name(plain.ledger, self._template or ANONYMOUS, kw)
        return place(plain.ledger, value, target) if target is not None else value

    def _check_code(self, plain: "Rev", env: Env, repo: Optional[str]) -> str:
        """The base-mode gate, always (no byte record of what ran): code in a clean checkout."""
        if repo is None:
            raise NotEvaluated(f"{self.name}: its code ({self.module}) is outside any git checkout, so no "
                               "commit can vouch for a result")
        code = env.code[repo]
        if code.dirty:
            raise NotEvaluated(f"{self.name}: the checkout of {repo} has uncommitted changes; a result would "
                               "carry false provenance")
        return repo         # a db/repo/<repo> commit row names a clean run, not where evals may run

    def _run_base(self, plain: "Rev", kw: Dict[str, Any], enc: str, save: Any,
                  name: Optional[str] = None) -> Value:
        """Run in this process. ``save``: ``False``, a draft carrying its ``RunTrace``; ``True``, the
        memo entry in a transaction of its own; a ``Transaction``, the memo entry in it (named ``name``)."""
        from .rev import Rev
        from .txn import code_token

        env = current_env()
        repo = repo_of(env, self.module)
        if save is not False:                       # a draft simply runs (Eval § 2)
            self._check_code(plain, env, repo)
        rec: Dict[str, str] = {}
        work = work_folder() if self._takes_path else None
        args = dict(kw, path=work) if work is not None else kw
        value = None
        try:
            out = self._obj(Rev(plain.ledger, plain.id, _rec=rec), **args)
            value = wrap_result(self.name, self._obj, out)
            trace = dict(rec)
            trace.update({"code": self.code.subject, "fn": self.name, "platform": env.platform})
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
    """``clean=True`` (Q39): the checkout clean and at the commit ``plain``'s ``db/repo/<repo>`` row names."""
    repo = fn._info.get("repo") if fn.code.sandboxed else repo_of(env, fn.module)
    code = env.code.get(repo) if repo else None
    if code is None:
        raise NotClean(f"{fn.name}: clean=True, and its code ({fn.module}) is in no git checkout here")
    if code.dirty:
        raise NotClean(f"{fn.name}: clean=True, and the checkout of {repo} has uncommitted changes")
    c = plain.get(f"db/repo/{repo}", "commit")
    if c is None:
        raise NotClean(f"{fn.name}: clean=True, and rev {plain.id} names no db/repo/{repo} commit "
                       "(the first clean run of code with a __version__ writes it)")
    if not (code.commit and (code.commit.startswith(c) or c.startswith(code.commit))):
        raise NotClean(f"{fn.name}: clean=True, and rev {plain.id} binds db/repo/{repo} to {c[:8]}; "
                       f"the checkout is at {(code.commit or '?')[:8]}")


def fresh_name(ledger: Any, template: str, keys: Dict[str, Any]) -> str:
    """The path template expanded with the call's keys (Q36): ``{unique}`` counts up (``""``,
    ``_2``, ...) until no name holds a value there and no folder is at it; without ``{unique}`` the
    name moves to the new value (A70)."""
    import datetime as _dt

    from ..core import _builtins, expand

    now = _dt.datetime.now()
    data = ledger._store.art.root / "dats"
    head = ledger.at()
    for count in range(1, 100000):
        unique = "" if count == 1 else f"_{count}"
        text = expand(template, {**_builtins(now), **keys, "unique": unique})
        if not isinstance(text, str) or not text:
            raise TypeError(f"path template {template!r} expanded to {text!r}, not a path")
        if "{unique}" not in template:
            return text
        if os.path.isabs(text) or (not head._held(text, "db/alias") and not (data / text).exists()):
            return text
    raise RuntimeError(f"path template {template!r}: no free name")


def place(ledger: Any, value: Value, target: str) -> Value:
    """``path=`` on a result (Q36, A70): relative, the value's name, its folder (a ``Dat``) rebuilt at
    ``<data folder>/<name>`` as a view; absolute, the folder made there, no name. Unsaved
    (``seal=False`` or ``True``): the name is set on the object, saved with it."""
    if os.path.isabs(target):
        if isinstance(value, Dat) and value.subject is not None:
            art = ledger._store.art
            value._forget()
            value.path = Dat._materialise(art.get(value.hash), art, target)
        elif isinstance(value, Dat):
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
    if isinstance(value, Dat) and value.rev is None:        # unsaved, or saved by a transaction still open
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
        return Ref(ledger.at(), e.subject).load()
    return value


def lookup(plain: "Rev", name: str, enc: str) -> Optional[Value]:
    """The latest-sealed entry for ``(name, keys)`` whose dependencies hold at ``plain``; never runs."""
    from .rev import Ref
    from .trace import trace_matches

    top = plain.ledger.at()
    cands = []
    for s in top._store.subjects(top.id, predicate="db/keys", obj="json:" + enc):
        fnh = top._held(s, "db/fn")
        val = top._held(s, "db/value")
        if fnh and fnh[0].obj == "str:" + name and val:
            cands.append((val[0].rev, val[0].ord, s))
    for _r, _o, s in sorted(cands, reverse=True):
        trace = {p[len("db/deps/"):]: h.obj.partition(":")[2]
                 for _s, p, h in top._held_rows(subject=s) if p.startswith("db/deps/")}
        if trace_matches(plain, trace):
            return Ref(top, s).load()
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

        return sandbox_code_at(rev, name, json.loads(show(mods[0].obj))) == subject
    try:
        if any(name.startswith(prefix + ".") for prefix in mounts_at(rev._plain())):
            return False                        # mounted since: the code is the mount's now
        modname, src = source_of(name, resolve_in_process(name))
        return installed_code(modname, src, current_env()).subject == subject
    except (ImportError, TypeError):
        return False
