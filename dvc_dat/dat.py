import importlib
import json
import logging
import os
import shutil
import time
import weakref
from abc import abstractmethod
from copy import deepcopy
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    Iterable,
    List,
    Optional,
    Protocol,
    Self,
    Tuple,
    Type,
    Union,
)

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import TypeVar


# =============================================================================
# Utility functions (merged from utils.py)
# =============================================================================

def merge_dicts(
    *dicts: Dict,
    inplace: bool = False,
) -> Dict:
    """Recursively merge N dicts, with each dict having priority over the previous one."""
    if len(dicts) == 1:
        return dicts[0]

    dict_1 = dicts[0]
    if not inplace:
        dict_1 = deepcopy(dict_1)

    dict_2 = dicts[1]
    for k, v in dict_2.items():
        if isinstance(v, dict):
            dict_1[k] = merge_dicts(dict_1.get(k, {}), v)
        else:
            dict_1[k] = v
    return merge_dicts(dict_1, *dicts[2:])


def dynamic_load_fn(fn_string: str) -> Callable:
    """Dynamically load the function `fn_string`. It must be specified as 'module.fn'."""
    try:
        fn_mod_str, fn_str = fn_string.rsplit(".", maxsplit=1)
    except Exception:
        raise ValueError("Function must be specified as: my_module.my_fn")
    module = importlib.import_module(fn_mod_str)
    try:
        fn: Callable = getattr(module, fn_str)
    except Exception:
        raise AttributeError(f"Function {fn_str} not found in module {module}.")
    return fn


def load_dict(conf_path: Optional[Union[str, Path]]) -> Optional[Dict[str, Any]]:
    """Load either a json or yaml file into a dict."""
    if conf_path is None:
        return None

    conf = None
    conf_path = Path(conf_path)
    if not conf_path.exists():
        return conf
    try:
        with conf_path.open("r") as f:
            if ".json" in conf_path.suffixes:
                conf = json.load(f)
            if ".yaml" in conf_path.suffixes or ".yml" in conf_path.suffixes:
                conf = yaml.safe_load(f)
    except Exception:
        return None
    return conf


# =============================================================================
# Configuration (merged from config.py)
# =============================================================================

DATA_CONFIG_FILE = ".dataconfig.yaml"
DATA_CONFIG_OVERRIDE_FILE = ".dataconfig.override.yaml"


class DataConfig(BaseModel):
    """Container for data-related configuration.

    Attributes
    ----------
    cwd : Cwd used for operations that involve the local filesystem.
    default_remote : Default protocol that will be used for remote operations.
    remote_prefix : Prefix that will be added to remote URIs when object paths are relative.
    local_prefix : Prefix that will be added to local URIs when object paths are relative.
    """

    cwd: str

    default_remote: str = "gs"
    remote_prefix: str = "sv-ai-data/"
    local_prefix: str = "data/"
    extra_local_prefixes: List[str] = Field(default_factory=list)
    dat: Dict[str, Any] = Field(default_factory=dict)

    # Mount commands for the "do" system. If None, do_fn.py is not loaded (standalone mode).
    mount_commands: Optional[List[Dict[str, Any]]] = None

    @classmethod
    def new(
        cls,
        cwd: Optional[Union[str, Path]] = None,
        config_name: str = DATA_CONFIG_FILE,
        config_override_name: str = DATA_CONFIG_OVERRIDE_FILE,
        override_values: Optional[Dict[str, Any]] = None,
        verbose: bool = False,
    ) -> "DataConfig":
        """Create a DataConfig by searching for config files up the directory tree."""
        if cwd:
            cwd = str(cwd)
        if override_values is None:
            override_values = {}

        config_path = cls._find_file_up(Path.cwd(), config_name)
        config_override_path = cls._find_file_up(Path.cwd(), config_override_name)

        config_values = {}
        if config_path:
            with config_path.open("r") as f:
                config_values = yaml.safe_load(f)
            if verbose:
                logger.debug("%s found and loaded.", config_path)

        config_override_values = {}
        if config_override_path:
            with config_override_path.open("r") as f:
                config_override_values = yaml.safe_load(f)

        if not cwd:
            if config_path:
                cwd = str(config_path.parent)
            else:
                cwd = str(Path.cwd())

        environ_values = dict(os.environ)

        final_values: Dict[str, Any] = merge_dicts(
            config_values,
            config_override_values,
            override_values,
            environ_values,
            {"cwd": cwd},
        )

        return cls(**final_values)

    @staticmethod
    def _find_file_up(
        path: Union[str, Path],
        file_name: str,
    ) -> Optional[Path]:
        """Look for a file with name `file_name` in the CWD and its parents."""
        path = Path(path)
        path = path.absolute()

        file: Optional[Path] = None
        prev_path: Optional[Path] = None

        while prev_path != path:
            file = next(path.glob(file_name), None)
            if file:
                break
            prev_path = path
            path = path.parent
        return file

    @model_validator(mode="after")
    def resolve_paths(self) -> Self:
        """Make every path used in the config absolute to avoid ambiguity."""
        self.cwd = os.path.realpath(self.cwd)

        if not os.path.isabs(self.remote_prefix):
            self.remote_prefix = os.path.join("/", self.remote_prefix)
        if not self.remote_prefix.endswith("/"):
            self.remote_prefix += "/"

        if not os.path.isabs(self.local_prefix):
            self.local_prefix = os.path.join(self.cwd, self.local_prefix)
        self.local_prefix = os.path.normpath(self.local_prefix)
        if not self.local_prefix.endswith("/"):
            self.local_prefix += "/"
        return self


# =============================================================================
# Dat module constants and types
# =============================================================================

_DAT_BASE = "dat.base"
_DEFAULT_PATH_TEMPLATE = "anonymous/Dat{unique}"
_NO_ARG = object()

SPEC_JSON = "_spec_.json"
SPEC_YAML = "_spec_.yaml"
RESULT_YAML = "_result_.yaml"

logger = logging.getLogger(__name__)


class classproperty:
    """Decorator for class-level properties (like @property but for the class itself)."""
    def __init__(self, func):
        self.func = func

    def __get__(self, obj, objtype=None):
        return self.func(objtype)


class DataState(Enum):
    NOT_LOADED = auto()


PathLike = Union[str, Path]

# A SpecValue is possibly recursive dict of parameters within the Dat's spec.
# Often it is a dict of dict, but single level is ok as long as keys are
# strings.  The spec is stored in the _spec_ file.
SpecValue = Union[str, int, float, bool, None, "SpecDict"]
SpecDict = Dict[str, SpecValue]

DatSpecType_co = TypeVar(
    "DatSpecType_co",
    bound="DatSpec",
    default="DatSpec",
    covariant=True,
)
DatType = TypeVar("DatType", bound="Dat")
DatMethodType = TypeVar("DatMethodType", bound="DatMethod")


class DatMethod(Protocol):
    """Method that acts on a Dat to produce a result."""

    def __call__(self, dat: "Dat", *args: Any, **kwds: Any) -> Any: ...


class MethodManager:
    """Manages a namespace of DatMethods that are  indexed by String"""

    @abstractmethod
    def __call__(self, name: str, *args, **kwargs) -> Any: ...

    @abstractmethod
    def mount(self, *args, **kwargs) -> None: ...

    @abstractmethod
    def load(
        self,
        name: str,
        *,
        default: Optional[DatMethodType] = None,
    ) -> Union[DatMethodType, DatMethod]: ...

    @abstractmethod
    def keys(self) -> Iterable[str]: ...


class SimpleMethodManager(MethodManager):
    """Manager for cached access to DatMethods."""

    def __init__(self):
        self._dat_methods: Dict[str, DatMethod] = {}

    def __call__(self, name, *args, **kwargs):
        return self._dat_methods[name](*args, **kwargs)

    def load(
        self,
        name: str,
        *,
        default: Optional[DatMethodType] = None,
    ) -> Union[DatMethodType, DatMethod]:
        if name in self._dat_methods:
            return self._dat_methods[name]
        elif default is not None:
            return default
        else:
            raise KeyError(f"Do method {name!r} not found.")

    def mount(self, value: DatMethod, at: str):
        self._dat_methods[at] = value

    def keys(self):
        return self._dat_methods.keys()


# TODO: use Path for everything instead of os.path
class DatManager:
    """Singleton class that manages the configuration and loading of Dats.

    Configuration info for the 'dat' module loaded from a DataConfig.
    """

    config: DataConfig
    main_sync_folder: str
    sync_folders: List[str]  # NOTE: includes the main_sync_folder
    do: MethodManager = SimpleMethodManager()
    dat_cache: weakref.WeakValueDictionary[str, "Dat"] = weakref.WeakValueDictionary()

    @property
    def sync_folder(self) -> str:
        """Backward compatibility: alias for main_sync_folder."""
        return self.main_sync_folder

    def __init__(self, config: Optional[DataConfig] = None):
        if config is None:
            config = DataConfig.new()

        self.config = config

        self.main_sync_folder = self.config.local_prefix
        self.sync_folders = [self.main_sync_folder, *self.config.extra_local_prefixes]
        self.dat_cache = weakref.WeakValueDictionary()

        assert self.main_sync_folder, "Sync folder not defined."

        # Initialize do manager based on config
        if config.mount_commands is not None:
            from .do_fn import create_do_manager
            self.do = create_do_manager(config)
        else:
            self.do = SimpleMethodManager()

    def create(
        self,
        dat_class: Type[DatType],
        *,
        path: Union[str, Path, None] = None,
        spec: Union["DatSpec", Dict, None] = None,
        overwrite: bool = False,
    ) -> DatType:
        """Creates a new Dat with the specified spec dict and backing folder at 'path'.

        Args:
            dat_class: The Dat class to instantiate.
            path (str): The path to the folder where the Dat is stored.
            spec (Dict): The spec dict that describes the Dat.
            overwrite (bool): If True, the path will be overwritten if it exists.

        exists_action: "error" | "overwrite" | "use"

        PATH EXPANSION RULES:
        - Path is relative to the Dat.path_root() folder.
        - Time and other variables below are used to expand the path.
        - If the path is None, the _DEFAULT_PATH_TEMPLATE is used
        - If '{unique}' is in the path is assigned a number to make the path unique.
        - Otherwise an error is generated on path collision, or
          If 'overwrite' is True, the old folder contents are erased instead.
        - Variables used for path expansion:
            {YYYY} {YY} {MM} {DD} {HH} {mm} {SS}   -- based on time now or vars['time']
            {cwd}    -- the current working directory
            {unique} -- a counter or UUID that makes the entire path unique.
        """
        if spec is None:
            logger.info("No spec provided. Creating default DatSpec.")
            spec = DatSpec(dat=DatSpecCore(kind="Dat"))
        elif isinstance(spec, dict):
            spec = deepcopy(spec)

            # Ensure 'dat' field exists with at least 'kind'
            if "dat" not in spec:
                spec["dat"] = {}
            if "kind" not in spec["dat"]:
                spec["dat"]["kind"] = dat_class.__name__

            templated_name = spec.get("dat", {}).get("name")
            if templated_name is not None:
                spec["dat"].pop("name")
                if path is None:
                    path = templated_name

            spec = dat_class._SPEC_TYPE(**spec)

        if not isinstance(spec, dat_class._SPEC_TYPE):
            raise ValueError(
                f"Spec given {spec} doesn't match expected spec type {dat_class._SPEC_TYPE}"
            )

        if path is None:
            path = _DEFAULT_PATH_TEMPLATE
        else:
            path = str(path)

        path = self.resolve_path(self.expand_dat_path(path, overwrite=overwrite))
        if not os.path.exists(path):
            os.makedirs(path)
        try:
            logger.info("Creating Dat %s under path: <%s>", dat_class, path)
            spec.to_yaml(path)
        except Exception as e:
            raise EnvironmentError(
                f"Couldn't write spec {spec} to path {path}. Error: {e}"
            )
        return self.load(dat_class, name_or_path=path)

    def load(
        self,
        dat_class: Type[DatType],
        name_or_path: Union[str, Path],
        *,
        cwd: Optional[str] = None,
        cache_after_load: bool = True,
        pull_if_missing: bool = False,
    ) -> DatType:
        """Loads (Instantiates) this Dat from disk.

        Dat-loading is generally lazy, so its attributes are loaded and
        cached only when accessed.

        Dats are searched in the following order:
        (1) as a fullpath to the folder of the Dat to load
        (2) as a relative path from the current working directory or cwd parameter
        (3) as a named dat under the DAT_ROOT folder
        (4) as a named dat on S3 (LATER)

        :param dat_class: The Dat class to instantiate.
        :param name_or_path: Either the fullpath to the folder of the Dat to
            load or its name to be searched for
        :param cwd: used instead of current working dir for dat search
        """
        name_or_path = str(name_or_path)
        cwd = cwd or os.getcwd()

        path = self.resolve_path(name_or_path)
        if not os.path.exists(path) and pull_if_missing:
            raise NotImplementedError("Data pulling not implemented.")

            # FIXME: add this if we want to implement data pulling
            # logger.info("Didn't find locally. Pulling %s", name_or_path)
            # data_mgr = DataManager()
            # try:
            #     data_mgr.pull(name_or_path, gather=True)
            #     path = self.resolve_path(name_or_path)
            # except Exception:
            #     logger.warning("Couldn't pull %s", name_or_path)

        if not os.path.exists(path):
            raise KeyError(
                f"LOAD_DAT: Could not find <{name_or_path!r}> as absolute, "
                f"under cwd {cwd}, or in {self.sync_folders}"
            )

        spec_type = dat_class._SPEC_TYPE

        if (cached_dat := self.dat_cache.get(path)) and isinstance(
            cached_dat, dat_class
        ):
            return cached_dat

        try:
            if os.path.exists(spec_path := os.path.join(path, SPEC_YAML)):
                spec = spec_type.from_yaml(spec_path)
            elif os.path.exists(spec_path := os.path.join(path, SPEC_JSON)):
                spec = spec_type.from_json(spec_path)
            else:
                raise FileNotFoundError(
                    f"Didn't find a _spec_.yaml/_spec_.json file under path <{path}>."
                )
        except Exception as e:
            raise EnvironmentError("Error during spec loading.") from e

        # Note: Base expansion is handled by do_fn.expand_spec() for do-system specs.
        # We don't expand bases here since dat.base can reference do-system configs,
        # not just disk dats.

        kind = spec.dat.kind
        dat_class_name = dat_class.__name__

        # If using generic Dat class, look up the correct subclass based on kind
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

        if os.path.exists(result_path := os.path.join(path, RESULT_YAML)):
            with open(result_path, "r") as f:
                result = yaml.safe_load(f)
        else:
            result = {}

        path = os.path.abspath(path)
        dat = dat_class(
            path=path,
            spec=spec,
            result=result,
        )

        if cache_after_load:
            self.dat_cache[path] = dat

        return dat

    def exists(self, path: Union[str, Path]) -> bool:
        """Checks if a given Dat exists (by looking for its _spec_ file)."""
        path = str(path)
        path = self.resolve_path(path)
        return os.path.exists(os.path.join(path, SPEC_JSON)) or os.path.exists(
            os.path.join(path, SPEC_YAML)
        )

    def get_path_name(self, path: Union[str, Path]):
        path = str(path)
        try:
            match = 1 + len(os.path.commonpath([self.main_sync_folder, path]))
            return path[match:] if match > 2 else path
        except ValueError:
            return path

    @staticmethod
    def get_path_tail(path: Union[str, Path]) -> str:
        """Returns the shortname (last part of the path) of this Dat."""
        path = str(path)
        return path.split("/")[-1]

    def _find_subclass_by_name(self, klass: Type, name: str) -> Optional[Type]:
        """Recursively find a subclass by name."""
        if klass.__name__ == name:
            return klass
        for sub in klass.__subclasses__():
            if result := self._find_subclass_by_name(sub, name):
                return result
        return None

    def expand_dat_path(
        self,
        path_spec: Union[str, Path, None],
        *,
        variables: Optional[Dict[str, Any]] = None,
        overwrite: bool = False,
    ) -> str:
        """(See Dat.manager.create for path expansion rules.)"""
        if path_spec is None:
            path_spec = _DEFAULT_PATH_TEMPLATE
        path_spec = str(path_spec)
        now, count = datetime.now(), 1
        while True:
            format_vars = {
                "now": now.strftime("%y-%m-%d_%H-%M-%S"),
                "YYYY": now.strftime("%Y"),
                "YY": now.strftime("%Y")[2:],
                "MM": now.strftime("%m"),
                "DD": now.strftime("%d"),
                "HH": now.strftime("%H"),
                "mm": now.strftime("%M"),
                "SS": now.strftime("%S"),
                "unique": "" if count == 1 else f"_{count}",
                "cwd": os.getcwd(),  # Current working directory
                **(variables or {}),
            }
            expanded_path = os.path.join(
                self.main_sync_folder, path_spec.format_map(format_vars)
            )
            if not os.path.exists(expanded_path):
                return expanded_path
            elif overwrite:
                shutil.rmtree(expanded_path)
                return expanded_path
            elif "{unique}" not in path_spec:
                raise Exception(f"DAT: Create failed, dir {expanded_path!r} exists")
            else:
                count += 1

    def resolve_path(self, name: Union[str, Path]) -> str:
        name = str(name)

        path = name
        if os.path.isabs(path):
            return path

        path = os.path.join(self.config.cwd, name)
        if os.path.exists(path):
            return path

        for folder in self.sync_folders:
            path = os.path.join(folder, name)
            if os.path.exists(os.path.join(path, SPEC_JSON)) or os.path.exists(
                os.path.join(path, SPEC_YAML)
            ):
                return path
        return os.path.join(self.main_sync_folder, name)


class DatSpecCore(BaseModel):
    """Part of the spec that defines which Dat class should load it."""

    model_config = ConfigDict(extra="allow")

    kind: str = "Dat"
    base: Optional[str] = None
    do: Optional[str] = None
    args: Optional[List[Any]] = None
    kwargs: Optional[Dict[str, Any]] = None


class DatSpec(BaseModel):
    """Base Spec for all Dats."""

    model_config = ConfigDict(extra="allow")

    dat: DatSpecCore

    @classmethod
    def from_json(cls, path: Union[Path, str]):
        """Load a DatSpec from a json file in `path`."""
        path = Path(path)
        with path.open("r") as f:
            return cls(**json.load(f))

    @classmethod
    def from_yaml(cls, path: Union[Path, str]):
        """Load a DatSpec from a yaml file in `path`."""
        path = Path(path)
        with path.open("r") as f:
            return cls(**yaml.safe_load(f))

    def to_yaml(self, path: Union[Path, str]):
        """Serialize this Spec to a yaml file in `path`."""
        path = Path(path)
        if path.suffix != ".yaml" and path.suffix != ".yml":
            path = path / SPEC_YAML

        with path.open("w") as f:
            yaml.dump(self.model_dump(mode="json"), f, sort_keys=False)


class Dat(Generic[DatSpecType_co]):
    """
    A Dat is a data container (filesystem folder plus JSON metadata) that is saved
    from one Python environment and can be instantiated into others.

    Each Dat:
    - Is defined by a spec and a path that are supplied at its creation.
    - The path indicating a folder in the local filesystem where the modifiable data for
      this persistable is stored.  (This path may also be the local caching
      for source contents that are stored in S3 or other locations.)
    - The spec can be
      - a dict, or
      - or the name of a loadable dict
    - In either case it is recursively expanded (see )
    - The expanded spec is saved in _spec_.yaml or _spec_.yaml in its folder.

    loc == path or name

    Notes
    -----
    Information access guideline for Dat subclasses:
    - Anything that is instantaneously accessible, and that doesn't require parameters
      from the user to obtain information, should be implemented as a property
    - Everything else should be accessed by a method with a "get_" prefix. In other
      words, if any of the following is true, it should be accessed by a method:
      - If the data access performs IO
      - If the data requires non-trivial compute
      - If the data should be a candidate for caching
      - If lazy loading is beneficial

    """

    _SPEC_TYPE: Type[DatSpec] = DatSpec

    _manager: Optional[DatManager] = None  # Lazily initialized singleton manager

    # Backward compatibility: expose _manager as manager
    @classproperty
    def manager(cls) -> DatManager:
        if cls._manager is None:
            cls._manager = DatManager()
        return cls._manager

    _path: str  # The immutable absolute path of this Dat
    spec: DatSpecType_co  # The immutable spec of this Dat
    _result: SpecDict  # The mutable state or result of this Dat

    def __init__(
        self,
        path: Union[str, Path],
        spec: DatSpecType_co,
        result: Optional[SpecDict] = None,
    ) -> None:
        path = str(path)
        path = os.path.abspath(path)

        self._path = path
        self.spec = spec
        self._result = result or {}

    def get_spec(self) -> SpecDict:
        """Returns the spec of this Dat."""
        return self.spec.model_dump()

    def get_results(self) -> SpecDict:
        """Returns the spec of this Dat."""
        return self._result

    def get_path(self) -> str:
        """Returns the absolute path of this Dat."""
        return self._path

    # backward-compatibility
    @property
    def path(self) -> Path:
        return Path(self.get_path())

    def get_path_name(self) -> str:
        """Returns the name (relative path) of this Dat."""
        return Dat.manager.get_path_name(self._path)

    def get_path_tail(self) -> str:
        """Returns the shortname (last part of the path) of this Dat."""
        return self._path.split("/")[-1]

    @classmethod
    def load(
        cls: Type[DatType],
        name_or_path: Union[str, Path],
        cwd: Optional[str] = None,
        cache_after_load: bool = True,
        pull_if_missing: bool = False,
    ) -> DatType:
        """Load data from `name_or_path` and create a Dat.

        When you load a Dat, the class that you use to call .load from must match the
        spec's dat.kind parameter. The only exception is if you're using the base Dat
        class directly to load it, in which case you can load any dat, with very
        weak guarantees as to its structure.

        Parameters
        ----------
        name_or_path : Union[str, Path]
            Standard dat name, or path where the dat will be loaded from.
        cwd : Optional[str]
            Assume this as the cwd, if provided.
        cache_after_load : bool
            If True, the Dat will be stored in cache after it's loaded.

        Returns
        -------
            The instantiated Dat.

        """
        name_or_path = str(name_or_path)
        return cls.manager.load(
            cls,
            name_or_path,
            cwd=cwd,
            cache_after_load=cache_after_load,
            pull_if_missing=pull_if_missing,
        )

    @classmethod
    def create(
        cls: Type[DatType],
        path: Optional[Union[str, Path]] = None,
        spec: Union[DatSpecType_co, Dict, None] = None,
        overwrite: bool = False,
    ) -> DatType:
        """Create a Dat given `path` and `spec`."""
        return cls.manager.create(
            cls,
            path=path,
            spec=spec,
            overwrite=overwrite,
        )

    @classmethod
    def is_valid(
        cls: Type[DatType],
        path: Union[str, Path],
        cwd: Optional[str] = None,
    ) -> bool:
        """Return True if `path` can be loaded. False otherwise."""
        try:
            _ = cls.load(
                path,
                cwd=cwd,
                cache_after_load=False,
            )
            return True
        except Exception:
            return False

    def run(self) -> Tuple[bool, Dict[str, Any]]:
        # TODO: wrap this by using Do and Dat managers
        if not self.spec.dat.do:
            raise ValueError("Dat can't be run because it needs dat.do defined.")

        try:
            fn = dynamic_load_fn(self.spec.dat.do)
        except Exception:
            raise ValueError(
                "Couldn't find dat.do function. It must be specified as: my_module.my_fn"
            )

        result: Dict[str, Any] = {
            "start_time": str(datetime.now()),
        }

        t0 = time.time()
        try:
            success, metadata = fn(self)
        except Exception:
            logger.exception("Dat .run() call failed.")
            success = False
            metadata = {}

        result["success"] = success
        result["execution_time"] = time.time() - t0
        result["end_time"] = str(datetime.now())
        result["run_metadata"] = metadata

        with Path(self.get_path(), RESULT_YAML).open("w") as f:
            yaml.safe_dump(result, f, sort_keys=False)

        return success, metadata

    def save(self) -> None:
        """Saves the Dat's results to the result file in its folder."""
        if self._result:
            with Path(self.get_path(), RESULT_YAML).open("w") as out:
                yaml.safe_dump(self._result, out, sort_keys=False)

    def delete(self, *, must_exist=True) -> bool:
        """Deletes the folder and its contents from the filesystem.
        This deletion will also be reflected as a deletion pushed to git.
        Still, the backing store will retain all previous versions of this Dat."""
        Dat.manager.dat_cache.pop(self._path, None)  # Remove from cache
        try:
            shutil.rmtree(self._path)
        except FileNotFoundError:
            if must_exist:
                raise Exception(f"DAT DELETE: Folder missing {self._path!r}.")
            else:
                return False
        return True

    def copy(self: DatType, new_path: Union[str, Path]) -> DatType:
        """Copies this Dat to a new location."""
        new_path_ = Dat.manager.resolve_path(new_path)
        if os.path.exists(new_path_):
            raise Exception(f"DAT COPY: Folder exists {new_path!r}.")
        shutil.copytree(self._path, new_path_)
        result = Dat.manager.load(type(self), new_path_)
        return result

    def move(self: DatType, new_path: Union[str, Path]) -> DatType:
        """Moves this Dat to a new location."""
        del Dat.manager.dat_cache[self._path]  # Remove from cache
        new_path_ = Dat.manager.resolve_path(new_path)
        if os.path.exists(new_path_):
            raise Exception(f"DAT MOVE: Folder exists {new_path!r}.")
        shutil.move(self._path, new_path_)
        result = Dat.manager.load(type(self), new_path_)
        return result

    def __repr__(self):
        base = Dat.get(self.spec.model_dump(), _DAT_BASE, self.__class__.__name__)
        base = base.split("/")[-1]
        return f"<{base}: {self.get_path_name()}>"

    def __str__(self):
        return self.__repr__()

    # methods below are for backward-compatibility
    @staticmethod
    def get(
        source: Union["Dat", dict],
        keys: Union[str, List[str]],
        default_value: Any = _NO_ARG,
    ) -> Any:
        """Utility method to get value from a recursive dict tree or return None."""
        return dotted_get(
            source=source,
            keys=keys,
            default_value=default_value,
        )

    @staticmethod
    def set(
        source: SpecDict,
        keys,
        value,
    ) -> None:
        """Utility method into a recursive dict tree."""
        dotted_set(
            source=source,
            keys=keys,
            value=value,
        )

    @staticmethod
    def gets(
        source: Union["Dat", SpecDict],
        *dotted_keys,
    ) -> List[Any]:
        return dotted_gets(
            source,
            *dotted_keys,
        )

    @staticmethod
    def sets(
        source: dict,
        *assignments,
    ) -> None:
        """Utility method that applies multiple dotted assignments into a
        recursive dict tree.

        Each assignment is of the form:   key.sub_key...=value
        - spaces are trimmed from ends and around '='
        - values are parsed as an int, as a float, else as a string.
        """
        dotted_sets(
            source,
            *assignments,
        )


# TODO: change this. Not super happy with how this turned out.
class DatContainer(Dat, Generic[DatType]):
    """Container of multiple Dats.

    This Dat looks for other Dats recursively under its path, and exposes them via
    the attributes `dats` and `dat_paths`.

    The container can be type annotated with the containers that it's expected to have.

    Properties
    ----------
    dat_paths : List[str]
        List of pahts corresponding to the dats under this DatContainer.
    dats : List[Dat]
        List of Dats under this DatContainer

    Examples
    --------
    >>> game_set: DatContainer[Dat] = DatContainer.load("name/of/game/set")
    >>> game_set.get_dats()[0] # a Game Dat!

    Notes
    -----

    The spec structure is assumed to be:
    {
        "dat": {
            "class": "DatContainer"
        }
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._dat_paths: Union[DataState, List[str]] = DataState.NOT_LOADED
        self._dats: Union[DataState, List[DatType]] = DataState.NOT_LOADED

    def get_dat_paths(self) -> List[str]:
        """Lazy loaded list of full paths for the contained Dat."""
        if self._dat_paths is DataState.NOT_LOADED:
            self._dat_paths = DatContainer._find_dats_under(self._path)
        return self._dat_paths

    def get_dats(self) -> List[DatType]:
        """List of contained Dat objects.

        WARNING: ALL Dats remain in memory until this container is released.
        """
        if self._dats is DataState.NOT_LOADED:
            # these will load as the Dat class as defined in each spec's
            # main  .class, but we're loading them dynamically from Dat directly,
            # so we'll ignore the type and assume they will all be List[T]
            self._dats = [Dat.load(p) for p in self.get_dat_paths()]  # type: ignore
        return self._dats  # type: ignore

    @staticmethod
    def _find_dats_under(root_path: Union[str, Path]):
        root_path = str(root_path)
        results = []
        for root, dirs, files in os.walk(root_path):
            for name in files:
                if name == SPEC_JSON or name == SPEC_YAML:
                    folder = os.path.dirname(os.path.join(root, name))
                    results.append(folder)
        results.sort()
        assert os.path.abspath(results[0]) == os.path.abspath(root_path)
        del results[0]
        return results


def dotted_get(
    source: Union[Dat, dict],
    keys: Union[str, List[str]],
    default_value: Any = _NO_ARG,
):
    """Utility method to get value from a recursive dict tree or return None."""
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
    results = []
    for dotted_key in dotted_keys:
        keys = dotted_key.split(".")
        results.append(dotted_get(source_, keys))
    return results


def dotted_set(source: SpecDict, keys, value):
    """Utility method into a recursive dict tree."""
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
    """Utility method that applies multiple dotted assignments into a
    recursive dict tree.

    Each assignment is of the form:   key.sub_key...=value
    - spaces are trimmed from ends and around '='
    - values are parsed as an int, as a float, else as a string.
    """
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


def create_from_template(
    path: PathLike,
    name: Union[Path, str, None] = None,
    data_config: Optional[DataConfig] = None,
    **kwargs,
) -> Dat:
    """Create a Dat from a template.

    Kwargs will be passed to the template, and the template will be used as a Dat's spec.

    Parameters
    ----------
    path : PathLike
        Path to the runset or template of the dat to execute.
    name : Union[Path, str]
        If `path` is a template, this can be used to override the resulting name.
    data_config : Optional[DataConfig]
        If provided, this data config will be used to look up the mappings between
        Dat kind and classes. Otherwise, a new instance will be created.

    Returns
    -------
    Dat:
        The newly created Dat.

    """
    if data_config is None:
        data_config = DataConfig.new()

    template = load_dict(path)
    if template is None:
        raise FileNotFoundError("Couldn't find template under %s", path)

    name_in_template = template.get("dat", {}).get("name")
    if not name and not name_in_template:
        raise ValueError(
            "When a template is provided, `name` must be specified either in the "
            "template under dat.name, or as a parameter to this function."
        )

    logger.info("Creating dat from template %s", path)

    template.update(kwargs)
    dat_kind = template.get("dat", {}).get("kind")
    if dat_kind is None:
        raise AttributeError("No entry for dat.kind found in template.")

    dat = _dynamic_load_dat_class(dat_kind, data_config).create(
        path=name,
        spec=template,
    )
    return dat


def load(
    path: PathLike,
    data_config: Optional[DataConfig] = None,
) -> Dat:
    """Load a Dat.

    The Dat type will be inferred from the spec's dat.kind.

    Parameters
    ----------
    path : PathLike
        Path to the runset or template of the dat to execute.
    data_config : Optional[DataConfig]
        If provided, this data config will be used to look up the mappings between
        Dat kind and classes. Otherwise, a new instance will be created.

    Returns
    -------
    Dat:
        The instantiated Dat.

    """
    if data_config is None:
        data_config = DataConfig.new()

    if not Dat.is_valid(path):
        raise EnvironmentError("Couldn't a valid Dat under <%s>", path)

    logger.info("Loading Dat in %s", path)
    generic_dat = Dat.load(path)
    dat = _dynamic_load_dat_class(generic_dat.spec.dat.kind, data_config).load(path)
    return dat


def _dynamic_load_dat_class(dat_kind: str, data_config: DataConfig) -> Type[Dat]:
    """Load a Dat class dynamically from the mappings defined in data_config.

    Parameters
    ----------
    dat_kind : str
        Name of the Dat class.
    data_config : DataConfig
        DataConfig containing .dat["mappings"]. Where the mappings map the name of the
        Dat class to the module where it can be loaded from.

    Returns
    -------
    Type[Dat]
        The dynamically loaded Dat class.

    """
    dat_mappings: Dict[str, str] = data_config.dat.get("mappings", {})
    module_str = dat_mappings.get(dat_kind)
    if module_str is None:
        raise AttributeError(
            f"No mapping entry found for dat of kind {dat_kind} in DataConfig."
        )

    module = importlib.import_module(module_str)
    try:
        dat_class = getattr(module, dat_kind)
    except Exception:
        raise AttributeError(f"Dat class {dat_kind} not found in module {module}.")

    if not issubclass(dat_class, Dat):
        raise ValueError(f"Class {dat_class} is not a subclass of Dat.")
    return dat_class
