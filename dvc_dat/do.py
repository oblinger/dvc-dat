"""The namespace: `ns` maps dotted names to Python objects.

    ns.load("pkg.mod.fn")         # the object a dotted name imports to
    ns.name_of(obj)               # the dotted name that loads back to obj
    ns.mount(folder=..., at=...)  # add names to the namespace, in code
    ns.mounts()                   # the mount table: {prefix: location}

Running is the manager's: `Dat.manager.run(target, *args, **kwargs)` runs a
dat, a template spec or a plain callable, loading names through this namespace.
`ns` (`Dat.ns`) is the process's default namespace: it forwards to `Dat.manager.ns`,
whichever manager that is.  `DatManager(dat_folders=[...])` is another world
with an `ns` of its own.  A dotted name is a mounted name, else exactly what
`import` means in this environment, `getattr` below that.  Mounts are
`ns.mount(...)` calls in the program; `.datconfig.yaml` holds none.  Importing
never reads the filesystem; the first use builds `Dat.manager` from the
nearest `.datconfig.yaml`.

In a project whose `.datconfig.yaml` names a ledger, `Dat.manager.ns` is a
`LedgerNamespace` (`dvc_dat.ledger.namespace`, DAT 1046, 1051): the same interface, its
names the ledger's `db/mount` rows, and `mount` refused.
"""

import copy
import importlib.util
import json
import math
import os
import re
import sys
import time
from datetime import datetime
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Type, Union

import yaml

from .core import (
    DAT_ARGS, DAT_BASE, DAT_CONFIG_FILE, DAT_DO, DAT_KWARGS, DAT_NAME, DAT_RUN_AT, DAT_RUN_TIME,
    DAT_TARGET_EXISTS, Dat, DatManager, merge_dicts,
)

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
    _manager: Optional[DatManager]

    def __init__(self, manager: Optional[DatManager] = None):
        self._base_objects = {}
        self._base_locations = {}
        self._registered_values = None
        self._manager = manager

    @property
    def manager(self) -> DatManager:
        """The world this namespace belongs to."""
        if self._manager is None:
            raise RuntimeError("this Namespace is a namespace with no manager, and running a "
                               "dat needs one: Namespace(manager=m), or "
                               "DatManager(dat_folders=[...], ns=this_ns)")
        return self._manager

    # -- forking (Dat.manager.run) ------------------------------------------

    @staticmethod
    def _fork_spec(spec: Spec, args: Iterable[Any] = (),
                  kwargs: Optional[Dict[str, Any]] = None) -> Spec:
        """A copy of `spec` with `args` as `dat.args` and `kwargs` merged into `dat.kwargs`."""
        spec = copy.deepcopy(spec)
        args = list(args)
        if args:
            Dat.set(spec, DAT_ARGS, args)
        if kwargs:
            merged = dict(Dat.get(spec, DAT_KWARGS, None) or {})
            merged.update(kwargs)
            Dat.set(spec, DAT_KWARGS, merged)
        return spec

    def _dat_from_template(self, spec: Spec, *, path: Optional[str] = None,
                           manager: Optional[DatManager] = None) -> Tuple[Dat, bool]:
        """Create the dat a template spec describes (see `DatManager.create`) in `manager`, the
        world running it (default this namespace's; one namespace may serve several worlds).

        Returns `(dat, skip_execution)`; `skip_execution` is True when
        `dat.target_exists: use` found the dat already there.
        """
        manager = manager or self.manager
        spec = self._merge_bases(copy.deepcopy(spec))
        path = path or Dat.get(spec, DAT_NAME, None)
        target_exists = Dat.get(spec, DAT_TARGET_EXISTS, "error")
        if target_exists == "use":
            expanded, exists = manager._prepare_dat_path(path, target_exists="use")
            if exists:
                return manager.load(expanded), True
        return manager.create(spec, path=path), False

    # -- specs ---------------------------------------------------------------

    def _merge_bases(self, spec: Union[Spec, str], _chain: Tuple[str, ...] = ()) -> Spec:
        """A spec (or the name of one) merged over its `dat.base` (a name, a spec, or a list of them, later
        entries winning), recursively; `dat.base` is dropped from the result so the
        stored spec is complete on its own."""
        if isinstance(spec, str):
            if spec in _chain:
                raise ValueError(f"dat.base: a cycle, {' -> '.join(_chain + (spec,))}")
            _chain = _chain + (spec,)
            spec = copy.deepcopy(self.load(spec))
        base = Dat.get(spec, DAT_BASE, None)
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

        Mounted names are checked first (values, modules, files, folders); otherwise
        the longest importable prefix is imported and the rest is `getattr`.  With
        nothing found the import's own `ImportError` / `AttributeError` propagates
        unless `default` is given.  A `.py`/`.yaml`/`.json` mount's contents are
        returned as loaded; a string starting with `yaml` is parsed as YAML.
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
        """The dotted name `load` takes back to `obj` (a module, class or function)."""
        if isinstance(obj, ModuleType):
            return obj.__name__
        module = getattr(obj, "__module__", None)
        qualname = getattr(obj, "__qualname__", None)
        if not module or not qualname or "<" in qualname:
            raise ValueError(f"ns.name_of: {obj!r} has no importable dotted name")
        return f"{module}.{qualname}"

    def mounts(self) -> Dict[str, str]:
        """The mount table: `{prefix: location}`, a mounted file, folder entry or
        module (its import name when mounted as an object); values mounted with
        `mount(value=...)` have no location and are not listed."""
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
        """Mount data in the namespace at `at`: a `folder` of loadables, a single
        `file`, a `module` (object, import name or path), or a literal `value`.

        A mounted name never shadows an importable one: `mount` raises `ValueError`
        when a top-level name it would add -- `at`'s first part, or with no `at`
        each top-level file or folder of a mounted folder -- is a module or
        package Python can import from somewhere else.  Mounting a module at its
        own name, or a folder that is itself the importable source, is not a clash.
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
    if spec is None:
        return
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


def _parse_yaml_prefix(result: Any) -> Any:
    """A string beginning `yaml` is a YAML spec; parse it."""
    if isinstance(result, str) and result.lstrip().lower().startswith("yaml"):
        return yaml.safe_load(result.lstrip()[4:].lstrip())
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


class _DefaultNamespace:
    """`dvc_dat.do.ns` (`Dat.ns`): forwards every call and attribute to `Dat.manager.ns`, so it
    always acts on the default world, whichever manager that is."""

    __slots__ = ()

    @staticmethod
    def _current() -> Optional[Namespace]:
        """The default world's `Namespace` if one is built yet, else None (reads no config)."""
        from . import core
        return core._default_manager.ns if core._default_manager is not None else None

    def __getattr__(self, name: str) -> Any:
        return getattr(Dat.manager.ns, name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"Dat.ns forwards to Dat.manager.ns; set {name!r} there")

    def __repr__(self) -> str:
        return f"<Dat.ns -> {self._current()!r}>"


# The process's default namespace: `Dat.manager.ns`, whichever manager that is.
ns = _DefaultNamespace()


# =============================================================================
# Command line
# =============================================================================

USAGE = """
SYNOPSIS
    x TARGET [ARG ...] [KEY=VALUE ...]          run TARGET
    x --list [PREFIX]                           the mounted names
    x --info                                    version, folders, config
    x --version                                 the version
    x --help                                    this message

DESCRIPTION
    `x` is `just run` (the recipe in dvc_dat.just; `just mounts` is
    `x --list`).  It configures itself from the nearest .datconfig.yaml
    before it runs anything that needs the namespace.  A word in first
    position is always a TARGET; the commands that ask about the command
    line itself are flags.

    `x TARGET ...` calls Dat.manager.run(TARGET, *ARGS, **KWARGS).  A TARGET that is a
    template spec is forked: the fixed ARGs become its dat.args and the
    KEY=VALUE pairs update its dat.kwargs, key by key; the forked spec creates
    a dat, and that dat runs.  A TARGET that is a callable is simply called.
    The return value prints on stdout when it is not None.

    With a `ledger:` line in the config, `x TARGET KEY=VALUE ...` is
    rev.run(TARGET, KEY=VALUE, ...): found if computed before from the same
    inputs by the same code, else run and sealed; it prints `hit` or `ran`
    and the value, and alias=NAME names it.  TARGET is a dotted name
    through the ledger's mounts or a spec file: a ledger function (its
    keys the KEY=VALUE pairs), a dat spec or a dat's run function (the
    pairs update its dat.kwargs), or a spec whose `main` names a ledger
    function (the line's keys over the file's).

    A function marked @command (dvc_dat.just), or a spec with `command:`,
    also runs as `just NAME` once the justfile has
    `import? '.dat/targets.just'`; `run` rewrites that file when stale.

    Every ARG and every KEY=VALUE value is JSON, else the text as typed: 7 is
    an int, true is a bool, null is None, [1,2] is a list, '"7"' is the string
    7, and 2026-01-01 or a bare word is that string.  A KEY=VALUE pair is recognised by a leading NAME= ; use -- to end
    the options and pass anything after it as a fixed argument.

OPTIONS
    --set DOTTED.KEY=VALUE      VALUE JSON, else the text as typed
    --json DOTTED.KEY=JSON      JSON a JSON value
                Update one spec key of a template before it forks; each
                repeats, one KEY=VALUE per flag

    --dry-run   Print the python Dat.manager.run() call instead of making it
    --usage     Print TARGET's own usage (a <base>.usage value, or the spec's
                usage key), else this message

EXIT STATUS
    0   ran
    1   the run failed, or the command line was malformed
    2   TARGET does not load

    A failure prints one line on stderr and no traceback; set DAT_DEBUG=1
    for the traceback.

EXAMPLES
    x hello_world
    x hello_again.salutation Maxim emphasis=true lucky_number=7
    x my_letters --set dat.title=Quickie --set start=100 --set end=110
    just mounts hello
"""

_KWARG = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=")


ENV_CLI_CONFIG = "DAT_CLI_CONFIG"     # set by `just run`, read here and nowhere else
ENV_JUSTFILE = "DAT_JUSTFILE"         # set by `just run`: the justfile, for `.dat/targets.just`


def cli_main(argv: Optional[List[str]] = None, *,
             config: Union[None, str, Path] = None) -> int:
    """The command line (`just run`, `x`), for a program's own main.

    A program that mounts names -- or simply wants the command line to run
    inside its own imports -- names its main in `.datconfig.yaml`'s `run:` and,
    when `DAT_CLI_CONFIG` is set, ends with `sys.exit(dat.cli_main())`.  The
    `run` recipe of `dvc_dat.just` sets that one variable -- the config file it
    found -- for the program it launches, so the main knows it was launched by
    `just run` and the config is read once; nothing else reads the variable.  `argv` defaults to
    `sys.argv`; `config` (a folder or a config file) replaces the default world,
    `Dat.manager = DatManager.load_dat_config(config, ns=Dat.ns)`, keeping
    its mounts; with neither, first use discovers one.  The return value is the
    exit status.
    """
    if config is None:
        config = os.environ.get(ENV_CLI_CONFIG) or None
        if config and not Path(config).is_file():
            raise ValueError(f"{ENV_CLI_CONFIG}={config}: no such config file")
    if config is not None:
        Dat.manager = DatManager.load_dat_config(config, ns=ns)
    argv = list(sys.argv if argv is None else argv)
    justfile = os.environ.get(ENV_JUSTFILE)
    if config is not None and justfile and argv[1:2] not in (["--version"], ["--help"], ["-h"]):
        from .just import refresh
        cfg = Path(config)
        try:
            refresh(ns, cfg.parent if cfg.is_file() else cfg, Path(justfile))
        except Exception as e:
            print(f"run: targets: {_message(e)}", file=sys.stderr)
    return _do_argv(argv, config)


def _do_argv(argv: List[str], config: Union[None, str, Path] = None) -> int:
    """Run one command line (argv[0] is the program); returns the exit code."""
    args = list(argv[1:])
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    command, rest = args[0], args[1:]
    if command == "--version":
        from . import __version__
        print(__version__)
        return 0
    elif command == "--info":
        return _cmd_info(rest)
    elif command == "--list":
        return _cmd_list(rest)
    return _cmd_do(args, config)


def _cmd_do(argv: List[str], config: Union[None, str, Path] = None) -> int:
    """`x TARGET ...` -- every line whose first word is not a flag."""
    try:
        overrides, args, kwargs, flags = _parse_argv(argv)
    except ValueError as e:
        return _fail(str(e))
    if not args:
        if "usage" in flags:
            print(USAGE)
            return 0
        return _fail("no TARGET given; `x --help` for usage")
    if "usage" not in flags:
        try:
            ledger = _ledger_of(config)
        except Exception as e:
            return _fail(_message(e))
        if ledger is not None:
            return _cmd_eval(ledger, args, kwargs, overrides, flags)
    target, fixed = args[0], [arg_value(a) for a in args[1:]]
    try:
        cmd = ns.load(target)
    except Exception as e:                  # a mounted file that does not parse included: one line, 2
        if os.environ.get("DAT_DEBUG"):
            raise
        return _fail(f"cannot load {target!r}: {_message(e)}", code=2)
    if "usage" in flags:
        usage = ns.load(target.split(".")[0] + ".usage", default=None)
        if usage is None and isinstance(cmd, dict):
            usage = cmd.get("usage")
        print(usage or USAGE)
        return 0
    elif "dry-run" in flags:
        shown = ([repr(target)] + [repr(a) for a in fixed]
                 + [f"{k}={v!r}" for k, v in kwargs.items()])
        print(f"Dat.manager.run({', '.join(shown)})")
        if overrides:
            print(f"  with the spec updated by --set/--json: {dict(overrides)!r}")
        return 0
    try:
        if isinstance(cmd, dict):
            spec = _apply_sets(ns._merge_bases(cmd), overrides)
            result = Dat.manager.run(spec, *fixed, **kwargs)
        elif overrides:
            return _fail(f"--set/--json need a template spec; "
                         f"{target!r} is {type(cmd).__name__}")
        elif not callable(cmd):
            print(cmd)
            return 0
        else:
            result = Dat.manager.run(target, *fixed, **kwargs)
    except Exception as e:
        if os.environ.get("DAT_DEBUG"):
            raise
        return _fail(_message(e))
    if result is not None:
        print(result)
    return 0


def _config_file(config: Union[None, str, Path]) -> Optional[Path]:
    """The `.datconfig.yaml` in force: `config` (a file or its folder), else the manager's."""
    if config is None:
        folder = getattr(Dat.manager, "_config_dir", None)
        config = os.path.join(folder, DAT_CONFIG_FILE) if folder else None
    if config is None:
        return None
    path = Path(config)
    path = path if path.suffix in (".yaml", ".yml") else path / DAT_CONFIG_FILE
    return path if path.is_file() else None


def _ledger_of(config: Union[None, str, Path]) -> Any:
    """The ledger the config's `ledger:` line names (`DAT_LEDGER` overriding it), else None."""
    path = _config_file(config)
    if path is None:
        return None
    led = (yaml.safe_load(path.read_text()) or {}).get("ledger")
    if not led:
        return None
    from .ledger import Ledger
    from .ledger.ledger import ENV, _relative, is_dsn
    if os.environ.get(ENV):
        return Ledger()
    ledger = Ledger(led if is_dsn(led) else _relative(path, led))
    ledger._assert_mounts(path)              # the config's `mounts:` sugar, as `Ledger()` does
    return ledger


RESERVED_RUN_KEYS = ("alias",)                # control options on a ledger run, never a key


def _cmd_eval(ledger: Any, args: List[str], kwargs: Dict[str, Any], overrides: List[Tuple[str, Any]],
              flags: set) -> int:
    """`x TARGET k=v ...` with a ledger: `rev.run(TARGET, **kwargs)`, found if computed before, else run
    and sealed (DAT 1046).

    TARGET is what `rev.run` takes: a dotted name through the ledger's mounts (a ledger function, a
    spec, or a dat's run function, its keys updating the spec's `dat.kwargs`), or a spec file
    (`.yaml`/`.json`).  A spec whose `main` names a ledger function is that function, its other keys
    the keys, the line's over the file's.  `--set` / `--json` update a spec's keys.  `alias=NAME`
    names the result (`path=`).
    """
    target, fixed = args[0], args[1:]
    if fixed:
        return _fail(f"a run through the ledger takes keywords only (KEY=VALUE); got {fixed!r}")
    rev = ledger.at()
    spec: Any = None
    is_file = os.path.isfile(target) and target.endswith((".yaml", ".yml", ".json"))
    try:
        if is_file:
            with open(target) as f:
                spec = json.load(f) if target.endswith(".json") else yaml.safe_load(f)
            if not isinstance(spec, dict):
                return _fail(f"{target}: a spec is a mapping, not {type(spec).__name__}")
        else:
            obj = rev.ns.load(target)
            if isinstance(obj, dict):
                spec = obj
            elif overrides:
                return _fail(f"--set/--json need a spec; {target!r} is {type(obj).__name__}")
    except Exception as e:
        if os.environ.get("DAT_DEBUG"):
            raise
        return _fail(f"cannot load {target!r}: {_message(e)}", code=2)
    run_target: Any = target
    keys: Dict[str, Any] = {}
    if spec is not None:
        spec = _apply_sets(spec, overrides)
        if isinstance(spec.get("main"), str):
            run_target = spec["main"]
            keys = {k: v for k, v in spec.items() if k not in ("main", "command")}
        elif isinstance(spec.get("dat"), dict):
            run_target = spec if (is_file or overrides) else target
        else:
            return _fail(f"{target}: a spec run through the ledger is a dat spec (`dat:` naming its run "
                         "function in `dat.do`) or names a ledger function in `main`")
    keys.update(kwargs)
    alias = keys.pop("alias", None)
    if "dry-run" in flags:
        shown = [repr(run_target)] + [f"{k}={v!r}" for k, v in keys.items()]
        print(f"rev.run({', '.join(shown)})" + (f", then named {alias!r}" if alias else ""))
        return 0
    try:
        hit = rev.run(run_target, seal="get", path=alias, **keys)
        value = hit or rev.run(run_target, path=alias, **keys)
    except Exception as e:
        if os.environ.get("DAT_DEBUG"):
            raise
        return _fail(_message(e))
    preds = " ".join(f"{p}={json.dumps(o) if isinstance(o, (dict, list)) else o}"
                     for p, o in value.preds.items())
    print(f"{'hit' if hit else 'ran'}  {value}" + (f"  {preds}" if preds else ""))
    return 0


def _cmd_list(argv: List[str]) -> int:
    """`x --list [PREFIX]` (`just mounts`) -- the mounted names."""
    if len(argv) > 1:
        return _fail("--list takes at most one PREFIX")
    from .dat_tools import cmd_list
    cmd_list(argv[0] if argv else "")
    return 0


def _cmd_info(argv: List[str]) -> int:
    """`x --info` -- the version, the folders and the config in force."""
    if argv:
        return _fail("--info takes no arguments")
    from . import __version__
    manager = Dat.manager
    config_dir = manager._config_dir
    print("\n# -- Dat Configuration Info -- ")
    print(f"# Dat version       : {__version__}")
    print(f"# Dat folder        : {manager._dat_folders[0]}")
    print(f"# Artifact folder   : {manager._art_folder or '(none)'}")
    print(f"# .datconfig folder : {config_dir}")
    config_file = os.path.join(config_dir, DAT_CONFIG_FILE) if config_dir else None
    if config_file and os.path.exists(config_file):
        print(f"# .datconfig.yaml   : {config_file}")
        with open(config_file) as f:
            print(f.read())
    else:
        print("# (no .datconfig.yaml found)")
    print()
    return 0


def _parse_argv(argv: List[str]) -> Tuple[List[Tuple[str, Any]], List[str], Dict[str, Any], set]:
    """Split `x TARGET` arguments into spec overrides, positionals, kwargs and flags.

    The overrides are the `--set` / `--json` `(DOTTED.KEY, value)` pairs in order, each setting
    one key (`_apply_sets`).  Positionals come back as written (the first is the target name); every
    KEY=VALUE value is `arg_value` (JSON, else the text).  A malformed line raises `ValueError`.
    """
    overrides: List[Tuple[str, Any]] = []
    shape: Spec = {}                    # the keys the line sets, so a key under a scalar it set is refused
    args: List[str] = []
    kwargs: Dict[str, Any] = {}
    flags: set = set()
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            args += argv[i + 1:]
            break
        elif arg in ("--set", "--json"):
            (pair,) = _operands(argv, i, 1)
            key, eq, value = pair.partition("=")
            if not eq or not key:
                raise ValueError(f"{arg} needs DOTTED.KEY=VALUE, got {pair!r}")
            if arg == "--json":
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as e:
                    raise ValueError(f"--json {key}: illegal JSON: {e}")
            else:
                value = arg_value(value)
            Dat.set(shape, key, copy.deepcopy(value))
            overrides.append((key, value))
            i += 1
        elif arg in ("--dry-run", "--usage"):
            flags.add(arg[2:])
        elif not args and not arg.startswith("-"):
            args.append(arg)                # the first word is the TARGET, never parsed (cli.md)
        elif (match := _KWARG.match(arg)):
            kwargs[match.group(1)] = arg_value(arg[match.end():])
        elif arg.startswith("-") and arg != "-" and isinstance(arg_value(arg), str):
            raise ValueError(f"unknown option {arg!r}; "
                             f"keyword arguments are written KEY=VALUE")
        else:
            args.append(arg)
        i += 1
    return overrides, args, kwargs, flags


def _apply_sets(spec: Spec, overrides: List[Tuple[str, Any]]) -> Spec:
    """A copy of `spec` with each `--set` / `--json` pair applied in order: the value replaces what the
    dotted key held (a dict or a named list too, never merged into it); missing levels are made."""
    out = copy.deepcopy(spec)
    for key, value in overrides:
        Dat.set(out, key, copy.deepcopy(value))
    return out


def _operands(argv: List[str], i: int, count: int) -> List[str]:
    """The `count` words after the option at `argv[i]`."""
    operands = argv[i + 1:i + 1 + count]
    if len(operands) < count:
        raise ValueError(f"{argv[i]} needs {count} value(s)")
    return operands


def arg_value(text: str) -> Any:
    """One command-line value: JSON, else the text exactly as typed (DAT 1041).

    The one `k=v` grammar of every dat command line (`x`, `just run`, `--set`, the
    ledger recipes): `12` an int, `1.5` a float, `true` a bool, `null` None, `[1,2]`
    a list, `{"a":1}` a dict, `"12"` the string 12; `2026-01-01`, `foo` and `NaN`
    are not JSON, so each is that string.
    """
    if text != text.strip():
        return text                     # JSON would drop the padding: not the text as typed
    try:
        return json.loads(text, parse_constant=_not_json, parse_float=_finite)
    except (ValueError, RecursionError):
        return text


def _finite(text: str) -> float:
    """A JSON number too big for a float (`1e999`) is not `inf`: the text stays as typed."""
    x = float(text)
    if math.isinf(x):
        raise ValueError(text)
    return x


def _not_json(name: str) -> Any:
    """`NaN` / `Infinity` / `-Infinity` are Python's extensions, not JSON."""
    raise ValueError(name)


def _message(error: BaseException) -> str:
    """One line naming an exception and the exceptions it was raised from."""
    parts: List[str] = []
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        text = str(error) or type(error).__name__
        if text not in parts:
            parts.append(text)
        error = error.__cause__
    return ": ".join(parts)


def _fail(text: str, code: int = 1) -> int:
    """Print a one-line error on stderr and return the exit code."""
    text = " ".join(line.strip() for line in text.splitlines() if line.strip())   # a YAML error spans lines
    print(f"run: {text}", file=sys.stderr)
    return code
