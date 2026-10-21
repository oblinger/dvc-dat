"""Sandbox mode: a function under a ``db/mount/<prefix>`` row, loaded from the mounted tree, run in a process of its own.

Parent side (``load_sandboxed``, ``run_sandboxed``): the name resolves through
the mounts as of the rev to a file under ``<checkout>/<db/root>``, the checkout
being what discovery reports for the mount's ``db/repo`` (A40); no checkout is
``NotEvaluated`` naming the repo. A miss runs at HEAD, clean or dirty (Q39 (A));
``clean=True`` asks for a clean checkout at the rev's commit (``fn.check_clean``).
It runs in a fresh process forked for the one call from a warm server, one per
environment (the interpreter): the server is started ``python -I`` (the
standard library, ``site-packages`` and nothing else on its path), imports the
ledger's machinery and no mounted module, never initialises CUDA, and forks a
child per request. The child opens the request's ledger (A44), runs the call,
seals the entry itself and hands back its subject; an exception comes back
with the child's traceback, nothing sealed; the child then exits, so nothing a
body loaded or changed outlives its call.

Child side (``worker.py`` drives the server): ``MountFinder``, first on
``sys.meta_path``, loads a mounted prefix from its root, gives the prefix's
ancestors empty namespace packages (their ``__init__`` never runs), and refuses
a module that would resolve inside a mounted repo's checkout but under no mount
(``UnmountedImport``). An audit hook refuses, while a function body (or its
module's load) runs, a read (``open``, ``os.listdir``/``scandir``) outside
the mounted roots, the art store (the dats) and the body's ``work`` folder
(``UntracedRead``), except the import system's own reads of module files and,
while a module from outside the mounts is being imported, its reads in the
interpreter's folders (its bundled data); and a write anywhere but the running
body's ``work`` folder, the dat being produced
(``ConfinedWrite``): ``open``/``os.open`` for writing, every path-changing
``os`` call (mkdir, rename, link, remove, chmod, ...), and through them
``pathlib``, ``shutil``, ``tempfile`` and ``sqlite3``. The ledger's own
writes inside a body (a nested eval's seal, a dat materialised into the art
store) run ``unguarded``. The same hook refuses a host-name lookup or an internet
send (``ConfinedNetwork``), except to a Postgres ledger's own endpoint.
A nested eval runs in-process and its loads count toward its own entry (Q37 (ii)).

The ``fn`` item (Q37 (A); Dan 2026-10-21): exactly the modules the run loaded,
hashed with the mount rows into ``db/fn/<name>/<hash>``. A mounted module (and
the static import closure of the function's module) is ``relpath -> sha256`` of
the file as read; a third-party one is ``dist:<name> -> <version>:<sha256 of its
RECORD>`` when its distribution has a ``RECORD``, else ``py:<path under its
sys.path entry> -> sha256`` of the file (the standard library, an editable
source). dvc-dat and what the server holds before the fork (the standard
library pieces the ledger uses, pyyaml) are infrastructure, like dvc-dat (A56).
A lookup re-hashes exactly those: a mounted file at the rev's ``code/<repo>``
commit when it binds one other than HEAD, else on disk; a third-party one as
installed now. Any byte changed in a loaded module is a different entry.
``Fn.subject`` before any run is the static closure.
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
import re
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Set, Tuple

from .codec import sha256
from .env import Env, current_env
from .errors import ConfinedNetwork, ConfinedWrite, NotEvaluated, UnmountedImport, UntracedRead
from .fn import Fn, drop_work, fn_subject, mounts_at, mounts_hash, path_template, seal_entry, wrap_result

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


def _scoped_imports(path: Path, dotted: str, is_pkg: bool, func: Optional[str]) -> Set[str]:
    """The imports a module runs on load (module and class bodies), plus those in the body of ``func``."""
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return set()
    out: Set[str] = set()

    def visit(node: Any) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node is tree and child.name == func:
                    for n in ast.walk(child):
                        if isinstance(n, (ast.Import, ast.ImportFrom)):
                            out.update(_imports_of_node(n, dotted, is_pkg))
                continue
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                out.update(_imports_of_node(child, dotted, is_pkg))
            visit(child)
    visit(tree)
    return out


def _imports_of_node(node: Any, dotted: str, is_pkg: bool) -> Set[str]:
    pkg = dotted if is_pkg else dotted.rpartition(".")[0]
    out: Set[str] = set()
    if isinstance(node, ast.Import):
        for a in node.names:
            parts = a.name.split(".")
            out.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))
    else:
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


def check_mounted_imports(mounts: List[Mount], modname: str, func: str) -> None:
    """At load (Module § load_fn): ``UnmountedImport`` when the function's module, or a mounted module it
    reaches on load, imports a repo module under no mount. The worker's finder still checks at run time."""
    todo: List[Tuple[str, Optional[str]]] = [(modname, func)]
    seen: Set[str] = set()
    while todo:
        d, fname = todo.pop()
        if d in seen:
            continue
        seen.add(d)
        m = _mount_of(mounts, d)
        f = m.file_of(d) if m is not None else None
        if f is None:
            continue
        for imp in sorted(_scoped_imports(f[0], d, f[1], fname)):
            if _mount_of(mounts, imp) is not None:
                todo.append((imp, None))
                continue
            if any(mm.prefix.startswith(imp + ".") for mm in mounts):
                continue
            for mm in mounts:
                base = mm.checkout.joinpath(*imp.split("."))
                if base.with_suffix(".py").is_file() or (base / "__init__.py").is_file():
                    raise UnmountedImport(f"{imp} from {d}; mount it or move it")


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


def static_closure(root: Path, start: str, within: Path) -> Dict[str, Path]:
    """Base mode (Q37 (iii)): every module under ``within`` reachable from ``start`` by import statements,
    resolving a dotted name under ``root`` (the ``sys.path`` entry the start module was imported from)."""
    within = Path(os.path.realpath(within))
    seen: Dict[str, Path] = {}
    todo = [start]
    while todo:
        d = todo.pop()
        if d in seen:
            continue
        base = Path(root).joinpath(*d.split("."))
        f, pkg = (base / "__init__.py", True) if (base / "__init__.py").is_file() else (base.with_suffix(".py"), False)
        if not f.is_file() or not os.path.realpath(f).startswith(str(within) + os.sep):
            continue
        seen[d] = f
        todo.extend(_imports(f, d, pkg))
    return seen


def module_shas(rev: "Rev", env: Env, mods: Dict[str, Tuple[Mount, Path]], at_rev: bool = True) -> Dict[str, str]:
    """``relpath -> sha256`` of mounted modules: at the rev's commit (a lookup), or on disk, as read (a run)."""
    out = {}
    for _d, (m, path) in mods.items():
        rel = path.relative_to(m.checkout).as_posix()
        out[rel] = file_sha(m.checkout, rel, _commit_for(rev, m.repo, env) if at_rev else None)
    return dict(sorted(out.items()))


# -- third-party modules: by distribution RECORD, else by file bytes ------------------------------------

_SHAS: Dict[Tuple[str, int, int], str] = {}
_DISTS: Optional[Dict[Tuple[str, str], Tuple[str, str]]] = None


def _bytes_sha(path: str) -> str:
    """sha256 of a file, cached by (path, mtime, size); ``<missing>`` when it is not there."""
    try:
        st = os.stat(path)
    except OSError:
        return "<missing>"
    key = (path, st.st_mtime_ns, st.st_size)
    if key not in _SHAS:
        with open(path, "rb") as f:
            _SHAS[key] = sha256(f.read())
    return _SHAS[key]


def _path_roots() -> List[str]:
    """``sys.path`` folders, real, longest first (the innermost entry holding a file names it)."""
    roots = {os.path.realpath(p) for p in sys.path if p and os.path.isdir(p)}
    return sorted(roots, key=len, reverse=True)


def _dist_record(dist: Any) -> Optional[str]:
    text = dist.read_text("RECORD")
    return None if text is None else f"{dist.version}:{sha256(text.encode())}"


def _dist_map() -> Dict[Tuple[str, str], Tuple[str, str]]:
    """``(site folder, top-level name) -> (dist:<name>, <version>:<RECORD sha>)`` for every installed
    distribution whose ``RECORD`` lists its files (an editable install lists none of its sources)."""
    global _DISTS
    if _DISTS is None:
        import importlib.metadata as md

        out: Dict[Tuple[str, str], Tuple[str, str]] = {}
        for dist in md.distributions():
            try:
                rec = _dist_record(dist)
                files = dist.files or []
                site = os.path.realpath(str(dist.locate_file("")))
            except Exception:                   # a broken install names nothing
                continue
            name = re.sub(r"[-_.]+", "-", (dist.metadata["Name"] or "")).lower()
            if rec is None or not name:
                continue
            for f in files:
                top = f.parts[0] if f.parts else ""
                if top and top != ".." and not top.endswith((".dist-info", ".data", ".pth")) \
                        and top != "__pycache__":
                    out.setdefault((site, top), (f"dist:{name}", rec))
        _DISTS = out
    return _DISTS


def third_party_items(names: Set[str]) -> Dict[str, str]:
    """The ``fn`` items of the non-mounted modules ``names`` (dvc-dat itself excluded, A56)."""
    roots = _path_roots()
    dists = _dist_map()
    out: Dict[str, str] = {}
    for name in sorted(names):
        if name == "dvc_dat" or name.startswith("dvc_dat.") or _mount_of(STATE.mounts, name) is not None:
            continue
        f = getattr(sys.modules.get(name), "__file__", None)
        if not f:
            continue                            # built in, frozen, a namespace: the interpreter's
        real = os.path.realpath(f)
        root = next((r for r in roots if real.startswith(r + os.sep)), None)
        if root is None:
            continue
        rel = Path(os.path.relpath(real, root)).as_posix()
        hit = dists.get((root, rel.split("/")[0]))
        if hit is not None:
            out[hit[0]] = hit[1]
        else:
            out["py:" + rel] = _bytes_sha(real)
    return out


def third_party_now(key: str) -> str:
    """A recorded third-party item's value as installed now (``<missing>`` when it is gone)."""
    if key.startswith("dist:"):
        import importlib.metadata as md

        try:
            rec = _dist_record(md.distribution(key[len("dist:"):]))
        except md.PackageNotFoundError:
            return "<missing>"
        return rec or "<missing>"
    rel = key[len("py:"):]
    for root in [p for p in sys.path if p and os.path.isdir(p)]:
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            return _bytes_sha(os.path.realpath(p))
    return "<missing>"


def _signature(fdef: ast.FunctionDef, name: str) -> Tuple[inspect.Signature, bool, Optional[str], str, bool]:
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
    folder = next((p for p in rest if p.name == "path"), None)
    keep = [p for p in rest if p.name != "path"]
    template = path_template(folder.default) if folder is not None else None
    decorated = any((isinstance(d, ast.Name) and d.id == "ledger_fn")
                    or (isinstance(d, ast.Attribute) and d.attr == "ledger_fn") for d in fdef.decorator_list)
    returns = ast.unparse(fdef.returns) if fdef.returns is not None else ""
    return inspect.Signature(keep), folder is not None, template, returns, decorated


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
    sig, takes_path, template, returns, decorated = _signature(fdef, name)
    if not decorated:
        raise TypeError(f"{name!r} is not a ledger function (mark it @ledger_fn)")
    check_mounted_imports(mounts, modname, attr_name)
    mods = module_shas(plain, env, closure(mounts, [modname]))
    rel = f[0].relative_to(m.checkout).as_posix()
    return Fn(name=name, module=f[0], sha=file_sha(m.checkout, rel, _commit_for(plain, m.repo, env)),
              mode="sandbox", mount=m.prefix, signature=sig, env=Env(env.code, env.platform, mounts_hash(plain)),
              subject=fn_subject(name, mods, mounts_hash(plain)), _rev=rev, _takes_path=takes_path,
              _template=template, _modules=mods, _returns=returns,
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
    now = {rel: third_party_now(rel) if rel.startswith(("dist:", "py:")) else file_sha(m.checkout, rel, commit)
           for rel in modules}
    return fn_subject(name, dict(sorted(now.items())), mounts_hash(plain))


def run_sandboxed(fn: Fn, plain: "Rev", kw: Dict[str, Any], enc: str, seal: bool) -> Any:
    """A miss: at HEAD, clean or dirty (Q39 (A)); the ``fn`` item records the bytes it loaded."""
    env = current_env()
    if fn._info["repo"] not in env.code:
        raise NotEvaluated(f"{fn.name}: repo {fn._info['repo']!r} has no checkout in this environment")
    if IN_WORKER:
        return run_here(fn, plain, kw, enc, seal)
    return _server().call(fn, plain, kw, seal, env)


# -- the worker's own machinery -----------------------------------------------------------------------

class _Frame:
    """One running body: the modules present when it started, and those a nested body claimed."""

    def __init__(self) -> None:
        self.before: Set[str] = set(sys.modules)
        self.claimed: Set[str] = set()


class _State:
    mounts: List[Mount] = []
    frames: List[_Frame] = []
    guard = False
    reads: List[str] = []                           # the mounted roots and the art store (the dats)
    importable: List[str] = []                      # sys.path and the mounts: where the import system reads
    interpreter: List[str] = []                     # where an unmounted module's own import may read
    works: List[Optional[str]] = []                 # the work folder of each running body, innermost last
    store: str = ""                                 # the ledger's own database file (a folder ledger)
    hosts: Set[str] = set()                         # the ledger's own endpoint, by name and by address
    addrs: Set[Tuple[str, int]] = set()


STATE = _State()


@contextmanager
def unguarded() -> Iterator[None]:
    """The ledger's own machinery inside a body (a nested eval, a dat materialised into the art store):
    its reads and writes are the view's, not the function's, so the open hook stands aside for it."""
    old = STATE.guard
    STATE.guard = False
    try:
        yield
    finally:
        STATE.guard = old


def _importer() -> str:
    for fr in inspect.stack()[2:]:
        name = fr.frame.f_globals.get("__name__", "")
        if not name.startswith(("importlib", "dvc_dat.ledger.sandbox")) and name != "<frozen importlib._bootstrap>":
            return name
    return "?"


class MountFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        m = _mount_of(STATE.mounts, fullname)
        if m is not None:
            f = m.file_of(fullname)
            if f is None:
                d = m.path.joinpath(*fullname[len(m.prefix):].lstrip(".").split(".")) \
                    if fullname != m.prefix else m.path
                if not d.is_dir():
                    return None
                spec = importlib.machinery.ModuleSpec(fullname, None, is_package=True)
                spec.submodule_search_locations = [str(d)]    # a root with no __init__.py: a namespace
                return spec
            loader = importlib.machinery.SourceFileLoader(fullname, str(f[0]))
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


def _interpreter_roots() -> List[str]:
    """The interpreter's own folders: the prefixes, the standard library and ``site-packages``."""
    import sysconfig

    roots = {sys.prefix, sys.base_prefix, sys.exec_prefix}
    for k in ("stdlib", "platstdlib", "purelib", "platlib"):
        p = sysconfig.get_paths().get(k)
        if p:
            roots.add(p)
    return [os.path.realpath(r) for r in roots]


def _under(p: str, roots: List[str]) -> bool:
    return any(p == r or p.startswith(r + os.sep) for r in roots)


_NET_NAME = ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo")
_NET_SEND = ("socket.connect", "socket.sendto", "socket.sendmsg")


def _ledger_endpoints(path: Any) -> Tuple[Set[str], Set[Tuple[str, int]]]:
    """The hosts and ``(address, port)`` pairs a Postgres ledger's DSN names (none for a folder ledger)."""
    from urllib.parse import urlsplit

    text = str(path)
    if not text.startswith(("postgres://", "postgresql://")):
        return set(), set()
    netloc = re.split(r"[/?]", text.partition("://")[2], maxsplit=1)[0].rpartition("@")[2]
    hosts, addrs = set(), set()
    for part in netloc.split(","):
        u = urlsplit("//" + part)
        host, port = u.hostname or "localhost", u.port or 5432
        hosts.add(host)
        try:
            for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP):
                addrs.add((str(info[4][0]), int(info[4][1])))
        except OSError:
            pass                                    # unresolvable now: the ledger itself will say so
    return hosts, addrs


def _network(event: str, args: Any) -> None:
    if event in _NET_NAME:
        host = args[0]
        host = host[0] if event == "socket.getnameinfo" and isinstance(host, tuple) else host
        if isinstance(host, bytes):
            host = host.decode(errors="replace")
        if host is not None and host not in STATE.hosts and not any(host == a for a, _p in STATE.addrs):
            raise ConfinedNetwork(f"{host}: a sandboxed function does not use the network")
        return
    sock, addr = args[0], args[1]
    if getattr(sock, "family", None) not in (socket.AF_INET, socket.AF_INET6) or not isinstance(addr, tuple):
        return                                      # a local (AF_UNIX) socket is not the network
    if (str(addr[0]), int(addr[1])) not in STATE.addrs:
        raise ConfinedNetwork(f"{addr[0]}:{addr[1]}: a sandboxed function does not use the network")


_OS_READS = ("os.listdir", "os.scandir", "os.listxattr", "os.getxattr")
_DEV_NULL = [os.path.realpath(os.devnull)]
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC
# the path-changing os events: each written path's argument index, and its dir_fd's (None: takes none)
_OS_WRITES: Dict[str, Tuple[Tuple[int, Optional[int]], ...]] = {
    "os.mkdir": ((0, 2),), "os.rmdir": ((0, 1),), "os.remove": ((0, 1),),
    "os.rename": ((0, 2), (1, 3)), "os.link": ((0, 2), (1, 3)), "os.symlink": ((1, 2),),
    "os.chmod": ((0, 2),), "os.chown": ((0, 3),), "os.utime": ((0, 3),), "os.truncate": ((0, None),),
    "os.chflags": ((0, None),), "os.lchflags": ((0, None),), "os.setxattr": ((0, None),),
    "os.removexattr": ((0, None),),
    "shutil.rmtree": ((0, 1),), "shutil.move": ((0, None), (1, None)), "shutil.copytree": ((1, None),),
    "shutil.copyfile": ((1, None),),            # these four only name the target first; os.* events follow
}


def _fd_path(fd: int) -> Optional[str]:
    """The path an open descriptor names, or ``None`` for one that is no file (a pipe, a socket)."""
    try:
        if sys.platform == "darwin":
            import fcntl

            return os.fsdecode(fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0")) or None
        return os.readlink(f"/proc/self/fd/{fd}")
    except (OSError, ValueError):
        return None


def _resolve(path: Any, dir_fd: Any = None) -> Optional[str]:
    """The real path an audited argument names: a path (relative to ``dir_fd`` when one is given, else to
    the working directory) or a descriptor; ``None`` when it names no file."""
    if isinstance(path, int):
        return _fd_path(path)
    if not isinstance(path, (str, bytes, os.PathLike)):
        return None
    text = os.fsdecode(os.fspath(path))
    if isinstance(dir_fd, int) and dir_fd >= 0 and not os.path.isabs(text):
        base = _fd_path(dir_fd)
        if base is None:
            raise ConfinedWrite(f"{text} under descriptor {dir_fd}: a sandboxed function writes only in its "
                                "work folder")
        text = os.path.join(base, text)
    return os.path.realpath(text)


def _writable() -> List[str]:
    work = STATE.works[-1] if STATE.works else None
    return ([work] if work else []) + _DEV_NULL


def _check_write(p: Optional[str]) -> None:
    if p is not None and not _under(p, _writable()):
        raise ConfinedWrite(f"{p}: a sandboxed function writes only in its work folder")


def _audit(event: str, args: Any) -> None:
    if not STATE.guard:
        return
    if event in _NET_NAME or event in _NET_SEND:
        _network(event, args)
        return
    if event in _OS_WRITES:
        for i, d in _OS_WRITES[event]:
            _check_write(_resolve(args[i], args[d] if d is not None and d < len(args) else None))
        return
    if event == "sqlite3.connect":
        db = os.fsdecode(os.fspath(args[0])) if isinstance(args[0], (str, bytes, os.PathLike)) else ""
        db = db[5:].partition("?")[0] if db.startswith("file:") else db
        if db and db != ":memory:" and os.path.realpath(db) != STATE.store:
            _check_write(os.path.realpath(db))
        return
    if event in _OS_READS:
        _check_read(_resolve(args[0] if args and args[0] is not None else "."), sys._getframe(1))
        return
    if event != "open":
        return
    path, mode, flags = (list(args) + [None, None, None])[:3]
    if not isinstance(path, (str, bytes, os.PathLike)):
        return                                      # a descriptor, opened (and checked) already
    p = os.path.realpath(os.fsdecode(os.fspath(path)))
    write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
        isinstance(flags, int) and flags & _WRITE_FLAGS)
    if write:
        _check_write(p)
        return
    _check_read(p, sys._getframe(1))


def _importing(frame: Any) -> Optional[str]:
    """The module whose import is running at ``frame`` (the innermost module body the import system
    called), or ``None`` outside any import."""
    f = frame
    while f is not None:
        if f.f_code.co_name == "<module>" and f.f_back is not None \
                and f.f_back.f_code.co_filename.startswith("<frozen importlib"):
            return str(f.f_globals.get("__name__", ""))
        f = f.f_back
    return None


def _check_read(p: Optional[str], caller: Any) -> None:
    """Reads: the mounts, the dats, the running body's work folder; the import system's own reads of
    module files; and, while a module from outside the mounts is being imported, the interpreter's
    folders (that module's data; the module itself is in ``fn``). Else ``UntracedRead``."""
    if p is None or _under(p, STATE.reads + _writable()):
        return
    if caller.f_code.co_filename.startswith("<frozen importlib") and _under(p, STATE.importable):
        return
    if _under(p, STATE.interpreter):
        mod = _importing(caller)
        if mod is not None and _mount_of(STATE.mounts, mod) is None:
            return
    raise UntracedRead(f"{p}: outside the mounts, the dats and the work folder")


def install_worker(ledger: Any, mounts: List[Mount]) -> None:
    global IN_WORKER
    IN_WORKER = True
    if not any(isinstance(f, MountFinder) for f in sys.meta_path):
        from . import trace  # noqa: F401  (a body's first traced read imports it; under the guard an
        #                    editable install's source folder is unreadable to the import system)
        sys.meta_path.insert(0, MountFinder())
        sys.addaudithook(_audit)
        tempfile.gettempdir()                       # probed unconfined, so a default temp file in a body is
                                                    # refused by name (ConfinedWrite), not "no usable dir"
    STATE.mounts = mounts
    roots = [os.path.realpath(m.path) for m in mounts]
    STATE.reads = roots + [os.path.realpath(ledger._store.art.root)]
    STATE.interpreter = _interpreter_roots()
    STATE.importable = roots + [os.path.realpath(p) for p in sys.path if p and os.path.isdir(p)]
    store = getattr(ledger._store, "path", None)
    STATE.store = os.path.realpath(store) if isinstance(store, Path) else ""
    STATE.hosts, STATE.addrs = _ledger_endpoints(ledger.path)


def run_here(fn: Fn, plain: "Rev", kw: Dict[str, Any], enc: str, seal: bool) -> Any:
    from .rev import Rev

    outer_guard = STATE.guard
    STATE.guard = False                             # around the body, the ledger's own machinery runs
    try:
        env = current_env()
        mounts, rows = mounts_for(plain, env)
        STATE.mounts = mounts
        modname, attr_name = fn._info["modname"], fn._info["attr"]
        work = Path(tempfile.mkdtemp(prefix="work-", dir=os.environ.get("DAT_SCRATCH") or None)) \
            if fn._takes_path else None
        STATE.frames.append(_Frame())
        STATE.works.append(os.path.realpath(work) if work is not None else None)
        rec: Dict[str, str] = {}
        cwd = os.getcwd()
        try:
            if work is not None:
                os.chdir(work)                      # a relative path resolves in the dat being produced
            STATE.guard = True                      # the module's own load is confined like the body
            try:
                obj = getattr(importlib.import_module(modname), attr_name)
                if not getattr(obj, "__ledger_fn__", False):
                    raise TypeError(f"{fn.name!r} is not a ledger function (mark it @ledger_fn)")
                args = dict(kw, path=work) if work is not None else kw
                out = obj(Rev(plain.ledger, plain.id, _rec=rec), **args)
            finally:
                STATE.guard = False
                os.chdir(cwd)
        except BaseException:
            drop_work(work, None)
            raise
        finally:
            frame = STATE.frames.pop()
            STATE.works.pop()
            new = set(sys.modules) - frame.before
            loaded = new - frame.claimed
            if STATE.frames:
                STATE.frames[-1].claimed |= new     # a nested body's loads are its own entry's (Q37 (ii))
        value = wrap_result(fn.name, obj, out)
        mounted = sorted(n for n in loaded if _mount_of(mounts, n) is not None)
        mods = module_shas(plain, env, closure(mounts, [modname, *mounted]), at_rev=False)
        mods = dict(sorted({**mods, **third_party_items(loaded)}.items()))
        fsub = fn_subject(fn.name, mods, mounts_hash(plain))
        trace = dict(rec)
        trace.update({"fn": fsub, "platform": env.platform})
        salt = rows.get(fn._info["prefix"], {}).get("salt")
        if salt is not None:
            trace["salt"] = salt
        if not seal:
            value.trace = trace  # type: ignore[misc]
            drop_work(work, value)
            return value
        sealed = seal_entry(fn, plain, value, trace, enc, "eval:sandbox", modules=mods)
        drop_work(work, sealed)
        return sealed
    finally:
        STATE.guard = outer_guard


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


class Server:
    """One warm ``python -I`` process per environment (the interpreter): it forks a fresh child per call."""

    def __init__(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="ledger-worker-"))
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "LANG", "CUDA_VISIBLE_DEVICES")}
        env["DAT_SCRATCH"] = str(self.scratch)
        self.proc = subprocess.Popen([sys.executable, "-I", "-m", "dvc_dat.ledger.worker"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, cwd=str(self.scratch), env=env)
        self.lock = threading.Lock()

    def alive(self) -> bool:
        return self.proc.poll() is None

    def call(self, fn: Fn, plain: "Rev", kw: Dict[str, Any], seal: bool, env: Env) -> Any:
        from .rev import Ref

        req = {"ledger": str(plain.ledger.path), "rev": plain.id, "name": fn.name,
               "keys": {k: encode_key(v) for k, v in kw.items()}, "seal": seal,
               "env": {r: (c.version, c.commit, c.dirty, str(c.path) if c.path else None) for r, c in env.code.items()}}
        with self.lock:
            send(self.proc.stdin, req)
            resp = recv(self.proc.stdout)
        if resp["ok"]:
            if seal:
                return Ref(plain.ledger.at(), resp["subject"]).load()
            v = pickle.loads(resp["value"])
            top = plain.ledger.at()
            v.__dict__["_preds"] = {k: _unship(top, x) for k, x in resp.get("preds", {}).items()}
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


_SERVERS: Dict[str, Server] = {}
_SERVERS_LOCK = threading.Lock()


def _server() -> Server:
    """The warm server of this environment (``sys.executable``), started on first use."""
    with _SERVERS_LOCK:
        s = _SERVERS.get(sys.executable)
        if s is None or not s.alive():
            s = _SERVERS[sys.executable] = Server()
        return s


def shutdown() -> None:
    """Stop every server (also run at exit)."""
    with _SERVERS_LOCK:
        for s in _SERVERS.values():
            s.close()
        _SERVERS.clear()


atexit.register(shutdown)


def _warm() -> None:
    """What every child shares, loaded once before any fork: the ledger's machinery (never a mounted
    module, never CUDA) and the installed distributions' map."""
    from . import kept, ledger, rev, store, trace, txn, value  # noqa: F401
    _dist_map()


def worker_main() -> None:
    """The server's loop: one request, one forked child, one reply, until its stdin closes."""
    proto_in = sys.stdin.buffer
    proto_out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    _warm()
    while True:
        try:
            req = recv(proto_in)
        except EOFError:
            return
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:                                # the child: one call, then gone
            os.close(r)
            status = 0
            try:
                with os.fdopen(w, "wb") as out:
                    serve(req, out)
            except BaseException:  # noqa: BLE001 - the parent reports a child that never replied
                status = 1
            finally:
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(status)
        os.close(w)
        with os.fdopen(r, "rb") as inp:
            try:
                resp = recv(inp)
            except (EOFError, pickle.UnpicklingError, struct.error):
                resp = None
        _pid, status = os.waitpid(pid, 0)
        if resp is None:
            resp = {"ok": False, "exc": None, "type": "WorkerDied",
                    "message": f"the sandboxed call's process ended (exit code "
                               f"{os.waitstatus_to_exitcode(status)}) before it replied",
                    "traceback": ""}
        send(proto_out, resp)


def serve(req: Dict[str, Any], out: Any) -> None:
    """In the forked child: confine this process, run the call, reply on ``out``."""
    from .env import Code, platform_tag, set_env_provider
    from .ledger import Ledger
    from .rev import Ref

    try:
        code = {r: Code(v, c, d, Path(p) if p else None) for r, (v, c, d, p) in req["env"].items()}
        env = Env(code, platform_tag())
        set_env_provider(lambda env=env: env)
        ledger = Ledger(req["ledger"])
        plain = ledger.at(req["rev"])
        mounts, _rows = mounts_for(plain, env)
        install_worker(ledger, mounts)
        keys = {k: (Ref(ledger.at(), v[1]) if isinstance(v, tuple) and len(v) == 2 and v[0] == "__ref__" else v)
                for k, v in req["keys"].items()}
        fn = plain.load_fn(req["name"])
        kw = fn._bind(keys)
        value = run_here(fn, plain, kw, _enc(kw), req["seal"])
        if req["seal"]:
            send(out, {"ok": True, "subject": value.subject})
        else:
            preds = {k: _ship(v) for k, v in value.__dict__.pop("_preds", {}).items()}
            send(out, {"ok": True, "value": pickle.dumps(value), "preds": preds})
    except BaseException as e:  # noqa: BLE001 - every failure goes back to the parent
        try:
            blob = pickle.dumps(e)
        except Exception:
            blob = None
        send(out, {"ok": False, "exc": blob, "type": type(e).__name__, "message": str(e),
                   "traceback": traceback.format_exc()})


def _ship(v: Any) -> Any:
    """A pred across the pipe: a sealed ``Value`` or a ``Ref`` by its subject (a Ref does not pickle)."""
    from .rev import Ref
    from .value import Value

    if isinstance(v, (list, tuple)):
        return [_ship(x) for x in v]
    if isinstance(v, Ref) or (isinstance(v, Value) and v.subject is not None):
        return ("__ref__", v.subject)
    return v


def _unship(top: "Rev", v: Any) -> Any:
    from .rev import Ref

    if isinstance(v, tuple) and len(v) == 2 and v[0] == "__ref__":
        return Ref(top, v[1])
    if isinstance(v, list):
        return [_unship(top, x) for x in v]
    return v


def _enc(keys: Dict[str, Any]) -> str:
    from .codec import canonical
    from .fn import encode_keys

    return canonical(encode_keys(keys))

