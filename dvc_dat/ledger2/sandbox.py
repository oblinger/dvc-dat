"""Sandbox mode: a function under a ``db/mount/<prefix>`` row, loaded from the mounted tree, run in a worker.

Parent side (``load_sandboxed``, ``run_sandboxed``): the name resolves through
the mounts as of the rev to a file under ``<checkout>/<db/root>``, the checkout
being what discovery reports for the mount's ``db/repo`` (A40); no checkout is
``NotEvaluated`` naming the repo. A miss runs in a worker process, one per
mount (Q37 consequence (i)), started ``python -I`` (the standard library,
``site-packages`` and nothing else on its path) with ``DAT_LEDGER`` naming the
parent's ledger (A44). The worker seals the entry itself and hands back its
subject; an exception comes back with the worker's traceback, nothing sealed.

Worker side (``worker.py`` drives it): ``MountFinder``, first on
``sys.meta_path``, loads a mounted prefix from its root, gives the prefix's
ancestors empty namespace packages (their ``__init__`` never runs), records
every module it loads against the innermost running eval, and refuses a
module that would resolve inside a mounted repo's checkout but under no mount
(``UnmountedImport``). An audit hook on ``open`` refuses, while a function
body runs, a read outside the mounted roots, the art store (dats), the
worker's scratch and the interpreter's own files (``UntracedRead``), and a
write outside the scratch (where ``work`` folders live) and the art store.
Before each top-level call the mounted modules are purged from
``sys.modules``, so each run loads (and records) what it uses; a nested eval
runs in-process and its loads count toward its own entry (Q37 (ii)).

The ``fn`` item (Q37 (A), lean): the static import closure of the function's
module (its ``import`` statements, read from the source, within the mounts)
plus every module loaded during the run and their closures, each
``relpath -> sha256`` at the rev's commit, hashed with the mount rows into
``db/fn/<name>/<hash>``. ``Fn.subject`` before any run is the static closure.
"""

from __future__ import annotations

import ast
import atexit
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import inspect
import os
import pickle
import struct
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from .codec import sha256
from .env import Env, current_env
from .errors import NotEvaluated, UnmountedImport, UntracedRead
from .fn import Fn, fn_subject, mounts_at, mounts_hash, returns_class, seal_entry, wrap_result

if TYPE_CHECKING:
    from .rev import Rev

IN_WORKER = False


# -- resolution through the mounts -----------------------------------------------------------------

class Mount:
    def __init__(self, prefix: str, root: str, repo: str, checkout: Path, salt: Optional[str] = None) -> None:
        self.prefix, self.root, self.repo, self.checkout, self.salt = prefix, root, repo, Path(checkout), salt

    @property
    def path(self) -> Path:
        return self.checkout / self.root

    def file_of(self, dotted: str) -> Optional[Tuple[Path, bool]]:
        """``(file, is_package)`` of a dotted module under this mount, or ``None``."""
        if dotted == self.prefix:
            rest: List[str] = []
        elif dotted.startswith(self.prefix + "."):
            rest = dotted[len(self.prefix) + 1:].split(".")
        else:
            return None
        base = self.path.joinpath(*rest)
        if (base / "__init__.py").is_file():
            return base / "__init__.py", True
        if base.with_suffix(".py").is_file() and rest:
            return base.with_suffix(".py"), False
        return None


def mounts_for(rev: "Rev", env: Env) -> Tuple[List[Mount], Dict[str, Dict[str, str]]]:
    rows = mounts_at(rev)
    out = []
    for prefix, info in rows.items():
        code = env.code.get(info.get("repo", ""))
        if code is not None and code.path is not None:
            out.append(Mount(prefix, info["root"], info["repo"], code.path, info.get("salt")))
    return out, rows


def _mount_of(mounts: List[Mount], dotted: str) -> Optional[Mount]:
    best = None
    for m in mounts:
        if (dotted == m.prefix or dotted.startswith(m.prefix + ".")) and (best is None or len(m.prefix) > len(best.prefix)):
            best = m
    return best


def _commit_for(rev: "Rev", repo: str, env: Env) -> Optional[str]:
    """The commit the rev binds the repo to, when it differs from the checkout's HEAD (else ``None``: disk)."""
    c = rev.get(f"code/{repo}", "commit")
    head = env.code[repo].commit if repo in env.code else None
    if c and head and not (head.startswith(c) or c.startswith(head)):
        return c
    return None


def file_sha(checkout: Path, rel: str, commit: Optional[str]) -> str:
    if commit:
        try:
            data = subprocess.run(["git", "-C", str(checkout), "show", f"{commit}:{rel}"], capture_output=True,
                                  check=True, timeout=20).stdout
            return sha256(data)
        except (OSError, subprocess.SubprocessError):
            return "<missing>"
    p = checkout / rel
    return sha256(p.read_bytes()) if p.is_file() else "<missing>"


def _imports(path: Path, dotted: str, is_pkg: bool) -> Set[str]:
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return set()
    pkg = dotted if is_pkg else dotted.rpartition(".")[0]
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                parts = a.name.split(".")
                out.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg.split(".")
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            if mod:
                out.add(mod)
                out.update(f"{mod}.{a.name}" for a in node.names)
    return out


def closure(mounts: List[Mount], start: List[str]) -> Dict[str, Tuple[Mount, Path]]:
    """Every mounted module reachable from ``start`` (dotted names) by import statements."""
    seen: Dict[str, Tuple[Mount, Path]] = {}
    todo = list(start)
    while todo:
        d = todo.pop()
        if d in seen:
            continue
        m = _mount_of(mounts, d)
        if m is None:
            continue
        f = m.file_of(d)
        if f is None:
            continue
        seen[d] = (m, f[0])
        todo.extend(_imports(f[0], d, f[1]))
    return seen


def module_shas(rev: "Rev", env: Env, mods: Dict[str, Tuple[Mount, Path]]) -> Dict[str, str]:
    out = {}
    for _d, (m, path) in mods.items():
        rel = path.relative_to(m.checkout).as_posix()
        out[rel] = file_sha(m.checkout, rel, _commit_for(rev, m.repo, env))
    return dict(sorted(out.items()))


def _signature(fdef: ast.FunctionDef, name: str) -> Tuple[inspect.Signature, bool, str, bool]:
    a = fdef.args
    params = []
    pos = a.posonlyargs + a.args
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)

    def default(node: Any) -> Any:
        if node is None:
            return inspect.Parameter.empty
        try:
            return ast.literal_eval(node)
        except ValueError:
            return ast.unparse(node)

    def ann(node: Any) -> Any:
        return inspect.Parameter.empty if node is None else ast.unparse(node)
    for arg, d in zip(pos, defaults):
        params.append(inspect.Parameter(arg.arg, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=default(d),
                                        annotation=ann(arg.annotation)))
    for arg, d in zip(a.kwonlyargs, a.kw_defaults):
        params.append(inspect.Parameter(arg.arg, inspect.Parameter.KEYWORD_ONLY, default=default(d),
                                        annotation=ann(arg.annotation)))
    if a.kwarg is not None:
        params.append(inspect.Parameter(a.kwarg.arg, inspect.Parameter.VAR_KEYWORD))
    if not params or params[0].kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD:
        raise TypeError(f"{name!r}: a revision function takes the Rev as its first parameter")
    rest = params[1:]
    takes_work = any(p.name == "work" for p in rest)
    keep = [p for p in rest if p.name != "work"]
    decorated = any((isinstance(d, ast.Name) and d.id == "ledger_fn")
                    or (isinstance(d, ast.Attribute) and d.attr == "ledger_fn") for d in fdef.decorator_list)
    returns = ast.unparse(fdef.returns) if fdef.returns is not None else ""
    return inspect.Signature(keep), takes_work, returns, decorated


def load_sandboxed(rev: "Rev", name: str, prefix: str, info: Dict[str, str]) -> Fn:
    plain = rev._plain()
    env = current_env()
    repo = info.get("repo")
    code = env.code.get(repo or "")
    if code is None or code.path is None:
        raise NotEvaluated(f"{name!r} is under the mount {prefix!r} of repo {repo!r}, which has no checkout in "
                           "this environment")
    mounts, _rows = mounts_for(plain, env)
    m = _mount_of(mounts, name)
    assert m is not None
    modname, _, attr_name = name.rpartition(".")
    f = m.file_of(modname)
    if f is None:
        raise ImportError(f"{name!r}: no module {modname!r} under {m.path}")
    tree = ast.parse(f[0].read_text())
    fdef = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == attr_name), None)
    if fdef is None:
        raise ImportError(f"{name!r}: no function {attr_name!r} in {f[0]}")
    sig, takes_work, returns, decorated = _signature(fdef, name)
    if not decorated:
        raise TypeError(f"{name!r} is not a ledger function (mark it @ledger_fn)")
    mods = module_shas(plain, env, closure(mounts, [modname]))
    rel = f[0].relative_to(m.checkout).as_posix()
    return Fn(name=name, module=f[0], sha=file_sha(m.checkout, rel, _commit_for(plain, m.repo, env)),
              mode="sandbox", mount=m.prefix, signature=sig, env=Env(env.code, env.lock, env.platform,
                                                                      mounts_hash(plain)),
              subject=fn_subject(name, mods, mounts_hash(plain)), _rev=rev, _takes_work=takes_work,
              _modules=mods, _returns=returns,
              _info={"repo": m.repo, "prefix": m.prefix, "modname": modname, "attr": attr_name})


def sandbox_subject_at(rev: "Rev", name: str, modules: Dict[str, str]) -> Optional[str]:
    """The ``fn`` subject the recorded modules hash to at ``rev`` (memo only: nothing loads or runs)."""
    plain = rev._plain()
    env = current_env()
    mounts, _rows = mounts_for(plain, env)
    m = _mount_of(mounts, name)
    if m is None:
        return None
    commit = _commit_for(plain, m.repo, env)
    now = {rel: file_sha(m.checkout, rel, commit) for rel in modules}
    return fn_subject(name, dict(sorted(now.items())), mounts_hash(plain))


def _check_code(fn: Fn, plain: "Rev", env: Env) -> None:
    repo = fn._info["repo"]
    code = env.code.get(repo)
    if code is None:
        raise NotEvaluated(f"{fn.name}: repo {repo!r} has no checkout in this environment")
    if code.dirty:
        raise NotEvaluated(f"{fn.name}: the checkout of {repo} has uncommitted changes; a sandboxed result "
                           "must be reproducible from a commit")
    c = plain.get(f"code/{repo}", "commit")
    if c is not None and not (code.commit and (code.commit.startswith(c) or c.startswith(code.commit))):
        raise NotEvaluated(f"{fn.name}: rev {plain.id} binds code/{repo} to commit {c[:8]}; this environment "
                           f"is at {(code.commit or '?')[:8]}; a miss there cannot run here")


def run_sandboxed(fn: Fn, plain: "Rev", kw: Dict[str, Any], enc: str, seal: bool) -> Any:
    env = current_env()
    _check_code(fn, plain, env)
    if IN_WORKER:
        return run_here(fn, plain, kw, enc, seal)
    return _pool(plain, fn._info["prefix"]).call(fn, plain, kw, seal, env)


# -- the worker's own machinery -----------------------------------------------------------------------

class _State:
    mounts: List[Mount] = []
    frames: List[Set[str]] = []
    guard = False
    reads: List[str] = []
    writes: List[str] = []


STATE = _State()


class _Loader(importlib.machinery.SourceFileLoader):
    def exec_module(self, module: Any) -> None:
        if STATE.frames:
            STATE.frames[-1].add(module.__name__)
        super().exec_module(module)


def _importer() -> str:
    for fr in inspect.stack()[2:]:
        name = fr.frame.f_globals.get("__name__", "")
        if not name.startswith(("importlib", "dvc_dat.ledger2.sandbox")) and name != "<frozen importlib._bootstrap>":
            return name
    return "?"


class MountFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        m = _mount_of(STATE.mounts, fullname)
        if m is not None:
            f = m.file_of(fullname)
            if f is None:
                return None
            loader = _Loader(fullname, str(f[0]))
            return importlib.util.spec_from_file_location(
                fullname, str(f[0]), loader=loader,
                submodule_search_locations=[str(f[0].parent)] if f[1] else None)
        if any(mm.prefix.startswith(fullname + ".") for mm in STATE.mounts):
            spec = importlib.machinery.ModuleSpec(fullname, None, is_package=True)
            spec.submodule_search_locations = []
            return spec
        parts = fullname.split(".")
        for mm in STATE.mounts:
            base = mm.checkout.joinpath(*parts)
            if (base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()
                    or (mm.checkout / parts[0]).is_dir() and len(parts) > 1 and base.exists()):
                raise UnmountedImport(f"{fullname} from {_importer()}; mount it or move it")
        return None


def _allowed_roots() -> Tuple[List[str], List[str]]:
    import dvc_dat
    import sysconfig

    reads = {sys.prefix, sys.base_prefix, sys.exec_prefix, "/dev", str(Path(dvc_dat.__file__).parent)}
    for k in ("stdlib", "platstdlib", "purelib", "platlib"):
        p = sysconfig.get_paths().get(k)
        if p:
            reads.add(p)
    return [os.path.realpath(r) for r in reads], []


def _under(p: str, roots: List[str]) -> bool:
    return any(p == r or p.startswith(r + os.sep) for r in roots)


def _audit(event: str, args: Any) -> None:
    if event != "open" or not STATE.guard:
        return
    path, mode, flags = (list(args) + [None, None, None])[:3]
    if not isinstance(path, (str, bytes, os.PathLike)):
        return
    p = os.path.realpath(os.fsdecode(path))
    write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
        isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
    if write:
        if not _under(p, STATE.writes):
            raise UntracedRead(f"{p}: a sandboxed function writes only in its work folder")
        return
    if not _under(p, STATE.reads + STATE.writes):
        raise UntracedRead(f"{p}: outside the mounts, the dats and the scratch")


def install_worker(ledger: Any, mounts: List[Mount], scratch: Path) -> None:
    global IN_WORKER
    IN_WORKER = True
    if not any(isinstance(f, MountFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, MountFinder())
        sys.addaudithook(_audit)
    STATE.mounts = mounts
    base_reads, _ = _allowed_roots()
    art = os.path.realpath(ledger._store.art.root)
    STATE.reads = base_reads + [os.path.realpath(m.path) for m in mounts] + [art]
    STATE.writes = [os.path.realpath(scratch), art]


def purge_mounted() -> None:
    for name in list(sys.modules):
        if _mount_of(STATE.mounts, name) is not None or any(m.prefix.startswith(name + ".") for m in STATE.mounts):
            del sys.modules[name]
    importlib.invalidate_caches()


def run_here(fn: Fn, plain: "Rev", kw: Dict[str, Any], enc: str, seal: bool) -> Any:
    from .rev import Rev

    env = current_env()
    mounts, rows = mounts_for(plain, env)
    STATE.mounts = mounts
    modname, attr_name = fn._info["modname"], fn._info["attr"]
    STATE.frames.append(set())
    outer_guard = STATE.guard
    work = Path(tempfile.mkdtemp(prefix="work-", dir=os.environ.get("DAT_SCRATCH") or None)) \
        if fn._takes_work else None
    try:
        obj = getattr(importlib.import_module(modname), attr_name)
        if not getattr(obj, "__ledger_fn__", False):
            raise TypeError(f"{fn.name!r} is not a ledger function (mark it @ledger_fn)")
        rec: Dict[str, str] = {}
        args = dict(kw, work=work) if work is not None else kw
        STATE.guard = True
        try:
            out = obj(Rev(plain.ledger, plain.id, _rec=rec), **args)
        finally:
            STATE.guard = outer_guard
        loaded = STATE.frames[-1]
    finally:
        STATE.frames.pop()
    value = wrap_result(fn.name, obj, out)
    mods = module_shas(plain, env, closure(mounts, [modname, *sorted(loaded)]))
    fsub = fn_subject(fn.name, mods, mounts_hash(plain))
    trace = dict(rec)
    trace.update({"fn": fsub, "uv.lock": env.lock, "platform": env.platform})
    salt = rows.get(fn._info["prefix"], {}).get("salt")
    if salt is not None:
        trace[f"db/mount/{fn._info['prefix']} db/salt"] = salt
    if not seal:
        value.trace = trace  # type: ignore[misc]
        return value
    return seal_entry(fn, plain, value, trace, enc, "eval:sandbox", modules=mods)


# -- the parent's view of a worker ---------------------------------------------------------------------

def send(stream: Any, obj: Any) -> None:
    data = pickle.dumps(obj, protocol=4)
    stream.write(struct.pack(">Q", len(data)) + data)
    stream.flush()


def recv(stream: Any) -> Any:
    head = stream.read(8)
    if len(head) < 8:
        raise EOFError("the worker closed its channel")
    (n,) = struct.unpack(">Q", head)
    return pickle.loads(stream.read(n))


def encode_key(v: Any) -> Any:
    from .rev import Ref
    from .value import Value

    if isinstance(v, Ref):
        return ("__ref__", v.subject)
    if isinstance(v, Value):
        return ("__ref__", v.subject)
    return v


class Worker:
    """One ``python -I`` process serving one mount of one ledger."""

    def __init__(self, ledger_path: Path) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="ledger-worker-"))
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "LANG", "CUDA_VISIBLE_DEVICES")}
        env["DAT_LEDGER"] = str(ledger_path)
        env["DAT_SCRATCH"] = str(self.scratch)
        self.proc = subprocess.Popen([sys.executable, "-I", "-m", "dvc_dat.ledger2.worker"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, cwd=str(self.scratch), env=env)
        self.lock = threading.Lock()

    def alive(self) -> bool:
        return self.proc.poll() is None

    def call(self, fn: Fn, plain: "Rev", kw: Dict[str, Any], seal: bool, env: Env) -> Any:
        from .rev import Ref

        req = {"rev": plain.id, "name": fn.name, "keys": {k: encode_key(v) for k, v in kw.items()}, "seal": seal,
               "env": {r: (c.version, c.commit, c.dirty, str(c.path) if c.path else None) for r, c in env.code.items()}}
        with self.lock:
            send(self.proc.stdin, req)
            resp = recv(self.proc.stdout)
        if resp["ok"]:
            if seal:
                return Ref(plain.ledger.at(), resp["subject"]).load()
            v = pickle.loads(resp["value"])
            return v
        exc = None
        if resp.get("exc") is not None:
            try:
                exc = pickle.loads(resp["exc"])
            except Exception:
                exc = None
        if not isinstance(exc, BaseException):
            exc = RuntimeError(f"{resp['type']}: {resp['message']}")
        try:
            exc.worker_traceback = resp["traceback"]  # type: ignore[attr-defined]
        except Exception:
            pass
        raise exc

    def close(self) -> None:
        if self.alive():
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()


_POOL: Dict[Tuple[str, str], Worker] = {}
_POOL_LOCK = threading.Lock()


def _pool(plain: "Rev", prefix: str) -> Worker:
    key = (str(plain.ledger.path), prefix)
    with _POOL_LOCK:
        w = _POOL.get(key)
        if w is None or not w.alive():
            w = _POOL[key] = Worker(plain.ledger.path)
        return w


def shutdown() -> None:
    """Stop every worker (also run at exit)."""
    with _POOL_LOCK:
        for w in _POOL.values():
            w.close()
        _POOL.clear()


atexit.register(shutdown)


def worker_main() -> None:
    """The worker's loop: one request, one reply, until its stdin closes."""
    from .env import Code, set_env_provider
    from .env import lock_hash, platform_tag
    from .ledger import Ledger
    from .rev import Ref

    proto_in = sys.stdin.buffer
    proto_out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    ledger = Ledger(os.environ["DAT_LEDGER"])
    scratch = Path(os.environ.get("DAT_SCRATCH") or os.getcwd())
    while True:
        try:
            req = recv(proto_in)
        except EOFError:
            return
        try:
            code = {r: Code(v, c, d, Path(p) if p else None) for r, (v, c, d, p) in req["env"].items()}
            env = Env(code, lock_hash(), platform_tag())
            set_env_provider(lambda env=env: env)
            plain = ledger.at(req["rev"])
            mounts, _rows = mounts_for(plain, env)
            install_worker(ledger, mounts, scratch)
            purge_mounted()
            keys = {k: (Ref(ledger.at(), v[1]) if isinstance(v, tuple) and len(v) == 2 and v[0] == "__ref__" else v)
                    for k, v in req["keys"].items()}
            fn = plain.load_fn(req["name"])
            kw = fn._bind(keys)
            value = run_here(fn, plain, kw, _enc(kw), req["seal"])
            if req["seal"]:
                send(proto_out, {"ok": True, "subject": value.subject})
            else:
                value.__dict__.pop("_preds", None)
                send(proto_out, {"ok": True, "value": pickle.dumps(value)})
        except BaseException as e:  # noqa: BLE001 - every failure goes back to the parent
            try:
                blob = pickle.dumps(e)
            except Exception:
                blob = None
            send(proto_out, {"ok": False, "exc": blob, "type": type(e).__name__, "message": str(e),
                             "traceback": traceback.format_exc()})


def _enc(keys: Dict[str, Any]) -> str:
    from .codec import canonical
    from .fn import encode_keys

    return canonical(encode_keys(keys))


_ = returns_class
