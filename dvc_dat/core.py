"""dvc_dat core: configuration, the Dat manager, Dat, and spec expansion.

A Dat is a folder carrying a `_spec_.yaml` that is a complete, argumentless recipe
for itself, plus a `_result_.yaml` holding what running it produced.  The do-system
(`dvc_dat.do`) runs specs; this module stores and loads them.
"""

import json
import logging
import os
import re
import shutil
import weakref
from copy import deepcopy
from dataclasses import dataclass, field, fields
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

DATA_CONFIG_FILE = ".dataconfig.yaml"
DATA_CONFIG_OVERRIDE_FILE = ".dataconfig.override.yaml"
ENV_PREFIX = "DAT_"


@dataclass
class DataConfig:
    """Where dats are stored, and what the do-system mounts.

    Attributes
    ----------
    cwd : folder the config was found in (or given); relative paths resolve against it.
    local_prefix : the sync folder — where relative dat paths are created and searched.
    extra_local_prefixes : further folders searched when loading a dat by name.
    main : a module imported when the config installs, with the config folder
        first on `sys.path`.  Mounts and any other registration live there.
    python : the interpreter the `bin/dat` bootstrap runs -- a path to one, or a
        folder holding `bin/python`; relative to `cwd`.  Nothing in the library
        reads it; the bootstrap does.
    """

    cwd: str
    local_prefix: str = "data/"
    extra_local_prefixes: List[str] = field(default_factory=list)
    main: Optional[str] = None
    python: Optional[str] = None

    @classmethod
    def field_names(cls) -> List[str]:
        return [f.name for f in fields(cls)]

    @classmethod
    def new(
        cls,
        cwd: Optional[Union[str, Path]] = None,
        config_name: str = DATA_CONFIG_FILE,
        config_override_name: str = DATA_CONFIG_OVERRIDE_FILE,
        override_values: Optional[Dict[str, Any]] = None,
        verbose: bool = False,
    ) -> "DataConfig":
        """Create a DataConfig by searching for config files up the directory tree.

        Precedence, lowest to highest: `config_name`, `config_override_name`,
        `override_values`, then `DAT_<KEY>` environment variables.  Discovery walks up
        from `cwd` when given, else from the process's working directory.
        """
        if cwd:
            cwd = str(cwd)
        if override_values is None:
            override_values = {}

        search_root = Path(cwd) if cwd else Path.cwd()
        config_path = cls._find_file_up(search_root, config_name)
        config_override_path = cls._find_file_up(search_root, config_override_name)

        config_values = cls._read(config_path, verbose)
        config_override_values = cls._read(config_override_path, verbose)

        if not cwd:
            cwd = str(config_path.parent) if config_path else str(Path.cwd())

        # Only DAT_<FIELD> variables reach the config (DAT_LOCAL_PREFIX -> local_prefix).
        environ_values = {
            key[len(ENV_PREFIX):].lower(): value
            for key, value in os.environ.items()
            if key.startswith(ENV_PREFIX) and key[len(ENV_PREFIX):].lower() in cls.field_names()
        }

        final_values: Dict[str, Any] = merge_dicts(
            config_values, config_override_values, override_values, environ_values, {"cwd": cwd},
        )
        return cls(**final_values)

    @classmethod
    def _read(cls, path: Optional[Path], verbose: bool) -> Dict[str, Any]:
        if not path:
            return {}
        with path.open("r") as f:
            values = yaml.safe_load(f) or {}
        if not isinstance(values, dict):
            raise ValueError(
                f"{path}: expected a mapping of config keys, "
                f"got {type(values).__name__}")
        unknown = sorted(set(values) - set(cls.field_names()))
        if unknown:
            raise ValueError(
                f"{path}: unknown config key(s) {unknown}; known keys are {cls.field_names()}"
            )
        if verbose:
            logger.debug("%s found and loaded.", path)
        return values

    @staticmethod
    def _find_file_up(path: Union[str, Path], file_name: str) -> Optional[Path]:
        """Look for `file_name` in `path` and each of its parents."""
        path = Path(path).absolute()
        prev_path: Optional[Path] = None
        while prev_path != path:
            candidate = path / file_name
            if candidate.exists():
                return candidate
            prev_path = path
            path = path.parent
        return None

    def __post_init__(self) -> None:
        """Make every path in the config absolute."""
        self.cwd = os.path.realpath(self.cwd)
        if not os.path.isabs(self.local_prefix):
            self.local_prefix = os.path.join(self.cwd, self.local_prefix)
        self.local_prefix = os.path.normpath(self.local_prefix)
        if not self.local_prefix.endswith("/"):
            self.local_prefix += "/"
        if self.python and not os.path.isabs(self.python):
            self.python = os.path.normpath(os.path.join(self.cwd, self.python))


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

_DEFAULT_PATH_TEMPLATE = "anonymous/Dat{unique}"
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


class classproperty:
    """Decorator for class-level properties (like @property but for the class itself)."""
    def __init__(self, func):
        self.func = func

    def __get__(self, obj, objtype=None):
        return self.func(objtype)


class DataState(Enum):
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
            from .do import do
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
    the referenced object itself, not its string form.
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
        return str(resolve(match.group(1)))

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
    """Singleton that creates, finds and loads dats under the sync folder.

    Reached as `Dat.manager`.  Built lazily from `DataConfig.new()` (discovery walks up
    from the process's working directory) or explicitly by `do.configure(...)`.
    """

    config: DataConfig
    main_sync_folder: str
    sync_folders: List[str]
    dat_cache: "weakref.WeakValueDictionary[str, Dat]"

    @property
    def sync_folder(self) -> str:
        return self.main_sync_folder

    def __init__(self, config: Optional[DataConfig] = None):
        if config is None:
            config = DataConfig.new()
        self.config = config
        self.main_sync_folder = config.local_prefix
        self.sync_folders = [self.main_sync_folder, *config.extra_local_prefixes]
        self.dat_cache = weakref.WeakValueDictionary()
        assert self.main_sync_folder, "Sync folder not defined."

    def create(
        self,
        dat_class: Type[DatType],
        *,
        path: Union[str, Path, None] = None,
        spec: Union[Dict, str, None] = None,
    ) -> DatType:
        """Create a dat: resolve `dat.base`, validate, place it, write `_spec_.yaml`.

        `spec` may be a dict or a dotted name loaded through the do-system.  The
        folder is `path` if given, else the spec's `dat.name` template, else
        `anonymous/Dat{unique}`; templates expand with the `{}` grammar and
        `dat.target_exists` says what happens when the folder is already there.
        """
        from .do import do

        if spec is None:
            spec = {"dat": {"kind": dat_class.__name__}}
        if isinstance(spec, str):
            spec = do.load(spec)
        if not isinstance(spec, dict):
            raise TypeError(f"Dat.create: spec must be a dict or a dotted name, not {spec!r}")
        spec = do.resolve_base(deepcopy(spec))
        spec.setdefault("dat", {})
        spec["dat"].setdefault("kind", dat_class.__name__)
        spec = dat_class.validate_spec(spec)

        if path is None:
            path = Dat.get(spec, DAT_NAME, None) or _DEFAULT_PATH_TEMPLATE
        path = str(path)
        target_exists = Dat.get(spec, DAT_TARGET_EXISTS, "error")
        if target_exists == "overwrite" and path.lower() == "{cwd}":
            target_exists = "error"  # never wipe the working directory

        expanded_path, skip_execution = self.prepare_dat_path(path, target_exists=target_exists)
        if skip_execution:
            return self.load(dat_class, name_or_path=expanded_path)

        path = self.resolve_path(expanded_path)
        os.makedirs(path, exist_ok=True)
        logger.info("Creating Dat %s under path: <%s>", dat_class, path)
        with Path(path, SPEC_YAML).open("w") as f:
            yaml.dump(spec, f, Dumper=_SpecDumper, sort_keys=False)
        return self.load(dat_class, name_or_path=path)

    def load(
        self,
        dat_class: Type[DatType],
        name_or_path: Union[str, Path],
        *,
        cwd: Optional[str] = None,
        cache_after_load: bool = True,
    ) -> DatType:
        """Load a dat from disk, as the class its `dat.kind` names.

        Searched as an absolute path, under the config folder, in the do-system's
        mounts, then in each sync folder.
        """
        name_or_path = str(name_or_path)
        cwd = cwd or os.getcwd()
        path = self.resolve_path(name_or_path)
        if not os.path.exists(path):
            raise KeyError(
                f"LOAD_DAT: Could not find <{name_or_path!r}> as absolute, "
                f"under cwd {cwd}, or in {self.sync_folders}"
            )
        path = os.path.abspath(path)
        if (cached := self.dat_cache.get(path)) and isinstance(cached, dat_class):
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

        kind = Dat.get(spec, DAT_KIND, "Dat")
        dat_class_name = dat_class.__name__
        if dat_class_name == "Dat" and kind != "Dat":
            actual_class = self._find_subclass_by_name(dat_class, kind)
            if actual_class:
                dat_class = actual_class
        elif dat_class_name != "Dat" and kind != dat_class_name:
            raise ValueError(
                f"Spec 'dat.kind' <{kind}> doesn't match <{dat_class_name}>. "
                "Update the spec accordingly and instantiate with the correct class "
                "(or the generic Dat)."
            )
        spec = dat_class.validate_spec(spec)

        result: SpecDict = {}
        if os.path.exists(result_path := os.path.join(path, RESULT_YAML)):
            with open(result_path) as f:
                result = yaml.safe_load(f) or {}

        dat = dat_class(path=path, spec=spec, result=result)
        if cache_after_load:
            self.dat_cache[path] = dat
        return dat

    def exists(self, path: Union[str, Path]) -> bool:
        """True if a dat's `_spec_` file is at `path` (resolved like `load`)."""
        path = self.resolve_path(str(path))
        return os.path.exists(os.path.join(path, SPEC_JSON)) or os.path.exists(
            os.path.join(path, SPEC_YAML)
        )

    def get_path_name(self, path: Union[str, Path]) -> str:
        path = str(path)
        try:
            match = 1 + len(os.path.commonpath([self.main_sync_folder, path]))
            return path[match:] if match > 2 else path
        except ValueError:
            return path

    @staticmethod
    def get_path_tail(path: Union[str, Path]) -> str:
        return str(path).split("/")[-1]

    def _find_subclass_by_name(self, klass: Type, name: str) -> Optional[Type]:
        if klass.__name__ == name:
            return klass
        for sub in klass.__subclasses__():
            if result := self._find_subclass_by_name(sub, name):
                return result
        return None

    def prepare_dat_path(
        self,
        path_spec: Union[str, Path, None],
        *,
        variables: Optional[Dict[str, Any]] = None,
        target_exists: str = "error",
    ) -> Tuple[str, bool]:
        """Expand a path template under the sync folder and settle a collision.

        Returns `(path, skip_execution)`; `skip_execution` is True only for
        `target_exists: use` on an existing folder.  `overwrite` deletes the folder;
        `increment` (or a `{unique}` in the template) counts up `_2`, `_3`, …
        """
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
            expanded = expand(path_spec, names)
            if not isinstance(expanded, str):
                raise TypeError(
                    f"path template {path_spec!r} expanded to {expanded!r}, "
                    "not a string")
            expanded_path = os.path.join(self.main_sync_folder, expanded)
            if not os.path.exists(expanded_path):
                return expanded_path, False
            elif target_exists == "use":
                return expanded_path, True
            elif target_exists == "overwrite":
                shutil.rmtree(expanded_path)
                return expanded_path, False
            elif target_exists == "increment" or "{unique}" in path_spec:
                count += 1
            else:
                raise FileExistsError(f"DAT: Create failed, dir {expanded_path!r} exists")

    def resolve_path(self, name: Union[str, Path]) -> str:
        from .do import do

        name = str(name)
        if os.path.isabs(name):
            return name
        path = os.path.join(self.config.cwd, name)
        if os.path.exists(path):
            return path
        if (mount_path := do.resolve_dat_folder(name)) is not None:
            return mount_path
        for folder in self.sync_folders:
            path = os.path.join(folder, name)
            if os.path.exists(os.path.join(path, SPEC_JSON)) or os.path.exists(
                os.path.join(path, SPEC_YAML)
            ):
                return path
        return os.path.join(self.main_sync_folder, name)


# =============================================================================
# Dat
# =============================================================================

class Dat:
    """A folder of data described by its `_spec_.yaml`.

    The spec is the complete recipe: `dat.do` names the function, `dat.args` and
    `dat.kwargs` its arguments, `dat.name` the path template, `dat.base` what it
    inherits from.  `get_spec()` returns it with every `{}` reference expanded (once,
    lazily); `get_spec(raw=True)` is the file as written.  `get_results()` is the
    mutable `_result_.yaml`.

    Subclasses override `validate_spec` to check or coerce a spec on create and load
    (a schema library inside it is the subclass's choice and dependency).
    """

    _manager: Optional[DatManager] = None

    @classproperty
    def manager(cls) -> DatManager:
        if Dat._manager is None:
            from .do import do
            do._ensure_configured()          # also builds Dat._manager
        if Dat._manager is None:
            Dat._manager = DatManager()
        return Dat._manager

    _path: str
    _spec: SpecDict
    _expanded: Optional[SpecDict]
    _result: SpecDict

    def __init__(
        self,
        path: Union[str, Path],
        spec: SpecDict,
        result: Optional[SpecDict] = None,
    ) -> None:
        self._path = os.path.abspath(str(path))
        self._spec = spec
        self._expanded = None
        self._result = result or {}

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
        dat.setdefault("kind", cls.__name__)
        for key in ("kind", "name", "do", "target_exists"):
            if key in dat and dat[key] is not None and not isinstance(dat[key], str):
                raise TypeError(
                    f"{cls.__name__}: dat.{key} is a string, got {dat[key]!r} "
                    f"(a value starting with '{{' must be quoted in YAML)"
                )
        return spec

    def get_spec(self, raw: bool = False) -> SpecDict:
        """The spec, with every `{}` reference expanded (cached) — or as written."""
        if raw:
            return self._spec
        if self._expanded is None:
            self._expanded = expand_spec(self._spec)
        return self._expanded

    @property
    def spec(self) -> SpecDict:
        return self.get_spec()

    def get_results(self) -> SpecDict:
        """The mutable results of this Dat (persisted by `save()`)."""
        return self._result

    def get_path(self) -> str:
        return self._path

    def get_path_name(self) -> str:
        """The name (path relative to the sync folder) of this Dat."""
        return Dat.manager.get_path_name(self._path)

    def get_path_tail(self) -> str:
        return self._path.split("/")[-1]

    @classmethod
    def load(
        cls: Type[DatType],
        name_or_path: Union[str, Path],
        cwd: Optional[str] = None,
        cache_after_load: bool = True,
    ) -> DatType:
        """Load the dat at `name_or_path`; its `dat.kind` must match `cls` (or use `Dat`)."""
        return cls.manager.load(cls, str(name_or_path), cwd=cwd, cache_after_load=cache_after_load)

    @classmethod
    def create(
        cls: Type[DatType],
        path: Optional[Union[str, Path]] = None,
        spec: Union[Dict, str, None] = None,
    ) -> DatType:
        """Create a dat at `path` (or the spec's `dat.name` template) from `spec`."""
        return cls.manager.create(cls, path=path, spec=spec)

    def save(self) -> None:
        """Write the results to `_result_.yaml`."""
        if self._result:
            with Path(self.get_path(), RESULT_YAML).open("w") as out:
                yaml.dump(self._result, out, Dumper=_SpecDumper, sort_keys=False)

    def delete(self, *, must_exist=True) -> bool:
        """Delete the folder and its contents."""
        Dat.manager.dat_cache.pop(self._path, None)
        try:
            shutil.rmtree(self._path)
        except FileNotFoundError:
            if must_exist:
                raise Exception(f"DAT DELETE: Folder missing {self._path!r}.")
            return False
        return True

    def copy(self: DatType, new_path: Union[str, Path]) -> DatType:
        new_path_ = Dat.manager.resolve_path(new_path)
        if os.path.exists(new_path_):
            raise Exception(f"DAT COPY: Folder exists {new_path!r}.")
        shutil.copytree(self._path, new_path_)
        return Dat.manager.load(type(self), new_path_)

    def move(self: DatType, new_path: Union[str, Path]) -> DatType:
        Dat.manager.dat_cache.pop(self._path, None)
        new_path_ = Dat.manager.resolve_path(new_path)
        if os.path.exists(new_path_):
            raise Exception(f"DAT MOVE: Folder exists {new_path!r}.")
        shutil.move(self._path, new_path_)
        return Dat.manager.load(type(self), new_path_)

    def __repr__(self):
        kind = Dat.get(self._spec, DAT_KIND, self.__class__.__name__)
        return f"<{kind}: {self.get_path_name()}>"

    def __str__(self):
        return self.__repr__()

    @staticmethod
    def get(source: Union["Dat", dict], keys: Union[str, List[str]],
            default_value: Any = _NO_ARG) -> Any:
        """Get a value from a dotted key path in a dict tree (or a Dat's spec)."""
        return dotted_get(source=source, keys=keys, default_value=default_value)

    @staticmethod
    def set(source: SpecDict, keys, value) -> None:
        """Set a value at a dotted key path in a dict tree, creating levels as needed."""
        dotted_set(source=source, keys=keys, value=value)

    @staticmethod
    def gets(source: Union["Dat", SpecDict], *dotted_keys) -> List[Any]:
        return dotted_gets(source, *dotted_keys)

    @staticmethod
    def sets(source: dict, *assignments) -> None:
        """Apply `key.sub=value` assignments to a dict tree (values parsed as int, float, str)."""
        dotted_sets(source, *assignments)


class DatContainer(Dat, Generic[DatType]):
    """A Dat whose folder holds other Dats, exposed through `get_dats()` / `get_dat_paths()`."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._dat_paths: Union[DataState, List[str]] = DataState.NOT_LOADED
        self._dats: Union[DataState, List[DatType]] = DataState.NOT_LOADED

    def get_dat_paths(self) -> List[str]:
        """Lazy loaded list of full paths for the contained Dats."""
        if self._dat_paths is DataState.NOT_LOADED:
            self._dat_paths = DatContainer._find_dats_under(self._path)
        return self._dat_paths

    def get_dats(self) -> List[DatType]:
        """The contained Dats (all stay in memory until this container is released)."""
        if self._dats is DataState.NOT_LOADED:
            self._dats = [Dat.load(p) for p in self.get_dat_paths()]  # type: ignore
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

def dotted_get(source: Union[Dat, dict], keys: Union[str, List[str]], default_value: Any = _NO_ARG):
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


def dotted_gets(source: Union[Dat, SpecDict], *dotted_keys):
    assert source is not None, "gets method requires a non None dict"
    source_ = source.get_spec() if isinstance(source, Dat) else source
    return [dotted_get(source_, dotted_key.split(".")) for dotted_key in dotted_keys]


def dotted_set(source: SpecDict, keys, value):
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


def dotted_sets(source: dict, *assignments):
    assert source is not None, "set method requires a non None dict"
    for assignment in assignments:
        prefix, suffix = assignment.split("=")
        keys, suffix = prefix.strip().split("."), suffix.strip()
        try:
            value = int(suffix)
        except ValueError:
            try:
                value = float(suffix)
            except ValueError:
                value = suffix
        dotted_set(source, keys, value)
