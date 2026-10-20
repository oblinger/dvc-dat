"""``ledger_fn``, ``Fn`` and ``eval`` (``Fn.__call__``): a revision function resolved at a ``Rev``.

``@ledger_fn`` declares and returns the function unchanged (A52): a plain call
runs the body and returns an unsealed ``Value``, recording nothing.
``rev.load_fn(name)`` resolves a dotted name at a revision: under a mounted
prefix (``db/mount/<prefix>`` rows) it is a sandboxed function, loaded from the
mounted tree and run in a worker (``sandbox``); otherwise a base function,
resolved in this process. Calling the ``Fn`` is ``eval``: a memo lookup over
every entry at the top whose ``db/fn`` and ``db/keys`` rows match, each
candidate's trace matched against the rev, the latest-sealed match winning
(Q20, A20); on a miss, run, record the trace, seal with ``db/fn``,
``db/keys`` and ``db/provenance eval:base|eval:sandbox``.
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
from .errors import NotEvaluated
from .value import Pickled, Value, dotted

if TYPE_CHECKING:
    from .rev import Rev

RESERVED_KEYS = ("memo", "work")


def ledger_fn(func: Callable) -> Callable:
    """Mark a value function: it takes the ``Rev`` first and keywords after, and returns a ``Value``.

    The return annotation is required (``TypeError`` at decoration): a ``Value`` subclass means the
    result must be one; any other annotation means a bare result is wrapped in ``Pickled`` (A31).
    The function comes back unchanged and still callable (A52); nothing is written on import.
    """
    if not callable(func):
        raise TypeError(f"@ledger_fn goes on a function, not {func!r}")
    ann = getattr(func, "__annotations__", {})
    if "return" not in ann:
        raise TypeError(f"@ledger_fn {getattr(func, '__qualname__', func)!r}: a return annotation is required "
                        "(-> a Value subclass, or any type to be wrapped in Pickled)")
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
    """The ``Value`` subclass the annotation names, or ``None`` (wrap a bare result in ``Pickled``)."""
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


def fn_subject(name: str, modules: Dict[str, str], mounts: Optional[str]) -> str:
    return f"db/fn/{name}/{hash_text(canonical({'modules': modules, 'mounts': mounts}), 16)}"


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


def signature_of(name: str, obj: Callable) -> Tuple[inspect.Signature, bool]:
    """The keys a function takes (the ``Rev`` and ``work`` excluded), and whether it takes ``work``."""
    sig = inspect.signature(obj)
    params = list(sig.parameters.values())
    if not params or params[0].kind not in (inspect.Parameter.POSITIONAL_ONLY,
                                            inspect.Parameter.POSITIONAL_OR_KEYWORD):
        raise TypeError(f"{name!r}: a revision function takes the Rev as its first parameter")
    rest = params[1:]
    if any(p.name == "memo" for p in rest):
        raise TypeError(f"{name!r}: 'memo' is reserved (Q12)")
    takes_work = any(p.name == "work" for p in rest)
    keep = [p for p in rest if p.name != "work"]
    return sig.replace(parameters=keep, return_annotation=inspect.Signature.empty), takes_work


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
    modname = getattr(obj, "__module__", None) or name.rpartition(".")[0]
    src = inspect.getsourcefile(obj)
    if not src or not os.path.exists(src):
        raise ImportError(f"{name!r}: no source file to hash")
    sha = sha256(Path(src).read_bytes())
    sig, takes_work = signature_of(name, obj)
    env = current_env()
    modules = base_closure(modname, Path(src), env)
    return Fn(name=name, module=Path(src), sha=sha, mode="base", mount=None, signature=sig, env=env,
              subject=fn_subject(name, modules, None), _rev=rev, _obj=obj, _takes_work=takes_work,
              _modules=modules, _returns=returns_text(obj))


def base_closure(modname: str, src: Path, env: Env) -> Dict[str, str]:
    """The base-mode ``fn`` hash input: the static import closure within the function's checkout (Q37 (iii)),
    ``relpath -> sha256``; outside any checkout, the module file alone."""
    from .sandbox import static_closure

    parts = modname.split(".")
    root = src.parent if src.name != "__init__.py" else src.parent.parent
    for _ in parts[1:]:
        root = root.parent
    repo = repo_of(env, src)
    code = env.code.get(repo) if repo else None
    within = code.path if code is not None and code.path is not None else root
    out = {}
    for _d, f in static_closure(root, modname, within).items():
        out[Path(os.path.realpath(f)).relative_to(os.path.realpath(within)).as_posix()] = sha256(f.read_bytes())
    return dict(sorted(out.items())) or {modname: sha256(src.read_bytes())}


@dataclass(frozen=True)
class Fn:
    """A revision function, resolved at ``_rev``; calling it is ``eval``."""

    name: str
    module: Path
    sha: str
    mode: str
    mount: Optional[str]
    signature: inspect.Signature
    env: Env
    subject: str
    _rev: Any = field(repr=False, compare=False)
    _obj: Any = field(repr=False, compare=False, default=None)
    _takes_work: bool = field(repr=False, compare=False, default=False)
    _modules: Dict[str, str] = field(repr=False, compare=False, default_factory=dict)
    _returns: str = field(repr=False, compare=False, default="")
    _info: Dict[str, Any] = field(repr=False, compare=False, default_factory=dict)

    def _rows(self, subject: Optional[str] = None, modules: Optional[Dict[str, str]] = None) -> List[Tuple[str, str]]:
        """The ``db/fn/<name>/<hash>`` rows (A15, A31)."""
        mh = mounts_hash(self._rev._plain()) if self.mode == "sandbox" else None
        return [("db/name", "str:" + self.name), ("db/module", "str:" + str(self.module)),
                ("db/sha", "str:" + self.sha), ("db/modules", "json:" + canonical(modules or self._modules)),
                ("db/mounts", "str:" + (mh or "none")), ("db/mode", "str:" + self.mode),
                ("db/returns", "str:" + self._returns)]

    def _bind(self, keys: Dict[str, Any]) -> Dict[str, Any]:
        for k in RESERVED_KEYS:
            if k in keys:
                raise TypeError(f"{k!r} is reserved and never a key")
        bound = self.signature.bind(**keys)
        bound.apply_defaults()
        out: Dict[str, Any] = {}
        for k, v in bound.arguments.items():
            if self.signature.parameters[k].kind is inspect.Parameter.VAR_KEYWORD:
                out.update(v)
            else:
                out[k] = v
        return out

    def __call__(self, *, memo: Any = True, **keys: Any) -> Optional[Value]:
        """``True``: the memoised Value, or run, seal, return; ``False``: run, seal nothing; ``"get"``: lookup only."""
        if not (memo is True or memo is False or memo == "get"):
            raise ValueError(f"memo is True, False or 'get', not {memo!r}")
        rev = self._rev
        plain = rev._plain()
        kw = self._bind(keys)
        enc = canonical(encode_keys(kw))
        item = f"eval:{self.name}{enc}"
        if memo is not False:
            hit = lookup(plain, self.name, enc)
            if hit is not None or memo == "get":
                rev._record(item, ref_text(dotted(type(hit)), hit.hash) if hit is not None else "<none>")
                return hit
        if self.mode == "sandbox":
            from .sandbox import run_sandboxed

            value = run_sandboxed(self, plain, kw, enc, memo is not False)
        else:
            value = self._run_base(plain, kw, enc, memo is not False)
        rev._record(item, ref_text(dotted(type(value)), value.hash))
        return value

    def _check_code(self, plain: "Rev", env: Env, repo: Optional[str]) -> str:
        if repo is None:
            raise NotEvaluated(f"{self.name}: its code ({self.module}) is outside any git checkout, so no "
                               "commit can vouch for a result")
        code = env.code[repo]
        if code.dirty:
            raise NotEvaluated(f"{self.name}: the checkout of {repo} has uncommitted changes; a result would "
                               "carry false provenance")
        c = plain.get(f"code/{repo}", "commit")
        if c is not None and not (code.commit and (code.commit.startswith(c) or c.startswith(code.commit))):
            raise NotEvaluated(f"{self.name}: rev {plain.id} binds code/{repo} to commit {c[:8]}; this "
                               f"environment is at {(code.commit or '?')[:8]}; a miss there cannot run here")
        return repo

    def _run_base(self, plain: "Rev", kw: Dict[str, Any], enc: str, seal: bool) -> Value:
        from .rev import Rev
        from .txn import code_token

        env = current_env()
        repo = repo_of(env, self.module)
        if seal:                                    # memo=False simply runs (Eval § 2)
            self._check_code(plain, env, repo)
        rec: Dict[str, str] = {}
        work = Path(tempfile.mkdtemp(prefix="ledger-work-")) if self._takes_work else None
        args = dict(kw, work=work) if work is not None else kw
        value = None
        try:
            out = self._obj(Rev(plain.ledger, plain.id, _rec=rec), **args)
            value = wrap_result(self.name, self._obj, out)
            trace = dict(rec)
            trace.update({"fn": self.subject, "uv.lock": env.lock, "platform": env.platform})
            if repo is not None:
                trace[f"code/{repo}"] = code_token(plain, repo, env.code[repo].commit)
            if not seal:
                value.trace = trace  # type: ignore[misc]
                return value
            value = seal_entry(self, plain, value, trace, enc, "eval:base")
            return value
        finally:
            drop_work(work, value)


def drop_work(work: Optional[Path], value: Any) -> None:
    """Remove an eval's ``work`` folder once the call is done, sealed or not; an unsealed ``Dat`` that
    still lives in it (``memo=False``) keeps it, since the folder is that value."""
    from .value import Dat

    if work is None or not work.exists():
        return
    if isinstance(value, Dat) and value.subject is None:
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
    return out if isinstance(out, Value) else Pickled(out)


class _AlreadySealed(Exception):
    def __init__(self, subject: str) -> None:
        self.subject = subject


def seal_entry(fn: Fn, plain: "Rev", value: Value, trace: Dict[str, str], enc: str, provenance: str,
               modules: Optional[Dict[str, str]] = None) -> Value:
    """Seal an eval's result as a memo entry, or hand back the identical entry already sealed."""
    from .rev import Ref

    ledger = plain.ledger
    if value.sealed and value.subject is None:
        raise TypeError(f"{fn.name} returned a {type(value).__name__} sealed by v.seal(); eval seals its own "
                        "result, so return it unsealed")
    vtext = ref_text(dotted(type(value)), value.hash)
    try:
        with ledger.transaction(by=f"eval:{fn.name}") as t:
            pred_rows, canon = t._encode_preds(value)
            subject = hash_text(canonical({"fn": fn.name, "keys": json.loads(enc), "trace": trace,
                                           "preds": canon, "value": vtext}))
            if t.base._held(subject, "db/value"):
                raise _AlreadySealed(subject)
            fsub = trace.get("fn", fn.subject)
            if fsub not in t._fns and not t.base._held(fsub, "db/name"):
                t._fns.add(fsub)
                from .txn import _Op

                for p, o in fn._rows(fsub, modules):
                    t._ops.append(_Op(fsub, p, o, True))
            t._seal(value, subject, trace, provenance, pred_rows,
                    [("db/fn", "str:" + fn.name), ("db/keys", "json:" + enc)], None)
    except _AlreadySealed as e:
        return Ref(ledger.at(), e.subject).load()
    return value


def lookup(plain: "Rev", name: str, enc: str) -> Optional[Value]:
    """The latest-sealed entry for ``(name, keys)`` whose trace holds at ``plain``; never runs."""
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
        trace = {p[len("db/trace/"):]: h.obj.partition(":")[2]
                 for _s, p, h in top._held_rows(subject=s) if p.startswith("db/trace/")}
        if trace_matches(plain, trace):
            return Ref(top, s).load()
    return None


def lookup_encoded(rev: "Rev", name: str, enc: str) -> Optional[Value]:
    return lookup(rev._plain(), name, enc)


def fn_holds(rev: "Rev", subject: str) -> bool:
    """Does the ``fn`` item still name the code ``rev`` resolves to (memo only, nothing runs)."""
    from .codec import show

    top = rev.ledger.at()
    mode = top._held(subject, "db/mode")
    name = top._held(subject, "db/name")
    if not mode or not name:
        return False
    nm = show(name[0].obj)
    if show(mode[0].obj) == "sandbox":
        from .sandbox import sandbox_subject_at

        mods = json.loads(show(top._held(subject, "db/modules")[0].obj))
        return sandbox_subject_at(rev, nm, mods) == subject
    try:
        return load_fn(rev, nm).subject == subject
    except (ImportError, TypeError):
        return False
