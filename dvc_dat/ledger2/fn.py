"""``Fn``: a revision function resolved at a ``Rev``, and ``eval`` (``Fn.__call__``), base mode only.

Base mode: the dotted name resolves in the running process. The code
identity is ``code/<repo>`` from the ledger, checked against the
environment's own (``Fn.env.code``) before any run. The environment comes
from a provider: by default git discovery over the function's source file
(repo = the checkout's folder name, commit = HEAD, dirty = tracked changes),
replaceable with ``set_env_provider`` (tests, notebooks, a pinned deploy).
The sandbox (mounts, worker, ``MountFinder``) is not built: a name under a
mounted prefix raises ``NotImplementedError``.
"""

from __future__ import annotations

import functools
import importlib
import inspect
import os
import platform as _platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from .codec import canonical, key_text, ref_text, sha256, short
from .errors import NotEvaluated, Unindexed
from .value import Pickled, Value

if TYPE_CHECKING:
    from .rev import Rev

_MEMO = (True, False, "get")


@dataclass(frozen=True)
class Code:
    """One repo's code as the environment has it."""

    version: Optional[str]
    commit: Optional[str]
    dirty: bool = False


@dataclass(frozen=True)
class Env:
    """The environment a function will run in: the base-mode half of the trace."""

    code: Dict[str, Code]
    lock: str
    platform: str
    mounts: Optional[str] = None


Provider = Callable[[Optional[str]], Env]
_provider: Optional[Provider] = None


def set_env_provider(provider: Optional[Provider]) -> Optional[Provider]:
    """Replace how the environment is found (``provider(module_name or None) -> Env``); returns the old one."""
    global _provider
    old, _provider = _provider, provider
    return old


def current_env(module: Optional[str]) -> Env:
    """The environment for code in ``module`` (``None``: the process, from the working directory)."""
    return (_provider or discover)(module)


def _git(folder: str, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


@functools.lru_cache(maxsize=64)
def _discover_folder(folder: str) -> Env:
    plat = f"{sys.platform}-{_platform.machine()}-py{sys.version_info[0]}.{sys.version_info[1]}"
    top = _git(folder, "rev-parse", "--show-toplevel")
    if not top:
        return Env({}, "<none>", plat)
    commit = _git(top, "rev-parse", "HEAD")
    dirty = bool(_git(top, "status", "--porcelain", "--untracked-files=no"))
    lock = Path(top, "uv.lock")
    return Env({os.path.basename(top): Code(None, commit, dirty)},
               sha256(lock.read_bytes()) if lock.exists() else "<none>", plat)


def discover(module: Optional[str]) -> Env:
    """The default provider: git discovery over the module's source folder (cached per folder per process)."""
    folder = os.getcwd()
    if module is not None:
        f = getattr(sys.modules.get(module), "__file__", None)
        if f:
            folder = os.path.dirname(os.path.abspath(f))
    return _discover_folder(folder)


def fn_name_of(subject: str) -> str:
    """The dotted name in ``ledger/fn/<name>/<hash>``."""
    return subject[len("ledger/fn/"):].rpartition("/")[0]


def _resolve(name: str) -> Any:
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


def load_fn(rev: "Rev", name: str) -> "Fn":
    if not isinstance(name, str) or "." not in name:
        raise TypeError(f"a revision function is named by a dotted str, not {name!r}")
    plain = rev._plain()
    for s, _p, _h in plain._held_rows(predicate="root", prefix="ledger/mount/"):
        prefix = s[len("ledger/mount/"):]
        if name == prefix or name.startswith(prefix + "."):
            raise NotImplementedError(
                f"{name!r} is under the mount {prefix!r}: sandbox mode is not built in the ledger2 spike")
    obj = _resolve(name)
    if not callable(obj):
        raise TypeError(f"{name!r} resolves to {type(obj).__name__}, not a function")
    modname = getattr(obj, "__module__", None) or name.rpartition(".")[0]
    try:
        src = inspect.getsourcefile(obj)
    except TypeError:
        src = None
    if src and os.path.exists(src):
        sha = sha256(Path(src).read_bytes())
    else:
        try:
            sha = sha256(inspect.getsource(obj).encode())
        except (OSError, TypeError) as e:
            raise ImportError(f"{name!r}: no source to hash ({e})") from None
    sig = inspect.signature(obj)
    params = list(sig.parameters.values())
    if not params or params[0].kind not in (inspect.Parameter.POSITIONAL_ONLY,
                                            inspect.Parameter.POSITIONAL_OR_KEYWORD):
        raise TypeError(f"{name!r}: a revision function takes the Rev as its first parameter")
    env = current_env(modname)
    subject = f"ledger/fn/{name}/{short(canonical({'modules': {modname: sha}, 'mounts': None}))}"
    return Fn(name=name, module=Path(src) if src else None, sha=sha, mode="base", mount=None,
              signature=sig.replace(parameters=params[1:]), env=env, subject=subject,
              _rev=rev, _obj=obj, _module_name=modname)


@dataclass(frozen=True)
class Fn:
    """A revision function, resolved at ``_rev``; calling it is ``eval``."""

    name: str
    module: Optional[Path]
    sha: str
    mode: str
    mount: Optional[str]
    signature: inspect.Signature
    env: Env
    subject: str
    _rev: Any = field(repr=False, compare=False)
    _obj: Any = field(repr=False, compare=False)
    _module_name: str = field(repr=False, compare=False, default="")

    # -- keys -----------------------------------------------------------------

    def _bind(self, keys: Dict[str, Any]) -> Dict[str, Any]:
        bound = self.signature.bind(**keys)
        bound.apply_defaults()
        out: Dict[str, Any] = {}
        for k, v in bound.arguments.items():
            if self.signature.parameters[k].kind is inspect.Parameter.VAR_KEYWORD:
                out.update(v)
            else:
                out[k] = v
        return out

    @staticmethod
    def _key_obj(v: Any) -> str:
        from .rev import Ref

        if isinstance(v, Ref):
            return ref_text(v._cls, v.hash, v._target or v.subject)
        return "str:" + key_text(v)

    @staticmethod
    def _key_tok(v: Any) -> str:
        from .rev import Ref, token

        return token(v) if isinstance(v, Ref) else key_text(v)

    # -- eval -----------------------------------------------------------------

    def __call__(self, *, memo: Any = True, **keys: Any) -> Optional[Value]:
        """``True``: the memoised Value or run, seal, return; ``False``: run, seal nothing; ``"get"``: lookup only."""
        if not any(memo is m if not isinstance(m, str) else memo == m for m in _MEMO):
            raise ValueError(f"memo is True, False or 'get', not {memo!r}")
        rev = self._rev
        plain = rev._plain()
        kw = self._bind(keys)
        item = f"eval:{self.name}" + canonical({k: self._key_tok(v) for k, v in kw.items()})
        if memo is not False:
            hit = self._lookup(plain, kw)
            if hit is not None or memo == "get":
                rev._record(item, hit.hash if hit is not None else "<none>")
                return hit
        self._check_code(plain)
        rec: Dict[str, str] = {}
        from .rev import Rev

        out = self._obj(Rev(plain.ledger, plain.id, _rec=rec), **kw)
        value = out if isinstance(out, Value) else Pickled(out)
        trace = dict(rec)
        for repo in self.env.code:
            trace[f"code/{repo}"] = plain._code_token(f"code/{repo}")
        trace.update({"fn": self.subject, "uv.lock": self.env.lock, "platform": self.env.platform})
        if memo is False:
            value._provenance(subject=None, rev=plain, trace=trace, sealed=False)
        else:
            enc = {k: self._key_obj(v) for k, v in kw.items()}
            subject = (f"{type(value).__name__}/"
                       f"{short(canonical({'fn': self.name, 'keys': enc, 'trace': trace, 'hash': value.hash}))}")
            extra = [("fn", "str:" + self.name)] + [(f"kwargs.{k}", o) for k, o in sorted(enc.items())]
            with plain.ledger.transaction(by=f"eval:{self.name}") as t:
                t._ensure_fn(self)
                t._seal(value, subject, trace, "eval", extra, plain, keys=kw)
        rev._record(item, value.hash)
        return value

    def _lookup(self, plain: "Rev", kw: Dict[str, Any]) -> Optional[Value]:
        from .rev import Ref

        where: Dict[str, Any] = {"fn": self.name, "provenance": "eval"}
        where.update({f"kwargs.{k}": v for k, v in kw.items()})
        # Entries are found at the top, not as of ``plain``: an entry sealed after ``plain`` for
        # ``plain``'s exact trace is still the answer (Eval § 2, Versions § 7: running at an old
        # revision hits what was sealed under its bindings). The trace is matched against ``plain``.
        top = plain.ledger.at()
        try:
            cands = top._subjects(None, where, {}, None)
        except Unindexed:
            return None
        want = {f"kwargs.{k}" for k in kw}
        for s in reversed(cands):
            rows = top._held_rows(subject=s)
            if {p for _s, p, _h in rows if p.startswith("kwargs.")} != want:
                continue
            trace = {p[len("trace."):]: top._decode(h.obj, s) for _s, p, h in rows if p.startswith("trace.")}
            if plain._matches(trace):
                return Ref(top, s)._load(rev=plain)
        return None

    def _check_code(self, plain: "Rev") -> None:
        if not self.env.code:
            raise NotEvaluated(f"{self.name}: its code is outside any git checkout, so no code/<repo> row "
                               "can vouch for it")
        for repo, code in self.env.code.items():
            subj = f"code/{repo}"
            v, c = plain.get(subj, "version"), plain.get(subj, "commit")
            here = f"{code.version or ''}+{code.commit or ''}"
            if code.dirty:
                raise NotEvaluated(f"{self.name}: the working tree of {repo} is dirty ({here}); "
                                   "a result would carry false provenance")
            if v is None and c is None:
                raise NotEvaluated(f"{self.name}: rev {plain.id} has no {subj} row to run against")
            if c is not None:
                ok = bool(code.commit) and (code.commit.startswith(c) or c.startswith(code.commit))
            else:
                ok = code.version is not None and code.version == v
            if not ok:
                raise NotEvaluated(f"{self.name}: rev {plain.id} binds {subj} to {v}+{c}; "
                                   f"this environment is {here}")
