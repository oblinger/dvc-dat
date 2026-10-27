"""The ledger's namespace: a dotted name resolved through the ``db/mount`` rows at a revision (DAT 1046).

``resolve_name(rev, name)`` is ``rev.resolve(name)``. The ``db/mount/<prefix>``
rows as of the rev are walked longest prefix first; under a mount the name is a
path in the mount's tree in the checkout discovery reports for its ``db/repo``:
a ``.yaml``/``.yml``/``.json`` file is read and comes back a dict (a dotted
tail below the file walks into it); a function in a ``.py`` file comes back its
``Fn``, read off the file and never imported here, its ``kind`` the decorator
(``@ledger_fn``: a ledger function; none: a dat's run function); a module-level
literal (``NAME = {...}``) its value. A name under no mount is imported, and a
``@ledger_fn`` it imports to comes back its ``Fn``, an undecorated function
itself.

``LedgerDo`` is ``Dat.manager.do`` in a project whose ``.datconfig.yaml`` names
a ledger: the ``Do`` interface (``load``, ``merge_bases``, ``{}`` expansion, the
``dat.do`` lookup in ``execute``) answered from these mounts, at the head, or at
the rev it was made for. Its ``mount`` is refused: in a ledger project the mounts
are rows.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Tuple, Union

import yaml

from ..do import Do
from .errors import NotEvaluated
from .fn import Fn, installed_fn, mounts_at

if TYPE_CHECKING:
    from .rev import Rev

DATA_SUFFIXES = (".yaml", ".yml", ".json")


def resolve_name(rev: "Rev", name: str) -> Any:
    """What the dotted ``name`` denotes at ``rev``: a dict, an ``Fn``, a literal, or the imported object."""
    if not isinstance(name, str) or not name or not all(name.split(".")):
        raise ImportError(f"{name!r} is not a dotted name")
    plain = rev._plain()
    for prefix, info in sorted(mounts_at(plain).items(), key=lambda kv: -len(kv[0])):
        if name == prefix or name.startswith(prefix + "."):
            return _mounted(rev, name, prefix, info)
    obj = Do._load_static(name)
    if callable(obj) and getattr(obj, "__ledger_fn__", False):
        return installed_fn(rev, name, obj)
    return obj


def mount_root(name: str, prefix: str, info: Dict[str, str]) -> Path:
    """The mount's tree in this environment's checkout of its repo; ``NotEvaluated`` with none."""
    from .env import current_env

    repo = info.get("repo")
    code = current_env().code.get(repo or "")
    if code is None or code.path is None:
        raise NotEvaluated(f"{name!r} is under the mount {prefix!r} of repo {repo!r}, which has no checkout in "
                           "this environment")
    return Path(code.path) / info["root"]


def _mounted(rev: "Rev", name: str, prefix: str, info: Dict[str, str]) -> Any:
    from .sandbox import load_sandboxed, unguarded

    rest = name[len(prefix) + 1:].split(".") if name != prefix else []
    with unguarded():                       # the ledger's own reads, also inside a sandboxed body
        root = mount_root(name, prefix, info)
        for cut in range(len(rest), -1, -1):
            base = root.joinpath(*rest[:cut])
            tail = rest[cut:]
            data = [base.with_suffix(s) for s in DATA_SUFFIXES if cut and base.with_suffix(s).is_file()]
            py = base / "__init__.py" if (base / "__init__.py").is_file() else (
                base.with_suffix(".py") if cut and base.with_suffix(".py").is_file() else None)
            if len(data) + (py is not None) > 1:
                raise KeyError(f"{name!r}: {', '.join(str(f) for f in data + ([py] if py else []))} "
                               "all answer to it")
            if data:
                text = data[0].read_text()
                value = json.loads(text) if data[0].suffix == ".json" else yaml.safe_load(text)
                return _walk(value, tail, name, data[0])
            if py is None:
                continue
            if not tail:
                raise ImportError(f"{name!r} is the module {py}; a name resolves to a spec, a function or "
                                  "a value in it")
            node = _top_level(py, tail[0])
            modname = ".".join([prefix, *rest[:cut]])
            if isinstance(node, ast.FunctionDef):
                if len(tail) > 1:
                    raise KeyError(f"{name!r}: {modname}.{tail[0]} is a function")
                break
            if node is None:
                raise ImportError(f"{name!r}: no {tail[0]!r} in {py}")
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                try:
                    value = ast.literal_eval(node.value)
                except ValueError:
                    raise TypeError(f"{name!r}: {modname}.{tail[0]} in {py} is not a literal; a mounted module "
                                    "is never imported here, so a value in it is a literal") from None
                return _walk(value, tail[1:], name, py)
            raise TypeError(f"{name!r}: {modname}.{tail[0]} in {py} is not a function or a literal")
        else:
            raise ImportError(f"{name!r}: nothing answers to it under the mount {prefix!r} ({root})")
    return load_sandboxed(rev, f"{modname}.{tail[0]}", prefix, info)


def _top_level(py: Path, attr: str) -> Optional[ast.AST]:
    """The module-level function or assignment binding ``attr`` in ``py`` (the last one), else ``None``."""
    found = None
    for node in ast.parse(py.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == attr:
            found = node
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == attr for t in node.targets):
            found = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == attr:
            found = node
    return found


def _walk(value: Any, tail: List[str], name: str, source: Path) -> Any:
    for i, k in enumerate(tail):
        if not isinstance(value, dict) or k not in value:
            raise KeyError(f"{name!r}: {'.'.join(tail[:i + 1])!r} is missing from {source}")
        value = value[k]
    return value


def mounted_commands(rev: "Rev") -> Iterator[Tuple[str, Dict[str, str], Path]]:
    """``(dotted name, decl, file)`` of every function marked ``@command(args=..., help=...)`` and every
    spec with a ``command:`` key in the mounted trees, read off the files (nothing imported)."""
    from ..just import _check, declared
    from .sandbox import unguarded

    plain = rev._plain()
    with unguarded():
        for prefix, info in sorted(mounts_at(plain).items()):
            try:
                root = mount_root(prefix, prefix, info)
            except NotEvaluated:
                continue
            for data in sorted(f for s in DATA_SUFFIXES for f in root.rglob("*" + s)):
                name = ".".join([prefix, *data.relative_to(root).with_suffix("").parts])
                try:
                    text = data.read_text()
                    spec = json.loads(text) if data.suffix == ".json" else yaml.safe_load(text)
                except (OSError, ValueError, yaml.YAMLError):
                    continue
                if isinstance(spec, dict) and spec.get("command") and (decl := declared(spec, name)):
                    yield name, decl, data
            for py in sorted(root.rglob("*.py")):
                rel = py.relative_to(root).with_suffix("").parts
                rel = rel[:-1] if rel and rel[-1] == "__init__" else rel
                modname = ".".join([prefix, *rel])
                try:
                    tree = ast.parse(py.read_text())
                except (OSError, SyntaxError):
                    continue
                for node in tree.body:
                    if not isinstance(node, ast.FunctionDef):
                        continue
                    for d in node.decorator_list:
                        f = d.func if isinstance(d, ast.Call) else None
                        if f is None or not ((isinstance(f, ast.Name) and f.id == "command")
                                             or (isinstance(f, ast.Attribute) and f.attr == "command")):
                            continue
                        kw = {k.arg: k.value for k in d.keywords if k.arg in ("args", "help")}
                        target = f"{modname}.{node.name}"
                        try:
                            decl = {k: ast.literal_eval(v) for k, v in kw.items()}
                            args, help = _check(decl.get("args", ""), decl.get("help", ""), target)
                        except (ValueError, TypeError):
                            continue                # not a literal, or refused at decoration anyway
                        yield target, {"args": args, "help": help}, py


class LedgerDo(Do):
    """``Dat.manager.do`` in a ledger project (DAT 1046): names resolve through the ledger's mounts.

    Bound to ``rev`` when given, else to the head of ``ledger`` (opened on first use from ``config``,
    the ``.datconfig.yaml`` naming it, as ``just run`` opens it). ``load`` is ``Do.load`` with the
    ledger's namespace (``resolve_name``) where a plain ``Do`` imports; ``mount`` is refused."""

    def __init__(self, ledger: Any = None, *, rev: Optional["Rev"] = None,
                 config: Union[str, Path, None] = None, manager: Any = None) -> None:
        super().__init__(manager)
        self._ledger = ledger
        self._rev = rev
        self._config = config

    def __repr__(self) -> str:
        where = f"rev {self._rev.id}" if self._rev is not None else (
            repr(self._ledger) if self._ledger is not None else str(self._config))
        return f"<LedgerDo {where}>"

    def rev(self) -> "Rev":
        """The revision names resolve at: the one it was made for, else the ledger's head now."""
        if self._rev is not None:
            return self._rev
        if self._ledger is None:
            from ..do import _ledger_of

            self._ledger = _ledger_of(self._config)
            if self._ledger is None:
                raise RuntimeError(f"{self._config}: names no ledger")
        return self._ledger.at()

    def _load_unmounted(self, dotted_name: str) -> Any:
        return resolve_name(self.rev(), dotted_name)

    def mount(self, **kwargs: Any) -> None:  # type: ignore[override]
        raise TypeError("a ledger project names things through its db/mount rows (`mounts:` in "
                        ".datconfig.yaml, or t.add('db/mount/<prefix>', 'db/root', ...)); Dat.do.mount is "
                        "the namespace of a project with no ledger")

    def keys(self) -> List[str]:  # type: ignore[override]
        """The manager's own names and the ledger's mount prefixes."""
        return sorted(set(super().keys()) | set(mounts_at(self.rev()._plain())))

    def _commands(self) -> List[Tuple[str, Dict[str, str], Path]]:
        """The ``@command`` functions in the mounted trees (``just.commands``)."""
        return list(mounted_commands(self.rev()))


__all__ = ["LedgerDo", "resolve_name", "mounted_commands"]
