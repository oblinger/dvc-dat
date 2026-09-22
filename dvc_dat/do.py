"""The do-system: `do` maps dotted names to Python objects and runs dats.

    do(target, *args, **kwargs)   # run: a dat, a template spec, or a plain callable
    do.load("pkg.mod.fn")         # the object a dotted name imports to
    do.name_of(obj)               # the dotted name that loads back to obj
    do.configure(...)             # apply a .dataconfig.yaml's mount table

`do` is a singleton: importing `dvc_dat` gives the static resolver (a dotted name
means exactly what `import` means in this environment, `getattr` below that);
`do.configure()` mounts a config's namespace onto the same object, so a name
imported early keeps working.  Importing never reads the filesystem; the `dat`
command-line tool configures itself.
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
    DAT_ARGS, DAT_BASE, DAT_DO, DAT_KWARGS, DAT_NAME, DAT_RUN_AT, DAT_RUN_TIME,
    DAT_TARGET_EXISTS, Dat, DataConfig, DatManager, merge_dicts,
)

_DO_EXTENSIONS = [".json", ".yaml", ".py"]
_DO_ERROR_FLAG = tuple("multiple loadable modules have this same name")
_DO_NULL = tuple(["-no-value-"])
_MAIN = "__main__"

Spec = Dict[str, Any]


class Do:
    """The do namespace and runner.  See the module docstring; one instance, `do`."""

    do_folder: Optional[str]
    base_locations: Dict[str, str]
    base_objects: Dict[str, Any]
    registered_values: Optional[Dict[str, Any]]
    config: Optional[DataConfig]

    def __init__(self):
        self.base_objects = {}
        self.base_locations = {}
        self.registered_values = None
        self.do_folder = None
        self.config = None
        self._configuring = False

    def _ensure_configured(self) -> None:
        """Install a config the first time one is needed.

        Import reads no filesystem; the first `load`, call or `Dat.manager` access
        discovers `.dataconfig.yaml` from the working directory and applies its mount
        table.  `configure(...)` stays for a config chosen by hand.
        """
        if self.config is None and not self._configuring:
            self._configuring = True
            try:
                self.configure()
            finally:
                self._configuring = False

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
        self._ensure_configured()
        obj = self.load(target) if isinstance(target, str) else target
        try:
            if isinstance(obj, Dat):
                if not args and not kwargs:
                    return self._run_dat(obj)
                obj = obj.get_spec(raw=True)
            elif callable(obj):
                return obj(*args, **kwargs)
            if not isinstance(obj, dict):
                raise TypeError(f"do: cannot run {obj!r}; expected a callable, a spec or a Dat")
            spec = self.fork_spec(obj, args, kwargs)
            dat, skip_execution = self.dat_from_template(spec)
            if skip_execution:
                return dat
            return self._run_dat(dat)
        except Exception as e:
            raise Exception(f"In {target!r}") from e

    @staticmethod
    def fork_spec(spec: Spec, args: Iterable[Any] = (),
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

    def _run_dat(self, dat: Dat) -> Any:
        """Run a dat as its spec says; record when and how long in its results."""
        spec = dat.get_spec()
        fn = Dat.get(spec, DAT_DO, None)
        if fn is None:
            return dat
        if isinstance(fn, str):
            fn = self.load(fn)
        if not callable(fn):
            raise TypeError(f"{DAT_DO} in {dat!r} is {fn!r}, not callable")
        args = list(Dat.get(spec, DAT_ARGS, None) or [])
        kwargs = dict(Dat.get(spec, DAT_KWARGS, None) or {})
        run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        before = time.time()
        result = fn(dat, *args, **kwargs)
        time_ms = (time.time() - before) * 1000
        exec_time = (time.strftime("%H:%M:%S", time.gmtime(time_ms // 1000))
                     + ".{:03d}".format(int(time_ms % 1000)))
        Dat.set(dat.get_results(), DAT_RUN_AT, run_at)
        Dat.set(dat.get_results(), DAT_RUN_TIME, exec_time)
        dat.save()
        return result

    def dat_from_template(self, spec: Spec, *, path: Optional[str] = None) -> Tuple[Dat, bool]:
        """Create the dat a template spec describes (see `DatManager.create`).

        Returns `(dat, skip_execution)`; `skip_execution` is True when
        `dat.target_exists: use` found the dat already there.
        """
        spec = self.resolve_base(copy.deepcopy(spec))
        path = path or Dat.get(spec, DAT_NAME, None)
        target_exists = Dat.get(spec, DAT_TARGET_EXISTS, "error")
        if target_exists == "use":
            expanded, exists = Dat.manager.prepare_dat_path(path, target_exists="use")
            if exists:
                return Dat.load(expanded), True
        return Dat.create(path=path, spec=spec), False

    # -- specs ---------------------------------------------------------------

    def resolve_base(self, spec: Union[Spec, str]) -> Spec:
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
            merged = merge_dicts(merged, self.resolve_base(entry))
        result = merge_dicts(merged, spec)
        result["dat"].pop("base", None)
        return result

    # -- loading -------------------------------------------------------------

    def load(self, dotted_name: str, *, default: Any = _DO_NULL,
             kind: Optional[Type] = None) -> Any:
        """The object `dotted_name` names.

        Mounted names are checked first (values, modules, files, do-folders); otherwise
        the longest importable prefix is imported and the rest is `getattr`.  With
        nothing found the import's own `ImportError` / `AttributeError` propagates
        unless `default` is given.  A `.py`/`.yaml`/`.json` mount's contents are
        returned as loaded; a string starting with `yaml` is parsed as YAML.
        """
        self._ensure_configured()
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
        if self.registered_values and _DO_NULL != \
                (value := self.registered_values.get(dotted_name, _DO_NULL)):
            value = _parse_yaml_prefix(value)
            return copy.deepcopy(value) if isinstance(value, dict) else value
        obj = self.get_base(file_base, default=None)
        if obj is None:
            if self.do_folder and (result := _resolve_in_folder(self.do_folder, parts)) is not None:
                return result
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
        return self.base_locations.keys()

    def resolve_dat_folder(self, name: str) -> Optional[str]:
        """The folder of a dat mounted as `<name>/_spec_`, else None."""
        spec_key = name + "/_spec_"
        if spec_key in self.base_locations:
            return os.path.dirname(self.base_locations[spec_key])
        return None

    # -- mounting ------------------------------------------------------------

    def configure(self, source: Union[None, str, Path, DataConfig] = None) -> DataConfig:
        """Install a config: build `Dat.manager`, then import its `main` module.

        `source` is a `DataConfig`, a folder to search up from, a config file, or
        None for discovery from the working directory.  The config folder goes
        first on `sys.path`; `main` is imported after that, so the `do.mount()`
        calls it makes land on the singleton `do` before any name is resolved.
        """
        if isinstance(source, DataConfig):
            config = source
        elif source is None:
            config = DataConfig.new()
        else:
            source = Path(source)
            if source.is_file():
                config = DataConfig.new(cwd=source.parent, config_name=source.name)
            else:
                config = DataConfig.new(cwd=source)
        Dat._manager = DatManager(config)
        from . import dat_tools
        self.mount(module=dat_tools, at="dat_tools")
        self.mount(module=dat_tools, at="dt")
        self.mount(value=dat_tools.cmd_list, at="dt.list")
        self.mount(value=dat_tools.cmd_list, at="dat_tools.list")
        self.config = config
        root = str(config.cwd)          # the config folder is the import root
        if root not in sys.path:
            sys.path.insert(0, root)
        if config.main:
            import_module(config.main)  # its `do.mount(...)` calls land here
        return config

    def mount(self, *,
              folder: Optional[str] = None,
              file: Optional[str] = None,
              module: Union[ModuleType, str, None] = None,
              value: Any = None,
              at: str = "",
              relative_to: str = "."):
        """Mount data in the namespace at `at`: a `folder` of loadables, a single
        `file`, a `module` (object, import name or path), or a literal `value`."""
        if 1 != sum(x is not None for x in (folder, file, module, value)):
            raise ValueError("mount: exactly one of 'folder', 'file', 'module' or 'value'")
        elif folder is not None:
            folder = os.path.join(relative_to, folder)
            for base, path in _build_loadables_index2(folder, at).items():
                self._reg_module(base, path, allow_redefine=True)
        elif file is not None:
            self.base_locations[at] = os.path.join(relative_to, file)
        elif module is not None:
            self._reg_module(at, module, allow_redefine=True)
        else:
            self._reg_value(at, value)

    def add_do_folder(self, do_folder):
        """Mount a folder of loadables by file name, and forget cached values."""
        self.do_folder = do_folder
        for base, path in _build_loadables_index(do_folder).items():
            self._reg_module(base, path, allow_redefine=True)
        self.registered_values = None

    def get_base(self, base: str, default: Any = _DO_NULL) -> Any:
        """The module or object mounted at base name `base`."""
        if base in self.base_objects:
            result = self.base_objects[base]
        elif base in self.base_locations:
            self.base_objects[base] = _load_base_entity(base, self.base_locations[base])
            result = self.base_objects[base]
        elif default is _DO_NULL:
            raise KeyError(f"do: base {base + '...'!r} is not mounted")
        else:
            result = default
        if isinstance(result, dict):
            result = copy.deepcopy(result)
        return result

    def _reg_module(self, at: str, module_spec: Union[str, ModuleType], *, allow_redefine=False):
        if (not allow_redefine and at in self.base_locations
                and self.base_locations[at] != module_spec):
            raise Exception(f"Base {at!r} is already defined")
        if isinstance(module_spec, ModuleType):
            self.base_locations[at] = "--directly-assigned--"
            self.base_objects[at] = module_spec
        else:
            self.base_locations[at] = module_spec
            self.base_objects.pop(at, None)

    def _reg_value(self, dotted_name: str, value: Any):
        if self.registered_values is None:
            self.registered_values = {}
        self.registered_values[dotted_name] = value


def _parse_yaml_prefix(result: Any) -> Any:
    """A string beginning `yaml` is a YAML spec; parse it."""
    if isinstance(result, str) and result.lstrip().lower().startswith("yaml"):
        return yaml.safe_load(result.lstrip()[4:].lstrip())
    return result


def _resolve_in_folder(folder: str, parts: List[str]) -> Optional[Any]:
    """Resolve a dotted name by walking a folder: part.yaml / part.json / part.py / part/."""
    path = folder
    for i, part in enumerate(parts):
        for ext in [".yaml", ".json", ".py"]:
            candidate = os.path.join(path, part + ext)
            if os.path.isfile(candidate):
                obj = _load_base_entity(part, candidate)
                remaining = parts[i + 1:]
                if remaining and isinstance(obj, dict):
                    return Dat.get(obj, remaining, None)
                return obj
        candidate = os.path.join(path, part)
        if os.path.isdir(candidate):
            path = candidate
        else:
            return None
    return None


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


def _build_loadables_index(do_folder: str) -> Dict[str, Any]:
    result = {}
    if not do_folder or not os.path.exists(do_folder):
        return result
    for path in Path(do_folder).rglob('*'):
        base, ext = os.path.splitext(os.path.basename(path))
        if not path.is_file() or ext not in _DO_EXTENSIONS or base == '__init__':
            continue
        elif base in result:
            print(f"WARNING: loadable at {result[base]} conflicts with {path}")
            result[base] = _DO_ERROR_FLAG
        else:
            result[base] = str(path)
    return result


def _build_loadables_index2(folder: str, at: str) -> Dict[str, Any]:
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


# The singleton.
do = Do()


# =============================================================================
# Command line
# =============================================================================

USAGE = """
SYNOPSIS
    dat do TARGET [ARG ...] [KEY=VALUE ...]     run TARGET
    dat TARGET [ARG ...] [KEY=VALUE ...]        shorthand for `dat do TARGET`
    dat list [PREFIX]                           the mounted names
    dat info                                    version, sync folder, config
    dat version                                 the version
    dat --help                                  this message

DESCRIPTION
    `dat` configures itself from the nearest .dataconfig.yaml before it runs
    anything that needs the namespace.

    `dat do TARGET ...` calls do(TARGET, *ARGS, **KWARGS).  A TARGET that is a
    template spec is forked: the fixed ARGs become its dat.args and the
    KEY=VALUE pairs update its dat.kwargs, key by key; the forked spec creates
    a dat, and that dat runs.  A TARGET that is a callable is simply called.
    The return value prints on stdout when it is not None.

    Every ARG and every KEY=VALUE value is read as a YAML scalar: 7 is an int,
    true is a bool, [1,2] is a list, "x" is a string, and a bare word stays a
    string.  A KEY=VALUE pair is recognised by a leading NAME= ; use -- to end
    the options and pass anything after it as a fixed argument.

OPTIONS
    --set DOTTED.KEY VALUE
    --sets DOTTED.KEY1=VALUE1,DOTTED.KEY2=VALUE2,...
    --json DOTTED.KEY '<json value>'
                Update those spec keys of a template before it forks

    --print     Print the python do() call instead of making it
    --usage     Print TARGET's own usage (a <base>.usage value, or the spec's
                usage key), else this message

EXIT STATUS
    0   ran
    1   the run failed, or the command line was malformed
    2   TARGET does not load

    A failure prints one line on stderr and no traceback; set DAT_DEBUG=1
    for the traceback.

EXAMPLES
    dat do hello_world
    dat hello_again.salutation Maxim emphasis=true lucky_number=7
    dat my_letters --sets dat.title=Quickie,start=100,end=110
    dat list hello
"""

_KWARG = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=")


def do_argv(argv: List[str]) -> int:
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
    return _cmd_do(rest if verb == "do" else args)


def _cmd_do(argv: List[str]) -> int:
    """`dat do TARGET ...` -- the default verb."""
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
    _configured()
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
    elif "print" in flags:
        shown = ([repr(target)] + [repr(a) for a in fixed]
                 + [f"{k}={v!r}" for k, v in kwargs.items()])
        print(f"do({', '.join(shown)})")
        return 0
    try:
        if isinstance(cmd, dict):
            spec = merge_dicts(do.resolve_base(cmd), overrides)
            result = do(spec, *fixed, **kwargs)
        elif overrides:
            return _fail(f"--set/--sets/--json need a template spec; "
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
    _configured()
    from .dat_tools import cmd_list
    cmd_list(argv[0] if argv else "")
    return 0


def _cmd_info(argv: List[str]) -> int:
    """`dat info` -- the version, the sync folder and the config in force."""
    if argv:
        return _fail("info takes no arguments")
    from . import __version__
    config = _configured()
    print("\n# -- Dat Configuration Info -- ")
    print(f"# Dat version       : {__version__}")
    print(f"# Dat Data Folder   : {Dat.manager.sync_folder}")
    print(f"# .dataconfig folder: {config.cwd}")
    config_file = os.path.join(config.cwd, ".dataconfig.yaml")
    if os.path.exists(config_file):
        print(f"# .dataconfig.yaml  : {config_file}")
        with open(config_file) as f:
            print(f.read())
    else:
        print("# (no .dataconfig.yaml found)")
    print()
    return 0


def _configured() -> DataConfig:
    """The config in force, reading the nearest `.dataconfig.yaml` if none is."""
    if do.config is None:
        do.configure()
    return do.config


def _parse_argv(argv: List[str]) -> Tuple[Spec, List[str], Dict[str, Any], set]:
    """Split `dat do` arguments into spec overrides, positionals, kwargs and flags.

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
        elif arg in ("--json", "--set"):
            key, value = _operands(argv, i, 2)
            if arg == "--json":
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as e:
                    raise ValueError(f"--json {key}: illegal JSON: {e}")
            Dat.set(overrides, key, value)
            i += 2
        elif arg == "--sets":
            (pairs,) = _operands(argv, i, 1)
            Dat.sets(overrides, *pairs.split(","))
            i += 1
        elif arg in ("--print", "--usage"):
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


if __name__ == '__main__':
    sys.exit(do_argv(sys.argv))
