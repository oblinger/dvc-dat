"""dvc_dat core: configuration, the Dat manager, Dat, and spec expansion.

A Dat is a folder carrying a `_spec_.yaml` that is a complete, argumentless recipe
for itself, plus a `_result_.yaml` holding what running it produced.  The do-system
(`dvc_dat.do`) runs specs; this module stores and loads them.
"""

import importlib
import inspect
import json
import logging
import os
import re
import shutil
import subprocess
import time
import weakref
from copy import deepcopy
import sys
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, Generic, List, Optional, Tuple, Type, TypeVar, Union

import yaml

logger = logging.getLogger(__name__)


# =============================================================================
# Utilities
# =============================================================================

def merge_dicts(*dicts: Dict, inplace: bool = False) -> Dict:
    """Recursively merge N dicts; each dict overrides the ones before it."""
    if len(dicts) == 1:
        return dicts[0]
    dict_1 = dicts[0]
    if not inplace:
        dict_1 = deepcopy(dict_1)
    dict_2 = dicts[1]
    for k, v in dict_2.items():
        if isinstance(v, dict) and isinstance(dict_1.get(k), dict):
            dict_1[k] = merge_dicts(dict_1[k], v)
        else:
            dict_1[k] = deepcopy(v)
    return merge_dicts(dict_1, *dicts[2:])


# =============================================================================
# Configuration
# =============================================================================

DAT_CONFIG_FILE = ".datconfig.yaml"
DAT_CONFIG_OVERRIDE_FILE = ".datconfig.override.yaml"
ENV_PREFIX = "DAT_"
_CONFIG_KEYS = ("dat_folders", "run")    # `run` is read by `bin/dat` only
_DEFAULT_DAT_FOLDER = "data"


def _find_file_up(path: Union[str, Path], file_name: str) -> Optional[Path]:
    """`file_name` in `path` or the nearest of its parents, else None."""
    path = Path(path).absolute()
    prev_path: Optional[Path] = None
    while prev_path != path:
        candidate = path / file_name
        if candidate.exists():
            return candidate
        prev_path = path
        path = path.parent
    return None


def _read_config(path: Optional[Path]) -> Dict[str, Any]:
    """The keys of one config file; an unknown key is `ValueError`."""
    if not path:
        return {}
    with path.open("r") as f:
        values = yaml.safe_load(f) or {}
    if not isinstance(values, dict):
        raise ValueError(
            f"{path}: expected a mapping of config keys, got {type(values).__name__}")
    unknown = sorted(set(values) - set(_CONFIG_KEYS))
    if unknown:
        raise ValueError(
            f"{path}: unknown config key(s) {unknown}; known keys are {list(_CONFIG_KEYS)}")
    return values


def _within(path: str, folder: str) -> bool:
    """True if `path` is `folder` or lies inside it."""
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


# =============================================================================
# Spec constants and types
# =============================================================================

DAT_KIND = "dat.kind"
DAT_BASE = "dat.base"                  # spec(s) to inherit from
DAT_NAME = "dat.name"                  # the path template
DAT_TARGET_EXISTS = "dat.target_exists"  # error | use | overwrite | increment
DAT_DO = "dat.do"                      # the function to run
DAT_ARGS = "dat.args"                  # its positional arguments
DAT_KWARGS = "dat.kwargs"              # its keyword arguments
DAT_RUN_AT = "dat.run_at"              # result: when the last run started
DAT_RUN_TIME = "dat.run_time"          # result: how long it took
DAT_CODE = "dat.code"                  # result: branch, commit, dirty of the code run

_DEFAULT_PATH_TEMPLATE = "anonymous/Dat{unique}"


def _kind_name(cls: Type) -> str:
    """The `dat.kind` a class is written as: its dotted `module.qualname`."""
    return f"{cls.__module__}.{cls.__qualname__}"


def _find_subclass_by_name(klass: Type, name: str) -> Optional[Type]:
    if klass.__name__ == name:
        return klass
    for sub in klass.__subclasses__():
        if result := _find_subclass_by_name(sub, name):
            return result
    return None


def _git(folder: str, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", folder, *args], capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _code_of(fn: Callable) -> Optional[Dict[str, Any]]:
    """`{branch, commit, dirty}` of the git checkout holding `fn`'s source, or None
    when it has no source file or the file is not in a checkout.  `branch` is None
    on a detached HEAD; `dirty` counts tracked files only."""
    try:
        source = inspect.getsourcefile(inspect.unwrap(fn))
    except TypeError:
        return None
    if not source:
        return None
    folder = os.path.dirname(os.path.abspath(source))
    commit = _git(folder, "rev-parse", "HEAD")
    if not commit:
        return None
    branch = _git(folder, "rev-parse", "--abbrev-ref", "HEAD")
    status = _git(folder, "status", "--porcelain", "--untracked-files=no")
    return {"branch": None if branch in (None, "HEAD") else branch,
            "commit": commit, "dirty": bool(status)}
_NO_ARG = object()


class _SpecDumper(yaml.SafeDumper):
    """SafeDumper that also writes tuples (a python spec may hold them) as sequences."""


_SpecDumper.add_representer(
    tuple, lambda dumper, value: dumper.represent_list(list(value)))


SPEC_JSON = "_spec_.json"
SPEC_YAML = "_spec_.yaml"
RESULT_YAML = "_result_.yaml"

PathLike = Union[str, Path]
SpecValue = Union[str, int, float, bool, None, "SpecDict", List[Any]]
SpecDict = Dict[str, SpecValue]
DatType = TypeVar("DatType", bound="Dat")


class _DataState(Enum):
    NOT_LOADED = auto()


# =============================================================================
# Expansion: the `{}` grammar
# =============================================================================

_REFERENCE = re.compile(r"\{\{|\}\}|\{([^{}]*)\}")
_WHOLE_VALUE = re.compile(r"^\{([^{}]+)\}$")


def _builtins(now: Optional[datetime] = None) -> Dict[str, str]:
    now = now or datetime.now()
    return {
        "now": now.strftime("%y-%m-%d_%H-%M-%S"),
        "YYYY": now.strftime("%Y"),
        "YY": now.strftime("%Y")[2:],
        "MM": now.strftime("%m"),
        "DD": now.strftime("%d"),
        "HH": now.strftime("%H"),
        "mm": now.strftime("%M"),
        "SS": now.strftime("%S"),
        "unique": "",
        "cwd": os.getcwd(),
    }


def _resolve_name(name: str, vars: Dict[str, Any], resolver: Optional[Callable[[str], Any]]) -> Any:
    name = name.strip()
    if not name:
        raise ValueError("expand: empty reference '{}'")
    if "." in name:
        if resolver is None:
            from .do import do          # the default world; a manager passes its own
            resolver = do.load
        return resolver(name)
    if name in vars:
        return vars[name]
    raise KeyError(
        f"expand: unknown name {{{name}}}; undotted names are the built-ins "
        f"{sorted(_builtins())} and the vars given, a dotted name resolves through do.load"
    )


def expand(text: str, vars: Optional[Dict[str, Any]] = None, *,
           resolver: Optional[Callable[[str], Any]] = None) -> Any:
    """Expand the `{}` references in `text`.

    `{name}` with an undotted name is a built-in (`YYYY YY MM DD HH mm SS now cwd unique`)
    or a key of `vars`; `{dotted.name}` is resolved through `do.load` (or `resolver`);
    `{{` and `}}` are the literal braces.  A `text` that is exactly one reference returns
    the referenced object itself, not its string form; a reference inside a longer
    string must be a string or a number.
    """
    if not isinstance(text, str):
        return text
    names = {**_builtins(), **(vars or {})}

    def resolve(name: str) -> Any:
        return _resolve_name(name, names, resolver)

    if (whole := _WHOLE_VALUE.match(text)):
        return resolve(whole.group(1))

    def replace(match: "re.Match") -> str:
        token = match.group(0)
        if token == "{{":
            return "{"
        if token == "}}":
            return "}"
        value = resolve(match.group(1))
        if not isinstance(value, (str, int, float)):
            raise TypeError(
                f"expand: {{{match.group(1)}}} inside a longer string must be a string "
                f"or a number, got {type(value).__name__}; a reference that is the whole "
                "value may be anything")
        return str(value)

    return _REFERENCE.sub(replace, text)


def expand_spec(spec: Any, vars: Optional[Dict[str, Any]] = None, *,
                resolver: Optional[Callable[[str], Any]] = None) -> Any:
    """Return a copy of `spec` with every string value expanded (keys are left alone)."""
    if isinstance(spec, dict):
        return {k: expand_spec(v, vars, resolver=resolver) for k, v in spec.items()}
    if isinstance(spec, list):
        return [expand_spec(v, vars, resolver=resolver) for v in spec]
    if isinstance(spec, str):
        return expand(spec, vars, resolver=resolver)
    return spec


# =============================================================================
# DatManager
# =============================================================================

class DatManager:
    """A world of dats: the dat folders, and the namespace that names things in them.

    A manager owns its `do` -- a `Do` bound to it, carrying its mounts, its `load`
    and its runner -- and everything the manager does (a dotted spec, `dat.base`,
    `{}` expansion, path resolution, every run) goes through that `do`.  The
    process's default world is `Dat.manager`, built on first use by
    `DatManager.load_dat_config()` and replaced by assigning to it.  Any number
    of others coexist.  `do` is the only public attribute.
    """

    do: "Do"
    _dat_folders: List[str]
    _config_dir: Optional[str]
    _dat_cache: "weakref.WeakValueDictionary[str, Dat]"

    def __init__(self, *, dat_folders: List[str], do: Optional["Do"] = None):
        """A world on `dat_folders` -- searched in order by name, the first written
        to.  Nothing is read from disk.  `do` adopts an existing namespace with its
        mounts; adopting the default world's makes this the default world."""
        from .do import Do, _DefaultDo
        from . import dat_tools

        if isinstance(dat_folders, (str, Path)) or not isinstance(dat_folders, (list, tuple)):
            raise TypeError(f"DatManager: dat_folders is a list of folders, got {dat_folders!r}")
        if not dat_folders or not all(isinstance(f, (str, Path)) and str(f) for f in dat_folders):
            raise ValueError(f"DatManager: dat_folders needs at least one folder, got {dat_folders!r}")
        self._dat_folders = [os.path.realpath(str(f)) for f in dat_folders]
        self._config_dir = None
        self._dat_cache = weakref.WeakValueDictionary()

        default = False
        if isinstance(do, _DefaultDo):
            do, default = do._current(), True
        elif do is not None and _default_manager is not None and do is _default_manager.do:
            default = True
        self.do = Do(manager=self) if do is None else do
        self.do._manager = self
        self.do.mount(module=dat_tools, at="dt")
        self.do.mount(value=dat_tools.cmd_list, at="dt.list")
        if default:
            Dat.manager = self

    @classmethod
    def load_dat_config(cls, start: Union[str, Path, None] = None, *,
                        do: Optional["Do"] = None) -> "DatManager":
        """A new manager from the `.datconfig.yaml` found walking up from `start`
        (default the working directory; a config file names itself).

        Precedence, lowest to highest: the file, `.datconfig.override.yaml`, then
        `DAT_FOLDERS` in the environment.  Relative folders resolve against the
        file's folder, which goes first on `sys.path`; with no file they resolve
        against `start`.  An unknown key is `ValueError`.  `do` as in the
        constructor.
        """
        start = Path(start) if start is not None else Path.cwd()
        name = DAT_CONFIG_FILE
        if start.is_file():
            start, name = start.parent, start.name
        config_path = _find_file_up(start, name)
        override_path = _find_file_up(start, DAT_CONFIG_OVERRIDE_FILE)
        values = merge_dicts(_read_config(config_path), _read_config(override_path))
        if (env := os.environ.get(ENV_PREFIX + "FOLDERS")):
            values["dat_folders"] = env
        root = os.path.realpath(config_path.parent if config_path else start)
        folders = values.get("dat_folders", _DEFAULT_DAT_FOLDER)
        folders = [folders] if isinstance(folders, str) else folders
        if not isinstance(folders, list) or not all(isinstance(f, str) and f for f in folders):
            raise ValueError(f"{config_path}: dat_folders is a folder or a list of them, "
                             f"got {values.get('dat_folders')!r}")
        manager = cls(dat_folders=[os.path.join(root, f) for f in folders], do=do)
        manager._config_dir = root
        if root not in sys.path:
            sys.path.insert(0, root)    # the config folder is the import root
        return manager

    def expand(self, text: str, vars: Optional[Dict[str, Any]] = None) -> Any:
        """`expand`, with dotted names resolved through this manager's `do`."""
        return expand(text, vars, resolver=self.do.load)

    def expand_spec(self, spec: Any, vars: Optional[Dict[str, Any]] = None) -> Any:
        """`expand_spec`, with dotted names resolved through this manager's `do`."""
        return expand_spec(spec, vars, resolver=self.do.load)

    def create(
        self,
        spec: Union[Dict, str, None] = None,
        *,
        path: Union[str, Path, None] = None,
    ) -> "Dat":
        """Create a dat, as the class its `dat.kind` names: resolve `dat.base`,
        validate, place it, write `_spec_.yaml`.

        `spec` may be a dict or a dotted name loaded through the do-system.  The
        folder is `path` if given, else the spec's `dat.name` template, else
        `anonymous/Dat{unique}`; `dat.target_exists` says what happens when the
        folder is already there.  Every `{}` in the spec is expanded here, once,
        with the same values the folder got, and the expanded spec is what is
        written: a spec on disk is a record, never a template.  `dat.kind` is
        written as the class's dotted `module.qualname`.
        """
        spec = self._spec_of(spec)
        dat_class = self._class_of(spec["dat"].get("kind"))
        spec["dat"]["kind"] = _kind_name(dat_class)
        spec = dat_class.validate_spec(spec)

        if path is None:
            path = Dat.get(spec, DAT_NAME, None) or _DEFAULT_PATH_TEMPLATE
        path = str(path)
        target_exists = Dat.get(spec, DAT_TARGET_EXISTS, "error")
        if target_exists == "overwrite" and path.lower() == "{cwd}":
            target_exists = "error"  # never wipe the working directory

        expanded_path, skip_execution, names = self._place(path, target_exists=target_exists)
        if skip_execution:
            return self.load(expanded_path)

        path = self._resolve_path(expanded_path)
        spec = self.expand_spec(spec, names)
        if _within(os.path.realpath(path), self._dat_folders[0]):
            Dat.set(spec, DAT_NAME, self._get_path_name(path))
        os.makedirs(path, exist_ok=True)
        logger.info("Creating Dat %s under path: <%s>", dat_class, path)
        try:
            text = yaml.dump(spec, Dumper=_SpecDumper, sort_keys=False)
        except yaml.representer.RepresenterError as e:
            shutil.rmtree(path, ignore_errors=True)
            raise TypeError(
                f"Dat.create: the spec is not data once expanded ({e.args[0]}); a "
                "`{...}` reference in a spec must resolve to something YAML can hold"
            ) from None
        Path(path, SPEC_YAML).write_text(text)
        return self._load(path, dat_class=dat_class)

    def _spec_of(self, spec: Union[Dict, str, None]) -> Dict:
        """A private copy of `spec` (a dict, or a dotted name loaded through `do`),
        merged over its `dat.base`, with a `dat` mapping."""
        if spec is None:
            spec = {}
        if isinstance(spec, str):
            spec = self.do.load(spec)
        if not isinstance(spec, dict):
            raise TypeError(f"Dat.create: spec must be a dict or a dotted name, not {spec!r}")
        spec = self.do._resolve_base(deepcopy(spec))
        if not isinstance(spec.setdefault("dat", {}), dict):
            raise TypeError(f"Dat.create: spec['dat'] is a mapping, got {spec['dat']!r}")
        return spec

    def load(
        self,
        name_or_path: Union[str, Path],
        *,
        cache_after_load: bool = True,
    ) -> "Dat":
        """Load a dat from disk, as the class its `dat.kind` names.

        Searched as an absolute path, in the do-system's mounts, then in each
        dat folder.
        """
        return self._load(name_or_path, cache_after_load=cache_after_load)

    def _load(
        self,
        name_or_path: Union[str, Path],
        *,
        dat_class: Optional[Type["Dat"]] = None,
        cache_after_load: bool = True,
    ) -> "Dat":
        """`load`, with `dat_class` given when the caller already holds the class
        (`create`, `copy`, `move`), so a class that cannot be imported by name --
        one defined inside a function -- still round-trips in this process."""
        name_or_path = str(name_or_path)
        path = self._resolve_path(name_or_path)
        if not os.path.exists(path):
            raise KeyError(
                f"LOAD_DAT: Could not find <{name_or_path!r}> as absolute, "
                f"as a mounted dat, or in {self._dat_folders}"
            )
        path = os.path.abspath(path)
        if (cached := self._dat_cache.get(path)) is not None and (
                dat_class is None or type(cached) is dat_class):
            return cached

        if os.path.exists(spec_path := os.path.join(path, SPEC_YAML)):
            with open(spec_path) as f:
                spec = yaml.safe_load(f)
        elif os.path.exists(spec_path := os.path.join(path, SPEC_JSON)):
            with open(spec_path) as f:
                spec = json.load(f)
        else:
            raise FileNotFoundError(
                f"Didn't find a {SPEC_YAML}/{SPEC_JSON} file under path <{path}>.")
        if not isinstance(spec, dict):
            raise TypeError(f"{spec_path}: a spec is a mapping, got {type(spec).__name__}")

        if dat_class is None:
            dat = spec.get("dat")
            dat_class = self._class_of(dat.get("kind") if isinstance(dat, dict) else None)
        spec = dat_class.validate_spec(spec)

        result: SpecDict = {}
        if os.path.exists(result_path := os.path.join(path, RESULT_YAML)):
            with open(result_path) as f:
                result = yaml.safe_load(f) or {}

        dat = dat_class(path=path, spec=spec, result=result)
        dat._manager = self
        if cache_after_load:
            self._dat_cache[path] = dat
        return dat

    def exists(self, path: Union[str, Path]) -> bool:
        """True if a dat's `_spec_` file is at `path` (resolved like `load`)."""
        path = self._resolve_path(str(path))
        return os.path.exists(os.path.join(path, SPEC_JSON)) or os.path.exists(
            os.path.join(path, SPEC_YAML)
        )

    def _get_path_name(self, path: Union[str, Path]) -> str:
        path = str(path)
        real = os.path.realpath(path)
        for folder in self._dat_folders:
            if real != folder and _within(real, folder):
                return os.path.relpath(real, folder)
        return path

    def execute(self, dat: "Dat") -> Any:
        """Run `dat` as its spec says, and record the run in its results.

        Calls `fn(dat, *dat.args, **dat.kwargs)` with `fn` the object `dat.do`
        names, loaded through this world's `do`; then records `dat.run_at`,
        `dat.run_time` and `dat.code` (the branch, commit and dirty flag of the git
        checkout holding `fn`'s source; nothing outside a checkout) and saves the
        results.  Every run in this world comes here -- `do(...)` and the `do(...)`
        calls nested inside a running function alike -- so a subclass that wraps
        this wraps every run.  Returns `fn`'s value, or `dat` when there is no
        `dat.do`.
        """
        spec = dat.get_spec()
        fn = Dat.get(spec, DAT_DO, None)
        if fn is None:
            return dat
        if isinstance(fn, str):
            fn = self.do.load(fn)
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
        if (code := _code_of(fn)) is not None:
            Dat.set(dat.get_results(), DAT_CODE, code)
        dat.save()
        return result

    def _class_of(self, kind: Optional[str]) -> Type["Dat"]:
        """The class a `dat.kind` names.

        A dotted `module.qualname` is imported, as pickle does; a class that cannot
        be imported is `ImportError`, and one that is not a `Dat` is `TypeError`.
        A bare name -- every dat written before 2.3 -- is found among the loaded
        subclasses of `Dat`, and reads as `Dat` when none has that name.  No kind
        is `Dat`.
        """
        if kind is None:
            return Dat
        if not isinstance(kind, str):
            raise TypeError(f"dat.kind is a dotted class path, got {kind!r}")
        if "." not in kind:
            return _find_subclass_by_name(Dat, kind) or Dat
        parts = kind.split(".")
        for cut in range(len(parts) - 1, 0, -1):     # the longest importable module
            module_name = ".".join(parts[:cut])
            try:
                obj = importlib.import_module(module_name)
            except ModuleNotFoundError as e:
                if e.name and (module_name == e.name or module_name.startswith(e.name + ".")):
                    continue
                raise
            try:
                for attr in parts[cut:]:
                    obj = getattr(obj, attr)
            except AttributeError:
                raise ImportError(f"dat.kind {kind!r}: module {module_name!r} "
                                  f"has no {'.'.join(parts[cut:])!r}") from None
            if not (isinstance(obj, type) and issubclass(obj, Dat)):
                raise TypeError(f"dat.kind {kind!r} is {obj!r}, not a Dat subclass")
            return obj
        raise ImportError(f"dat.kind {kind!r}: no module of it can be imported")

    def _prepare_dat_path(
        self,
        path_spec: Union[str, Path, None],
        *,
        variables: Optional[Dict[str, Any]] = None,
        target_exists: str = "error",
    ) -> Tuple[str, bool]:
        """Expand a path template under the dat folder and settle a collision.

        Returns `(path, skip_execution)`; `skip_execution` is True only for
        `target_exists: use` on an existing folder.  `overwrite` deletes the folder;
        `increment` (or a `{unique}` in the template) counts up `_2`, `_3`, …
        """
        path, skip, _ = self._place(path_spec, variables=variables, target_exists=target_exists)
        return path, skip

    def _place(
        self,
        path_spec: Union[str, Path, None],
        *,
        variables: Optional[Dict[str, Any]] = None,
        target_exists: str = "error",
    ) -> Tuple[str, bool, Dict[str, Any]]:
        """`_prepare_dat_path`, also returning the names the path expanded with, so the
        spec can be expanded with the very same `now` and `unique`."""
        if path_spec is None:
            path_spec = _DEFAULT_PATH_TEMPLATE
        path_spec = str(path_spec)
        if target_exists == "increment" and "{unique}" not in path_spec:
            path_spec += "{unique}"      # a plain name counts up as `_2`, `_3`, ...
        now, count = datetime.now(), 1
        while True:
            names = {**_builtins(now),
                     "unique": "" if count == 1 else f"_{count}",
                     **(variables or {})}
            expanded = self.expand(path_spec, names)
            if not isinstance(expanded, str):
                raise TypeError(
                    f"path template {path_spec!r} expanded to {expanded!r}, "
                    "not a string")
            expanded_path = os.path.join(self._dat_folders[0], expanded)
            if not os.path.exists(expanded_path):
                return expanded_path, False, names
            elif target_exists == "use":
                return expanded_path, True, names
            elif target_exists == "overwrite":
                shutil.rmtree(expanded_path)
                return expanded_path, False, names
            elif target_exists == "increment" or "{unique}" in path_spec:
                count += 1
            else:
                raise FileExistsError(f"DAT: Create failed, dir {expanded_path!r} exists")

    def _resolve_path(self, name: Union[str, Path]) -> str:
        name = str(name)
        if os.path.isabs(name):
            return name
        if (mount_path := self.do._resolve_dat_folder(name)) is not None:
            return mount_path
        for folder in self._dat_folders:
            path = os.path.join(folder, name)
            if os.path.exists(os.path.join(path, SPEC_JSON)) or os.path.exists(
                os.path.join(path, SPEC_YAML)
            ):
                return path
        return os.path.join(self._dat_folders[0], name)


# =============================================================================
# Dat
# =============================================================================

_default_manager: Optional[DatManager] = None


class _DatMeta(type):
    """Gives `Dat` (and every subclass) `manager`, the process's default world:
    a plain assignable class attribute, filled on first read by
    `DatManager.load_dat_config()`.  `Run.manager is Dat.manager`."""

    @property
    def manager(cls) -> DatManager:
        global _default_manager
        if _default_manager is None:
            _default_manager = DatManager.load_dat_config()
        return _default_manager

    @manager.setter
    def manager(cls, value: Optional[DatManager]) -> None:
        global _default_manager
        if value is not None and not isinstance(value, DatManager):
            raise TypeError(f"Dat.manager is a DatManager, got {value!r}")
        if value is not None:
            value.do._manager = value       # its namespace answers to it again
        _default_manager = value


class Dat(metaclass=_DatMeta):
    """A folder of data described by its `_spec_.yaml`.

    The spec is the complete recipe: `dat.do` names the function, `dat.args` and
    `dat.kwargs` its arguments, `dat.name` the path template, `dat.base` what it
    inherited from.  Every `{}` reference in it was expanded once, when the dat was
    created, and `get_spec()` returns it as written.  `get_results()` is the
    mutable `_result_.yaml`.

    Subclasses override `validate_spec` to check or coerce a spec on create and load
    (a schema library inside it is the subclass's choice and dependency).
    """

    @property
    def manager(self) -> DatManager:
        """The world this dat belongs to: the manager that loaded it, else the default.
        (`Dat.manager` on the class is the default world; see `_DatMeta`.)"""
        return self._world()

    _path: str
    _spec: SpecDict
    _result: SpecDict
    _manager: Optional[DatManager]      # the world this dat was loaded by, if any

    def __init__(
        self,
        path: Union[str, Path],
        spec: Optional[SpecDict] = None,
        result: Optional[SpecDict] = None,
    ) -> None:
        if spec is None or not isinstance(path, (str, Path)):
            raise TypeError(
                f"{type(self).__name__}(...) is not how a dat is made: "
                f"Dat.create(spec=...) makes one on disk, Dat.load(path) reads one")
        self._path = os.path.abspath(str(path))
        self._spec = spec
        self._result = result or {}
        self._manager = None

    def _world(self) -> DatManager:
        """The manager that loaded this dat, else the default one."""
        return self._manager if self._manager is not None else Dat.manager

    @classmethod
    def validate_spec(cls, spec: SpecDict) -> SpecDict:
        """Check a spec before it is written or loaded; return it (possibly coerced).

        The default checks the shape every dat relies on: a mapping with a `dat`
        mapping whose string fields are strings (a `{reference}` written unquoted in
        YAML arrives as a dict — that is the error this catches).
        """
        if not isinstance(spec, dict):
            raise TypeError(f"{cls.__name__}: a spec is a mapping, got {type(spec).__name__}")
        dat = spec.setdefault("dat", {})
        if not isinstance(dat, dict):
            raise TypeError(f"{cls.__name__}: spec['dat'] is a mapping, got {type(dat).__name__}")
        dat.setdefault("kind", _kind_name(cls))
        for key in ("kind", "name", "do", "target_exists"):
            if key in dat and dat[key] is not None and not isinstance(dat[key], str):
                raise TypeError(
                    f"{cls.__name__}: dat.{key} is a string, got {dat[key]!r} "
                    f"(a value starting with '{{' must be quoted in YAML)"
                )
        return spec

    def get_spec(self) -> SpecDict:
        """The spec as written -- every `{}` was expanded once, when the dat was created."""
        return self._spec

    def get_results(self) -> SpecDict:
        """The mutable results of this Dat (persisted by `save()`)."""
        return self._result

    def get_path(self) -> str:
        return self._path

    def get_path_name(self) -> str:
        """The name (path relative to its dat folder) of this Dat."""
        return self._world()._get_path_name(self._path)

    @classmethod
    def load(
        cls: Type[DatType],
        name_or_path: Union[str, Path],
        *,
        cache_after_load: bool = True,
    ) -> DatType:
        """Load the dat at `name_or_path` in the default world, as the class its
        `dat.kind` names; `TypeError` unless that is `cls` or a subclass of it."""
        dat = cls.manager.load(name_or_path, cache_after_load=cache_after_load)
        return cls._require(dat, f"{cls.__name__}.load({str(name_or_path)!r})")

    @classmethod
    def create(
        cls: Type[DatType],
        path: Optional[Union[str, Path]] = None,
        spec: Union[Dict, str, None] = None,
    ) -> DatType:
        """Create a dat at `path` (or the spec's `dat.name` template) from `spec`, in
        the default world.  A spec with no `dat.kind` gets `cls`; one naming a class
        outside `cls` is `TypeError` before anything is written."""
        manager = cls.manager
        spec = manager._spec_of(spec)
        kind = spec["dat"].get("kind")
        if kind is None:
            spec["dat"]["kind"] = _kind_name(cls)
        elif not issubclass(named := manager._class_of(kind), cls):
            raise TypeError(f"{cls.__name__}.create: dat.kind {kind!r} is "
                            f"{named.__name__}, not a {cls.__name__}")
        return cls._require(manager.create(spec, path=path), f"{cls.__name__}.create")

    @classmethod
    def _require(cls: Type[DatType], dat: "Dat", what: str) -> DatType:
        if not isinstance(dat, cls):
            raise TypeError(f"{what}: {dat!r} is a {type(dat).__name__}, not a {cls.__name__}")
        return dat

    def save(self) -> None:
        """Write the results to `_result_.yaml`."""
        if self._result:
            with Path(self.get_path(), RESULT_YAML).open("w") as out:
                yaml.dump(self._result, out, Dumper=_SpecDumper, sort_keys=False)

    def delete(self, *, must_exist=True) -> bool:
        """Delete the folder and its contents."""
        self._world()._dat_cache.pop(self._path, None)
        try:
            shutil.rmtree(self._path)
        except FileNotFoundError:
            if must_exist:
                raise Exception(f"DAT DELETE: Folder missing {self._path!r}.")
            return False
        return True

    def copy(self: DatType, new_path: Union[str, Path]) -> DatType:
        manager = self._world()
        new_path_ = manager._resolve_path(new_path)
        if os.path.exists(new_path_):
            raise Exception(f"DAT COPY: Folder exists {new_path!r}.")
        shutil.copytree(self._path, new_path_)
        return manager._load(new_path_, dat_class=type(self))

    def move(self: DatType, new_path: Union[str, Path]) -> DatType:
        manager = self._world()
        manager._dat_cache.pop(self._path, None)
        new_path_ = manager._resolve_path(new_path)
        if os.path.exists(new_path_):
            raise Exception(f"DAT MOVE: Folder exists {new_path!r}.")
        shutil.move(self._path, new_path_)
        return manager._load(new_path_, dat_class=type(self))

    def __repr__(self):
        return f"<{type(self).__name__}: {self.get_path_name()}>"

    def __str__(self):
        return self.__repr__()

    @staticmethod
    def get(source: Union["Dat", dict], keys: Union[str, List[str]],
            default_value: Any = _NO_ARG) -> Any:
        """Get a value from a dotted key path in a dict tree (or a Dat's spec)."""
        return _dotted_get(source=source, keys=keys, default_value=default_value)

    @staticmethod
    def set(source: SpecDict, keys, value) -> None:
        """Set a value at a dotted key path in a dict tree, creating levels as needed."""
        _dotted_set(source=source, keys=keys, value=value)


class DatContainer(Dat, Generic[DatType]):
    """A Dat whose folder holds other Dats, exposed through `get_dats()` / `get_dat_paths()`."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._dat_paths: Union[_DataState, List[str]] = _DataState.NOT_LOADED
        self._dats: Union[_DataState, List[DatType]] = _DataState.NOT_LOADED

    def get_dat_paths(self) -> List[str]:
        """Lazy loaded list of full paths for the contained Dats."""
        if self._dat_paths is _DataState.NOT_LOADED:
            self._dat_paths = DatContainer._find_dats_under(self._path)
        return self._dat_paths

    def get_dats(self) -> List[DatType]:
        """The contained Dats (all stay in memory until this container is released)."""
        if self._dats is _DataState.NOT_LOADED:
            manager = self._world()
            self._dats = [manager.load(p) for p in self.get_dat_paths()]  # type: ignore
        return self._dats  # type: ignore

    @staticmethod
    def _find_dats_under(root_path: Union[str, Path]):
        root_path = str(root_path)
        results = []
        for root, dirs, files in os.walk(root_path):
            for name in files:
                if name == SPEC_JSON or name == SPEC_YAML:
                    results.append(os.path.dirname(os.path.join(root, name)))
        results.sort()
        assert os.path.abspath(results[0]) == os.path.abspath(root_path)
        del results[0]
        return results


# =============================================================================
# Dotted-key helpers
# =============================================================================

def _dotted_get(source: Union[Dat, dict], keys: Union[str, List[str]], default_value: Any = _NO_ARG):
    d = source.get_spec() if isinstance(source, Dat) else source
    if isinstance(keys, str):
        keys = keys.split(".")
    for k in keys:
        if d is None:
            result = None
            break
        elif not isinstance(d, dict):
            raise ValueError(f"GET: Expected dict value for {k!r} not {d!r}")
        else:
            d = d.get(k)
    else:
        result = d
    if result is not None:
        return result
    elif default_value is _NO_ARG:
        raise KeyError(f"GET: Key {keys} not found in {source!r}")
    else:
        return default_value


def _dotted_set(source: SpecDict, keys, value):
    assert source is not None, "set method requires a non None dict"
    assert len(keys) > 0, "set method requires at least one key"
    if isinstance(keys, str):
        keys = keys.split(".")
    for k in keys[:-1]:
        if not isinstance(source, dict):
            raise Exception(f"Expected dict value for {k!r} not {source!r}")
        sub = source.get(k)
        if sub is None:
            sub = source[k] = {}
        source = sub
    source[keys[-1]] = value

