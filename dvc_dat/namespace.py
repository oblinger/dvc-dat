"""The namespace: `Namespace` maps dotted names to Python objects, with no Dat layer.

    ns.load("pkg.mod.fn")         # the object a dotted name imports to
    ns.name_of(obj)               # the dotted name that loads back to obj
    ns.mount(folder=..., at=...)  # add names to the namespace, in code
    ns.mounts()                   # the mount table: {prefix: location}
    ns.expand("runs/{YYYY}/{a.b}", k=v)  # a template filled through these names, a str

A dotted name is a mounted name, else exactly what `import` means in this environment, `getattr` below that.
Mounts are `ns.mount(...)` calls in the program; `.datconfig.yaml` holds none. Every `DatManager` builds its own
(`manager.ns`); `Dat.ns` (`dvc_dat.do.ns`) forwards to `Dat.manager.ns`. The ledger's `LedgerNamespace`
(`dvc_dat.ledger.namespace`) subclasses this one, which is why it lives outside `dvc_dat.do`: this module imports
neither `dvc_dat.core` nor `dvc_dat.do` at import (1519 R1); the parts that make a dat import `core` when used.
"""

import copy
import importlib.util
import json
import os
import re
import sys
from datetime import tzinfo
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple, Type, Union

import yaml

from .expand import expand, expand_spec, quote_spec
from .ledger.codec import dotted_get, dotted_set

if TYPE_CHECKING:
    from .core import Dat, DatManager

_DO_EXTENSIONS = [".json", ".yaml", ".py"]
_DO_ERROR_FLAG = tuple("multiple loadable modules have this same name")
_DO_NULL = tuple(["-no-value-"])
_MAIN = "__main__"

Spec = Dict[str, Any]


class Namespace:
    """A namespace, bound to the `DatManager` whose world it names.

    Every manager builds its own, reached as `manager.ns`; the module-level `ns`
    forwards to `Dat.manager.ns`.  A bare `Namespace()` is a plain namespace of Python
    objects: it mounts, loads and names with no manager at all.  It is not
    callable: running is `manager.run(target, ...)`, which loads names here.
    """

    _base_locations: Dict[str, str]
    _base_objects: Dict[str, Any]
    _registered_values: Optional[Dict[str, Any]]
    _manager: Optional["DatManager"]

    def __init__(self, manager: Optional["DatManager"] = None):
        self._base_objects = {}
        self._base_locations = {}
        self._registered_values = None
        self._manager = manager

    @property
    def manager(self) -> "DatManager":
        """The world this namespace belongs to; `RuntimeError` when it has none."""
        if self._manager is None:
            raise RuntimeError("this Namespace is a namespace with no manager, and running a "
                               "dat needs one: Namespace(manager=m), or "
                               "DatManager(dat_folders=[...], ns=this_ns)")
        return self._manager

    # -- forking (Dat.manager.run) ------------------------------------------

    @staticmethod
    def _fork_spec(spec: Spec, args: Iterable[Any] = (),
                  kwargs: Optional[Dict[str, Any]] = None) -> Spec:
        """A copy of `spec` with `args` as `dat.args` and `kwargs` merged into `dat.kwargs`.

        Call-site arguments are data (1467 Q2 (A)): their braces are escaped before the merge, so
        the spec's expansion at create hands the run exactly what was passed, while the spec's own
        template strings still expand."""
        spec = copy.deepcopy(spec)
        args = quote_spec(list(args))
        if args:
            dotted_set(spec, "dat.args", args)
        if kwargs:
            merged = dict(dotted_get(spec, "dat.kwargs", None) or {})
            merged.update(quote_spec(kwargs))
            dotted_set(spec, "dat.kwargs", merged)
        return spec

    def _dat_from_template(self, spec: Spec, *, path: Optional[str] = None,
                           manager: Optional["DatManager"] = None) -> Tuple["Dat", bool]:
        """Create the dat a template spec describes (see `DatManager.create`) in `manager`, the
        world running it (default this namespace's; one namespace may serve several worlds).

        Returns `(dat, skip_execution)`; `skip_execution` is True when
        `dat.target_exists: use` found the dat already there.
        """
        manager = manager or self.manager
        return manager._create(spec, path=path)

    # -- specs ---------------------------------------------------------------

    def _tz(self) -> Optional[tzinfo]:
        """The zone of the clock built-ins: `None`, the machine's local zone (a ledger namespace: its revision's display
        zone, `db db/timezone`)."""
        return None

    def expand(self, text: str, /, **vars: Any) -> str:
        """`text` with its `{}` references filled, always a str (doc/expand.md).

        `{name}` (undotted) is an expansion variable: a keyword of this call, else a built-in
        (`YYYY YY MM DD HH mm SS now cwd unique`, one moment in this namespace's zone); anything else
        is `KeyError`.  `{a.b}` (dotted) is `self.load("a.b")`, called when it is a function or
        method; `{a.b(1, k=2)}` calls it with those literals.  `{{` and `}}` are literal braces.
        Every reference must come back a str or a number; anything else is `TypeError` (the object
        a name refers to is `ns.load(name)`).  References do not nest: a lone `{` or `}` is
        `ValueError`.  `{unique}` is `""` here; a ledger namespace counts it."""
        return expand(text, vars, resolver=self.load, tz=self._tz())

    def expand_spec(self, spec: Any, /, **vars: Any) -> Any:
        """A copy of `spec` merged over its `dat.base` chain, every string value expanded.

        Expanded as `expand` does, keys left alone, the built-ins one moment. A string value that is exactly
        one reference is replaced by the object it names: `cfg: "{svp.defaults}"` inlines the dict. A spec
        that is not a dict has no bases and is only filled.
        """
        if isinstance(spec, dict):
            spec = self._merge_bases(copy.deepcopy(spec))
        return expand_spec(spec, vars, resolver=self.load, tz=self._tz())

    @staticmethod
    def quote_spec(spec: Any) -> Any:
        """A copy of `spec` that `expand_spec` turns back into `spec`: every brace in a string doubled."""
        return quote_spec(spec)


    def _merge_bases(self, spec: Union[Spec, str], _chain: Tuple[str, ...] = ()) -> Spec:
        """A spec (or the name of one) merged over its `dat.base` (a name, a spec, or a list of them, later
        entries winning), recursively; `dat.base` is dropped from the result so the
        stored spec is complete on its own."""
        if isinstance(spec, str):
            if spec in _chain:
                raise ValueError(f"dat.base: a cycle, {' -> '.join(_chain + (spec,))}")
            _chain = _chain + (spec,)
            spec = copy.deepcopy(self.load(spec))
        from .core import merge_dicts      # the merge is the Dat layer's: merging bases is making a dat

        base = dotted_get(spec, "dat.base", None)
        if not base:
            return spec
        bases = base if isinstance(base, list) else [base]
        merged: Spec = {}
        for entry in bases:
            merged = merge_dicts(merged, self._merge_bases(entry, _chain))
        result = merge_dicts(merged, spec)
        result["dat"].pop("base", None)
        return result

    # -- loading -------------------------------------------------------------

    def load(self, dotted_name: str, *, default: Any = _DO_NULL,
             kind: Optional[Type] = None) -> Any:
        """The object `dotted_name` names.

        Mounted names are checked first (values, modules, files, folders; a `.py`, `.yaml` or `.json` mount's contents
        as loaded, a string whose first line is `yaml` alone parsed as YAML); otherwise the longest importable prefix
        is imported and the rest is `getattr`. Dict results are deep copies.

        With nothing found the `ImportError`, `AttributeError` or `KeyError` propagates unless `default` is given,
        which is also returned for a `None` result. `kind` makes a result of another type `TypeError`.
        """
        try:
            result = self._load_mounted(dotted_name)
            if result is _DO_NULL:
                result = self._load_unmounted(dotted_name)
        except (ImportError, AttributeError, KeyError):
            if default is not _DO_NULL:
                return default
            raise
        if result is None and default is not _DO_NULL:
            return default
        if kind and not isinstance(result, kind):
            raise TypeError(f"ns.load: expected {dotted_name!r} of type {kind}, found {result!r}")
        return result

    def _load_mounted(self, dotted_name: str) -> Any:
        parts = dotted_name.split(".")
        file_base = parts[0]
        if self._registered_values:
            for cut in range(len(parts), 0, -1):   # the longest mounted prefix
                key = ".".join(parts[:cut])
                if (value := self._registered_values.get(key, _DO_NULL)) is _DO_NULL:
                    continue
                value = _parse_yaml_prefix(value)
                if cut < len(parts):
                    if not isinstance(value, dict):
                        raise KeyError(f"ns.load: {key!r} is a mounted value, "
                                       f"not a mapping; {dotted_name!r} is not in it")
                    value = _get_present(value, parts[cut:])
                    if value is _DO_NULL:
                        raise KeyError(f"ns.load: {'.'.join(parts[cut:])!r} "
                                       f"is missing from the value mounted at {key!r}")
                return copy.deepcopy(value) if isinstance(value, dict) else value
        # A folder mount indexes its files by path under `at`: `catalog/models/baseline` answers to
        # `catalog.models.baseline`; the longest such prefix wins, over a file named by the first part
        # alone (`train.yaml` does not hide `train/fast.yaml`).
        obj = None
        for cut in range(len(parts), 1, -1):
            key = "/".join(parts[:cut])
            if key in self._base_locations:
                obj = self._get_base(key)
                file_base, parts = key, [key] + parts[cut:]
                break
        if obj is None:
            obj = self._get_base(file_base, default=None)
        if obj is None:
            return _DO_NULL
        if obj == _DO_ERROR_FLAG:
            raise KeyError(f"ns.load: {file_base!r} is mounted more than once")
        elif isinstance(obj, ModuleType):
            if len(parts) < 2:
                result = getattr(obj, _MAIN, _DO_NULL)
            else:
                result = getattr(obj, parts[1], _DO_NULL)
                result = _get_present(result, parts[2:])
        elif len(parts) == 1:
            result = obj
        elif isinstance(obj, dict):
            result = _get_present(obj, parts[1:])
        else:
            raise KeyError(f"ns.load: illegal mounted value {obj!r} for {dotted_name}")
        if result is _DO_NULL:
            name = dotted_name[len(file_base) + 1:] or _MAIN
            source = obj.__file__ if isinstance(obj, ModuleType) else obj
            raise KeyError(f"ns.load: {name!r} is missing from {source!r}")
        result = _parse_yaml_prefix(result)
        return copy.deepcopy(result) if isinstance(result, dict) else result

    def _load_unmounted(self, dotted_name: str) -> Any:
        """A name no mount holds: imported (a `LedgerNamespace` walks the ledger's mounts first)."""
        return self._load_static(dotted_name)

    @staticmethod
    def _load_static(dotted_name: str) -> Any:
        """Import the longest importable prefix of `dotted_name`, then `getattr` the rest."""
        parts = dotted_name.split(".")
        if not all(parts):
            raise ImportError(f"ns.load: {dotted_name!r} is not a dotted name")
        for cut in range(len(parts), 0, -1):
            module_name = ".".join(parts[:cut])
            try:
                obj = import_module(module_name)
            except ModuleNotFoundError as e:
                if e.name and module_name.startswith(e.name):
                    continue  # this prefix does not exist; try a shorter one
                raise
            for attr in parts[cut:]:
                obj = getattr(obj, attr)
            return obj
        raise ImportError(f"ns.load: no importable prefix of {dotted_name!r}")

    @staticmethod
    def name_of(obj: Any) -> str:
        """The dotted `module.qualname` that `load` takes back to `obj` (a module, class or function).

        `ValueError` for an object with no importable name, such as a lambda or a function defined inside another.
        """
        if isinstance(obj, ModuleType):
            return obj.__name__
        module = getattr(obj, "__module__", None)
        qualname = getattr(obj, "__qualname__", None)
        if not module or not qualname or "<" in qualname:
            raise ValueError(f"ns.name_of: {obj!r} has no importable dotted name")
        return f"{module}.{qualname}"

    def mounts(self) -> Dict[str, str]:
        """The mount table: `{prefix: location}`, a mounted file, folder entry or module.

        Its import name when mounted as an object; a `value` mount (`mount(value=...)`) has no location and is not
        listed.
        """
        return {at: (self._base_objects[at].__name__ if loc == "--directly-assigned--" else loc)
                for at, loc in self._base_locations.items()}

    def _mounted_names(self) -> Iterable[str]:
        """Every mounted name, `mount(value=...)` ones included (the command line's `--list`, the just
        targets)."""
        values = [k for k in self._registered_values or () if k not in self._base_locations]
        return list(self._base_locations) + values

    def _resolve_dat_folder(self, name: str) -> Optional[str]:
        """The folder of a dat mounted as `<name>/_spec_`, else None."""
        spec_key = name + "/_spec_"
        if spec_key in self._base_locations:
            return os.path.dirname(self._base_locations[spec_key])
        return None

    # -- mounting ------------------------------------------------------------

    def mount(self, *,
              folder: Optional[str] = None,
              file: Optional[str] = None,
              module: Union[ModuleType, str, None] = None,
              value: Any = None,
              at: str = "",
              relative_to: str = "."):
        """Mount exactly one of a `folder`, a single `file`, a `module`, or a literal `value`, at `at`.

        A `module` is an object, import name or path. A `folder` is indexed by path under `at`, so
        `catalog/models/baseline` answers to `catalog.models.baseline`; folder and file paths join to `relative_to`.
        Mounts live in this namespace only; your program calls `mount` to add one name at a time.

        A mounted name never shadows an importable one: `mount` raises `ValueError` when a top-level name it would add
        -- `at`'s first part, or with no `at` each top-level file or folder of a mounted folder -- is a module or
        package Python can import from somewhere else. Mounting a module at its own name, or a folder that is itself
        the importable source, is not a clash. See [Mounts][mounts].
        """
        if 1 != sum(x is not None for x in (folder, file, module, value)):
            raise ValueError("mount: exactly one of 'folder', 'file', 'module' or 'value'")
        elif folder is not None:
            folder = os.path.join(relative_to, folder)
            index = _build_loadables_index(folder, at)
            tops = {_top_name(loc) for loc in index}
            for top in sorted(tops):
                _refuse_import_clash(top, "folder", folder, own=folder)
            for base, path in index.items():
                self._reg_module(base, path, allow_redefine=True)
        elif file is not None:
            path = os.path.join(relative_to, file)
            _refuse_import_clash(_top_name(at), "file", path, own=path)
            self._reg_module(at, path, allow_redefine=True)     # drops what an earlier mount cached
        elif module is not None:
            if isinstance(module, ModuleType):
                own = getattr(module, "__file__", None)
            elif "/" in module:
                own = module
            else:
                found = importlib.util.find_spec(module)
                own = found.origin if found else None
            if own and os.path.basename(own) == "__init__.py":
                own = os.path.dirname(own)          # a package: its folder is its own
            source = module.__name__ if isinstance(module, ModuleType) else module
            _refuse_import_clash(_top_name(at), "module", source, own=own)
            self._reg_module(at, module, allow_redefine=True)
        else:
            _refuse_import_clash(_top_name(at), "value", repr(value)[:60])
            self._base_locations.pop(at, None)
            self._base_objects.pop(at, None)
            self._reg_value(at, value)
        if value is None and self._registered_values:
            self._registered_values.pop(at, None)               # a remount replaces a value mounted there

    def _get_base(self, base: str, default: Any = _DO_NULL) -> Any:
        """The module or object mounted at base name `base`."""
        if base in self._base_objects:
            result = self._base_objects[base]
        elif base in self._base_locations:
            loc = self._base_locations[base]        # two files with one stem: the flag, refused by name
            self._base_objects[base] = loc if loc is _DO_ERROR_FLAG else _load_base_entity(base, loc)
            result = self._base_objects[base]
        elif default is _DO_NULL:
            raise KeyError(f"ns: base {base + '...'!r} is not mounted")
        else:
            result = default
        if isinstance(result, dict):
            result = copy.deepcopy(result)
        return result

    def _reg_module(self, at: str, module_spec: Union[str, ModuleType], *, allow_redefine=False):
        if (not allow_redefine and at in self._base_locations
                and self._base_locations[at] != module_spec):
            raise Exception(f"Base {at!r} is already defined")
        if isinstance(module_spec, ModuleType):
            self._base_locations[at] = "--directly-assigned--"
            self._base_objects[at] = module_spec
        else:
            self._base_locations[at] = module_spec
            self._base_objects.pop(at, None)

    def _reg_value(self, dotted_name: str, value: Any):
        if self._registered_values is None:
            self._registered_values = {}
        self._registered_values[dotted_name] = value


def _get_present(obj: Any, keys: List[str]) -> Any:
    """`obj` walked by `keys`; `_DO_NULL` when a key is missing -- a null in the file is `None`, not
    missing (`Dat.get` reads both as missing)."""
    for k in keys:
        if obj is _DO_NULL or obj is None:     # under a null, as under a missing key: missing
            return _DO_NULL
        if not isinstance(obj, dict):           # missing, as `default=` reads it (KeyError)
            raise KeyError(f"ns.load: {k!r} is not in {obj!r}, which is not a mapping")
        obj = obj.get(k, _DO_NULL)
    return obj


def _top_name(name: str) -> str:
    """The first part of a mounted name: `configs` for `configs/bb/base` or `configs.bb`."""
    return re.split(r"[./]", name, maxsplit=1)[0]


def _refuse_import_clash(top: str, kind: str, source: str, *, own: Optional[str] = None):
    """Raise if `top` is importable from outside `own` (the mounted file or folder).

    Both sides are compared as real paths, component by component: a symlinked
    mount of the importable source is its own, and `/x/configs2` is not inside
    `/x/configs`.
    """
    if not top:
        return
    try:
        spec = importlib.util.find_spec(top)
    except (ImportError, ValueError):
        spec = None
        if top in sys.modules:
            raise ValueError(f"mount: {top!r} is already an imported module; "
                             f"mount the {kind} {source!r} at another name")
    if spec is None or (spec.origin is None and top not in sys.modules):
        return      # nothing, or a bare folder on sys.path (a namespace package): no code to shadow
    places = [spec.origin] if spec.origin and spec.origin not in ("built-in", "frozen") else []
    places += list(spec.submodule_search_locations or [])
    if not places:  # a built-in module
        places = [spec.origin or "built-in"]
    if own:
        own = os.path.realpath(own)
        if all(_within(os.path.realpath(p), own) for p in places):
            return
    raise ValueError(f"mount: {top!r} is an importable module ({places[0]}); "
                     f"mount the {kind} {source!r} at another name")


def _within(path: str, folder: str) -> bool:
    """True if `path` is `folder` or lies inside it."""
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


_YAML_MARKER = re.compile(r"\s*yaml[ \t]*\r?\n", re.IGNORECASE)


def _parse_yaml_prefix(result: Any) -> Any:
    """A string whose first line is `yaml` alone is a YAML spec; parse the rest. Any other string, one
    merely starting with the word (`yaml`, `yaml-based pipeline`), is returned as written."""
    if isinstance(result, str) and (m := _YAML_MARKER.match(result)):
        return yaml.safe_load(result[m.end():])
    return result


def _load_base_entity(base, source_spec: str) -> Union[ModuleType, Spec]:
    ext = os.path.splitext(source_spec)[1]
    if ext == ".py" or "/" not in source_spec:
        return _load_module(base, source_spec)
    elif ext == ".json":
        with open(source_spec, 'r') as f:
            try:
                return json.load(f)
            except Exception as e:
                raise Exception(f"While parsing {source_spec}, {e}")
    elif ext == ".yaml":
        with open(source_spec, 'r') as f:
            return yaml.safe_load(f)
    else:
        raise Exception(f"ns: unsupported file type {source_spec}")


def _load_module(base, module_spec: str) -> ModuleType:
    if "/" not in module_spec:
        return import_module(module_spec)
    if not os.path.exists(module_spec):
        raise FileNotFoundError(f"ns: missing module file {module_spec}")
    spec = importlib.util.spec_from_file_location(base, module_spec)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_loadables_index(folder: str, at: str) -> Dict[str, Any]:
    folder = os.path.abspath(folder)
    results = {}
    if not folder or not os.path.exists(folder):
        raise FileNotFoundError(f"ns: could not mount folder {folder!r}")
    for path in Path(folder).rglob('*'):
        base, ext = os.path.splitext(path)
        loc = os.path.relpath(base, folder)
        loc = os.path.join(at.replace(".", "/"), loc) if at else loc   # lookup joins a name's parts by /
        if not path.is_file() or ext not in _DO_EXTENSIONS or os.path.basename(base) == '__init__':
            continue
        elif loc in results:
            print(f"WARNING: loadable at {results[loc]} conflicts with {path}")
            results[loc] = _DO_ERROR_FLAG
        else:
            results[loc] = str(path)
    return results
