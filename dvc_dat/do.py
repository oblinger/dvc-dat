"""The do-system: `do` maps dotted names to Python objects and runs dats.

    do(target, *args, **kwargs)   # run: a dat, a template spec, or a plain callable
    do.load("pkg.mod.fn")         # the object a dotted name imports to
    do.name_of(obj)               # the dotted name that loads back to obj
    do.mount(folder=..., at=...)  # add names to the namespace, in code

`do` is the process's default namespace: it forwards to `Dat.manager.do`,
whichever manager that is.  `DatManager(dat_folders=[...])` is another world
with a `do` of its own.  A dotted name is a mounted name, else exactly what
`import` means in this environment, `getattr` below that.  Mounts are
`do.mount(...)` calls in the program; `.datconfig.yaml` holds none.  Importing
never reads the filesystem; the first use builds `Dat.manager` from the
nearest `.datconfig.yaml`.
"""

import copy
import importlib.util
import json
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


class Do:
    """A do namespace and runner, bound to the `DatManager` whose world it names.

    Every manager builds its own, reached as `manager.do`; the module-level `do`
    forwards to `Dat.manager.do`.  A bare `Do()` is a namespace with no world:
    it mounts and loads, and a manager built with `do=` adopts it; running
    anything in it before then is `RuntimeError`.
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
            raise RuntimeError("this Do has no manager; build one with "
                               "DatManager(dat_folders=[...], do=this_do)")
        return self._manager

    # -- running -------------------------------------------------------------

    def __call__(self, target: Union[str, Spec, Dat, Callable], *args, **kwargs) -> Any:
        """Run `target`.

        - a **callable** (or a name that loads to one) is called with `args`/`kwargs`;
        - a **template spec** (dict, or a name that loads to one) is forked — `args`
          replace `dat.args`, `kwargs` update `dat.kwargs` — the new spec creates a
          dat, and that dat runs with no call-site arguments;
        - a **Dat** re-runs in place when no arguments are given, and forks a new dat
          from its spec when they are.  A dat on disk is never rewritten by a run.

        A run calls `fn(dat, *dat.args, **dat.kwargs)` with `fn` the object `dat.do`
        names; the return value is the call's value, and `dat.run_at` /
        `dat.run_time` land in the results.  A template with no `dat.do` just
        creates the dat and returns it.
        """
        obj = self.load(target) if isinstance(target, str) else target
        try:
            if isinstance(obj, Dat):
                if not args and not kwargs:
                    return self.manager.execute(obj)
                obj = copy.deepcopy(obj.get_spec())
                if Dat.get(obj, DAT_TARGET_EXISTS, "error") == "error":
                    Dat.set(obj, DAT_TARGET_EXISTS, "increment")   # a fork lands beside its parent
            elif callable(obj):
                return obj(*args, **kwargs)
            if not isinstance(obj, dict):
                raise TypeError(f"do: cannot run {obj!r}; expected a callable, a spec or a Dat")
            spec = self._fork_spec(obj, args, kwargs)
            dat, skip_execution = self._dat_from_template(spec)
            if skip_execution:
                return dat
            return self.manager.execute(dat)
        except Exception as e:
            raise Exception(f"In {target!r}") from e

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

    def _dat_from_template(self, spec: Spec, *, path: Optional[str] = None) -> Tuple[Dat, bool]:
        """Create the dat a template spec describes (see `DatManager.create`).

        Returns `(dat, skip_execution)`; `skip_execution` is True when
        `dat.target_exists: use` found the dat already there.
        """
        manager = self.manager
        spec = self._resolve_base(copy.deepcopy(spec))
        path = path or Dat.get(spec, DAT_NAME, None)
        target_exists = Dat.get(spec, DAT_TARGET_EXISTS, "error")
        if target_exists == "use":
            expanded, exists = manager._prepare_dat_path(path, target_exists="use")
            if exists:
                return manager.load(expanded), True
        return manager.create(spec, path=path), False

    # -- specs ---------------------------------------------------------------

    def _resolve_base(self, spec: Union[Spec, str]) -> Spec:
        """Merge a spec over its `dat.base` (a name, a spec, or a list of them, later
        entries winning), recursively; `dat.base` is dropped from the result so the
        stored spec is complete on its own."""
        if isinstance(spec, str):
            spec = copy.deepcopy(self.load(spec))
        base = Dat.get(spec, DAT_BASE, None)
        if not base:
            return spec
        bases = base if isinstance(base, list) else [base]
        merged: Spec = {}
        for entry in bases:
            merged = merge_dicts(merged, self._resolve_base(entry))
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
                result = self._load_static(dotted_name)
        except (ImportError, AttributeError, KeyError):
            if default is not _DO_NULL:
                return default
            raise
        if result is None and default is not _DO_NULL:
            return default
        if kind and not isinstance(result, kind):
            raise TypeError(f"do.load: expected {dotted_name!r} of type {kind}, found {result!r}")
        return result

    def _load_mounted(self, dotted_name: str) -> Any:
        parts = dotted_name.split(".")
        file_base = parts[0]
        if self._registered_values:
            for cut in range(len(parts), 0, -1):   # the longest mounted prefix
                key = ".".join(parts[:cut])
                if _DO_NULL == (value := self._registered_values.get(key, _DO_NULL)):
                    continue
                value = _parse_yaml_prefix(value)
                if cut < len(parts):
                    if not isinstance(value, dict):
                        raise KeyError(f"do.load: {key!r} is a mounted value, "
                                       f"not a mapping; {dotted_name!r} is not in it")
                    value = Dat.get(value, parts[cut:], _DO_NULL)
                    if value is _DO_NULL:
                        raise KeyError(f"do.load: {'.'.join(parts[cut:])!r} "
                                       f"is missing from the value mounted at {key!r}")
                return copy.deepcopy(value) if isinstance(value, dict) else value
        obj = self._get_base(file_base, default=None)
        if obj is None:
            # A folder mount indexes its files by path under `at`: `catalog/models/baseline`
            # answers to `catalog.models.baseline`, so try the longest such prefix.
            for cut in range(len(parts), 1, -1):
                key = "/".join(parts[:cut])
                if key in self._base_locations:
                    obj = self._get_base(key)
                    file_base, parts = key, [key] + parts[cut:]
                    break
        if obj is None:
            return _DO_NULL
        if obj == _DO_ERROR_FLAG:
            raise KeyError(f"do.load: {file_base!r} is mounted more than once")
        elif isinstance(obj, ModuleType):
            if len(parts) < 2:
                result = getattr(obj, _MAIN) if hasattr(obj, _MAIN) else None
            else:
                result = getattr(obj, parts[1]) if hasattr(obj, parts[1]) else None
                result = Dat.get(result, parts[2:], None) if result is not None else None
        elif len(parts) == 1:
            result = obj
        elif isinstance(obj, dict):
            result = Dat.get(obj, parts[1:], None)
        else:
            raise KeyError(f"do.load: illegal mounted value {obj!r} for {dotted_name}")
        if result is None:
            name = dotted_name[len(file_base) + 1:] or _MAIN
            source = obj.__file__ if isinstance(obj, ModuleType) else obj
            raise KeyError(f"do.load: {name!r} is missing from {source!r}")
        result = _parse_yaml_prefix(result)
        return copy.deepcopy(result) if isinstance(result, dict) else result

    @staticmethod
    def _load_static(dotted_name: str) -> Any:
        """Import the longest importable prefix of `dotted_name`, then `getattr` the rest."""
        parts = dotted_name.split(".")
        if not all(parts):
            raise ImportError(f"do.load: {dotted_name!r} is not a dotted name")
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
        raise ImportError(f"do.load: no importable prefix of {dotted_name!r}")

    @staticmethod
    def name_of(obj: Any) -> str:
        """The dotted name `load` takes back to `obj` (a module, class or function)."""
        if isinstance(obj, ModuleType):
            return obj.__name__
        module = getattr(obj, "__module__", None)
        qualname = getattr(obj, "__qualname__", None)
        if not module or not qualname or "<" in qualname:
            raise ValueError(f"do.name_of: {obj!r} has no importable dotted name")
        return f"{module}.{qualname}"

    def keys(self) -> Iterable[str]:
        """Every mounted base name."""
        return self._base_locations.keys()

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
            self._base_locations[at] = path
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
            self._reg_value(at, value)

    def _get_base(self, base: str, default: Any = _DO_NULL) -> Any:
        """The module or object mounted at base name `base`."""
        if base in self._base_objects:
            result = self._base_objects[base]
        elif base in self._base_locations:
            self._base_objects[base] = _load_base_entity(base, self._base_locations[base])
            result = self._base_objects[base]
        elif default is _DO_NULL:
            raise KeyError(f"do: base {base + '...'!r} is not mounted")
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
        raise Exception(f"do: unsupported file type {source_spec}")


def _load_module(base, module_spec: str) -> ModuleType:
    if "/" not in module_spec:
        return import_module(module_spec)
    if not os.path.exists(module_spec):
        raise FileNotFoundError(f"do: missing module file {module_spec}")
    spec = importlib.util.spec_from_file_location(base, module_spec)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_loadables_index(folder: str, at: str) -> Dict[str, Any]:
    folder = os.path.abspath(folder)
    results = {}
    if not folder or not os.path.exists(folder):
        raise FileNotFoundError(f"do: could not mount folder {folder!r}")
    for path in Path(folder).rglob('*'):
        base, ext = os.path.splitext(path)
        loc = os.path.relpath(base, folder)
        loc = os.path.join(at, loc) if at else loc
        if not path.is_file() or ext not in _DO_EXTENSIONS or os.path.basename(base) == '__init__':
            continue
        elif loc in results:
            print(f"WARNING: loadable at {results[loc]} conflicts with {path}")
            results[loc] = _DO_ERROR_FLAG
        else:
            results[loc] = str(path)
    return results


class _DefaultDo:
    """`dvc_dat.do`: forwards every call and attribute to `Dat.manager.do`, so it
    always acts on the default world, whichever manager that is."""

    __slots__ = ()

    @staticmethod
    def _current() -> Optional[Do]:
        """The default world's `Do` if one is built yet, else None (reads no config)."""
        from . import core
        return core._default_manager.do if core._default_manager is not None else None

    def __call__(self, *args, **kwargs) -> Any:
        return Dat.manager.do(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(Dat.manager.do, name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"dvc_dat.do forwards to Dat.manager.do; set {name!r} there")

    def __repr__(self) -> str:
        return f"<dvc_dat.do -> {self._current()!r}>"


# The process's default namespace: `Dat.manager.do`, whichever manager that is.
do = _DefaultDo()


# =============================================================================
# Command line
# =============================================================================

USAGE = """
SYNOPSIS
    dat TARGET [ARG ...] [KEY=VALUE ...]        run TARGET
    dat list [PREFIX]                           the mounted names
    dat info                                    version, dat folder, config
    dat version                                 the version
    dat --help                                  this message

DESCRIPTION
    `dat` configures itself from the nearest .datconfig.yaml before it runs
    anything that needs the namespace.  `list`, `info` and `version` are
    reserved words; anything else in first position is a TARGET.

    `dat TARGET ...` calls do(TARGET, *ARGS, **KWARGS).  A TARGET that is a
    template spec is forked: the fixed ARGs become its dat.args and the
    KEY=VALUE pairs update its dat.kwargs, key by key; the forked spec creates
    a dat, and that dat runs.  A TARGET that is a callable is simply called.
    The return value prints on stdout when it is not None.

    Every ARG and every KEY=VALUE value is read as a YAML scalar: 7 is an int,
    true is a bool, [1,2] is a list, "x" is a string, and a bare word stays a
    string.  A KEY=VALUE pair is recognised by a leading NAME= ; use -- to end
    the options and pass anything after it as a fixed argument.

OPTIONS
    --set DOTTED.KEY=VALUE      (repeatable; VALUE is a YAML scalar)
    --json DOTTED.KEY '<json value>'
                Update those spec keys of a template before it forks

    --dry-run   Print the python do() call instead of making it
    --usage     Print TARGET's own usage (a <base>.usage value, or the spec's
                usage key), else this message

EXIT STATUS
    0   ran
    1   the run failed, or the command line was malformed
    2   TARGET does not load

    A failure prints one line on stderr and no traceback; set DAT_DEBUG=1
    for the traceback.

EXAMPLES
    dat hello_world
    dat hello_again.salutation Maxim emphasis=true lucky_number=7
    dat my_letters --set dat.title=Quickie --set start=100 --set end=110
    dat list hello
"""

_KWARG = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=")


ENV_CLI_CONFIG = "DAT_CLI_CONFIG"     # set by the bootstrap, read here and nowhere else


def cli_main(argv: Optional[List[str]] = None, *,
             config: Union[None, str, Path] = None) -> int:
    """The `dat` command line, for a program's own main.

    A program that mounts names -- or simply wants `dat` to run inside its own
    imports -- names its main in `.datconfig.yaml`'s `run:` and, when
    `DAT_CLI_CONFIG` is set, ends with `sys.exit(dat.cli_main())`.  The bootstrap
    copy of `bin/dat` sets that one variable -- the config file it found -- for
    the program it launches, so the main knows it was launched by `dat` and the
    config is read once; nothing else reads the variable.  `argv` defaults to
    `sys.argv`; `config` (a folder or a config file) replaces the default world,
    `Dat.manager = DatManager.load_dat_config(config, do=dvc_dat.do)`, keeping
    its mounts; with neither, first use discovers one.  The return value is the
    exit status.
    """
    if config is None:
        config = os.environ.get(ENV_CLI_CONFIG) or None
        if config and not Path(config).is_file():
            raise ValueError(f"{ENV_CLI_CONFIG}={config}: no such config file")
    if config is not None:
        Dat.manager = DatManager.load_dat_config(config, do=do)
    return _do_argv(list(sys.argv if argv is None else argv))


def _do_argv(argv: List[str]) -> int:
    """Run one `dat` command line (argv[0] is the program); returns the exit code."""
    args = list(argv[1:])
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    verb, rest = args[0], args[1:]
    if verb in ("version", "--version"):
        from . import __version__
        print(__version__)
        return 0
    elif verb in ("info", "--info"):
        return _cmd_info(rest)
    elif verb == "list":
        return _cmd_list(rest)
    return _cmd_do(args)


def _cmd_do(argv: List[str]) -> int:
    """`dat TARGET ...` -- everything that is not a reserved word."""
    try:
        overrides, args, kwargs, flags = _parse_argv(argv)
    except ValueError as e:
        return _fail(str(e))
    if not args:
        if "usage" in flags:
            print(USAGE)
            return 0
        return _fail("no TARGET given; `dat --help` for usage")
    target, fixed = args[0], [_scalar(a) for a in args[1:]]
    try:
        cmd = do.load(target)
    except (ImportError, AttributeError, KeyError) as e:
        return _fail(f"cannot load {target!r}: {_message(e)}", code=2)
    if "usage" in flags:
        usage = do.load(target.split(".")[0] + ".usage", default=None)
        if usage is None and isinstance(cmd, dict):
            usage = cmd.get("usage")
        print(usage or USAGE)
        return 0
    elif "dry-run" in flags:
        shown = ([repr(target)] + [repr(a) for a in fixed]
                 + [f"{k}={v!r}" for k, v in kwargs.items()])
        print(f"do({', '.join(shown)})")
        if overrides:
            print(f"  with the spec updated by --set/--json: {overrides!r}")
        return 0
    try:
        if isinstance(cmd, dict):
            spec = merge_dicts(do._resolve_base(cmd), overrides)
            result = do(spec, *fixed, **kwargs)
        elif overrides:
            return _fail(f"--set/--json need a template spec; "
                         f"{target!r} is {type(cmd).__name__}")
        elif not callable(cmd):
            print(cmd)
            return 0
        else:
            result = do(target, *fixed, **kwargs)
    except Exception as e:
        if os.environ.get("DAT_DEBUG"):
            raise
        return _fail(_message(e))
    if result is not None:
        print(result)
    return 0


def _cmd_list(argv: List[str]) -> int:
    """`dat list [PREFIX]` -- the mounted names."""
    if len(argv) > 1:
        return _fail("list takes at most one PREFIX")
    from .dat_tools import cmd_list
    cmd_list(argv[0] if argv else "")
    return 0


def _cmd_info(argv: List[str]) -> int:
    """`dat info` -- the version, the dat folder and the config in force."""
    if argv:
        return _fail("info takes no arguments")
    from . import __version__
    manager = Dat.manager
    config_dir = manager._config_dir
    print("\n# -- Dat Configuration Info -- ")
    print(f"# Dat version       : {__version__}")
    print(f"# Dat folder        : {manager._dat_folders[0]}")
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


def _parse_argv(argv: List[str]) -> Tuple[Spec, List[str], Dict[str, Any], set]:
    """Split `dat TARGET` arguments into spec overrides, positionals, kwargs and flags.

    Positionals come back as written (the first is the target name); every
    KEY=VALUE value is a YAML scalar.  A malformed line raises `ValueError`.
    """
    overrides: Spec = {}
    args: List[str] = []
    kwargs: Dict[str, Any] = {}
    flags: set = set()
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            args += argv[i + 1:]
            break
        elif arg == "--json":
            key, value = _operands(argv, i, 2)
            try:
                value = json.loads(value)
            except json.JSONDecodeError as e:
                raise ValueError(f"--json {key}: illegal JSON: {e}")
            Dat.set(overrides, key, value)
            i += 2
        elif arg == "--set":
            (pair,) = _operands(argv, i, 1)
            key, eq, value = pair.partition("=")
            if not eq or not key:
                raise ValueError(f"--set needs DOTTED.KEY=VALUE, got {pair!r}")
            Dat.set(overrides, key, _scalar(value))
            i += 1
        elif arg in ("--dry-run", "--usage"):
            flags.add(arg[2:])
        elif (match := _KWARG.match(arg)):
            kwargs[match.group(1)] = _scalar(arg[match.end():])
        elif arg.startswith("-") and arg != "-":
            raise ValueError(f"unknown option {arg!r}; "
                             f"keyword arguments are written KEY=VALUE")
        else:
            args.append(arg)
        i += 1
    return overrides, args, kwargs, flags


def _operands(argv: List[str], i: int, count: int) -> List[str]:
    """The `count` words after the option at `argv[i]`."""
    operands = argv[i + 1:i + 1 + count]
    if len(operands) < count:
        raise ValueError(f"{argv[i]} needs {count} value(s)")
    return operands


def _scalar(text: str) -> Any:
    """One command-line word as a YAML scalar; a bare word stays a string."""
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return text


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
    print(f"dat: {text}", file=sys.stderr)
    return code
