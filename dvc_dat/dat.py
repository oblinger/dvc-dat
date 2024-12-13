import json
import os
import shutil
import weakref
from abc import abstractmethod
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union, Callable, \
    Iterable
import yaml
# from .dvc_dat_config import SPEC_JSON, SPEC_YAML

_RESULT_JSON = "_results_.json"
_DAT_BASE = "dat.base"
_DAT_CLASS = "dat.class"
_DAT_PATH_OVERWRITE = "dat.path_overwrite"
_DEFAULT_PATH_TEMPLATE = "anonymous/Dat{unique}"
_NO_ARG = "$$NO_ARG$$"

SPEC_JSON = "_spec_.json"
SPEC_YAML = "_spec_.yaml"
_DAT_CONFIG_JSON = ".datconfig.json"
_DAT_CONFIG_YAML = ".datconfig.yaml"
_DAT_FOLDER = "sync_folder"
_DAT_FOLDERS = "dat_folders"
_DAT_MOUNT_COMMANDS = "mount_commands"
_DEFAULT_DAT_FOLDER = "dat_data"


class DataState(Enum):
    NOT_LOADED = auto()


# A Value is possibly recursive dict of parameters within the Dat's spec.
# Often it is a dict of dict, but single level is ok as long as keys are
# strings.  The spec is stored in the _spec_ file in the Persistable's folder.
Value = Union[str, int, float, bool, None, 'Spec']

Spec = Dict[str, Value]

T = TypeVar("T", bound="Dat")


class Dat(object):
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

    Persistable API
      Dat.create(path=, spec=) ... Constructor
      .load(path) ................ Universal loader for all Persistables
      .get_spec() ................ Is the 'spec' dict for this dat
      .get_path() ................ Returns dat's path (its absolute path)
      .get_path_name() ........... Returns dat's name (its path relative to dat_folder)
      .get_path_tail() ........... Returns dat's shortname (last part of its path)
      .delete() .................. Deletes the dat from the filesystem
      .copy() .................... Copies the dat to a new location
      .move() .................... Moves the dat to a new location
      .save([path]) .............. Saves persistable to disk (optionally sets its path)

    Static Utility Methods
      .get(Dat|dict, [key1, key2, ...])
      .get(Dat|dict, "dotted.key.path")
      .set(dict, [key1, key2, ...], value)
      .set(dict, "dotted.key.path", value)

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

    """   # noqa
    manager: 'DatManager' = None    # The singleton manager for all Dats, set at end of file
    _path: str      # The immutable absolute path of this Dat
    _spec: Spec     # The immutable spec of this Dat
    _result: Spec   # The mutable state or result of this Dat

    @staticmethod
    def get(source: Union["Dat", dict],
            keys: Union[str, List[str]],
            default_value=_NO_ARG) -> Any:
        """Utility method to get value from a recursive dict tree or return None."""
        d = source._spec if isinstance(source, Dat) else source
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

    @staticmethod
    def set(source: Spec, keys, value) -> None:
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

    @staticmethod
    def gets(source: Union["Dat", Spec], *dotted_keys) -> List[Any]:
        assert source is not None, "gets method requires a non None dict"
        source_ = source._spec if isinstance(source, Dat) else source
        results = []
        for dotted_key in dotted_keys:
            keys = dotted_key.split(".")
            results.append(Dat.get(source_, keys))
        return results

    @staticmethod
    def sets(source: dict, *assignments) -> None:
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
            Dat.set(source, keys, value)

    # DEPRECATED METHODS

    @classmethod
    def create(cls, *,
               path: str = None,
               spec: Spec = None,
               overwrite=()
               ) -> "Dat":
        return Dat.manager.create(path=path, spec=spec, overwrite=overwrite)

    @classmethod
    def load(cls: Type[T], name_or_path: str, *,
             cwd: Optional[str] = None) -> T:
        return Dat.manager.load(name_or_path, cwd=cwd)

    @staticmethod
    def exists(path: str) -> bool:
        """Checks if a given Dat exists (by looking for its _spec_ file)."""
        return Dat.manager.exists(path)

    def __init__(self,
                 *,
                 path: str = None,
                 spec: Dict = None,
                 _no_backing: bool = False):
        super().__init__()
        self._result = {}
        if _no_backing:
            self._path, self._spec = path, spec
        else:
            raise Exception("Use Dat.create() to create a new Dat instances.")

    def __repr__(self):
        base = Dat.get(self._spec, _DAT_BASE, self.__class__.__name__)
        base = base.split("/")[-1]
        return f"<{base}: {self.get_path_name()}>"

    def __str__(self):
        return self.__repr__()

    def get_spec(self) -> Spec:
        """Returns the spec of this Dat."""
        return self._spec

    def get_results(self) -> Spec:
        """Returns the spec of this Dat."""
        return self._result

    def get_path(self) -> str:
        """Returns the absolute path of this Dat."""
        return self._path

    def get_path_name(self) -> str:
        """Returns the name (relative path) of this Dat."""
        return Dat.manager.get_path_name(self._path)

    def get_path_tail(self) -> str:
        """Returns the shortname (last part of the path) of this Dat."""
        return self._path.split("/")[-1]

    def save(self) -> None:
        """Flags a Dat to have a version of its folder's contents saved
        to in the backing store.
        """
        if True or self._result:
            with open(os.path.join(self._path, _RESULT_JSON), "w") as out:
                txt = json.dumps(self._result, indent=2)
                out.write(txt)

    def delete(self, *, must_exist=True) -> bool:
        """Deletes the folder and its contents from the filesystem.
        This deletion will also be reflected as a deletion pushed to git.
        Still, the backing store will retain all previous versions of this Dat."""
        Dat.manager.dat_cache.pop(self._path, None)      # Remove from cache
        try:
            shutil.rmtree(self._path)
        except FileNotFoundError:
            if must_exist:
                raise Exception(f"DAT DELETE: Folder missing {self._path!r}.")
            else:
                return False
        return True

    def copy(self, new_path: str) -> "Dat":
        """Copies this Dat to a new location."""
        new_path_ = Dat.manager.resolve_path(new_path)
        if os.path.exists(new_path_):
            raise Exception(f"DAT COPY: Folder exists {new_path!r}.")
        shutil.copytree(self._path, new_path_)
        result = Dat.load(new_path_)
        return result

    def move(self, new_path: str) -> "Dat":
        """Moves this Dat to a new location."""
        del Dat.manager.dat_cache[self._path]      # Remove from cache
        new_path_ = Dat.manager.resolve_path(new_path)
        if os.path.exists(new_path_):
            raise Exception(f"DAT MOVE: Folder exists {new_path!r}.")
        shutil.move(self._path, new_path_)
        result = Dat.load(new_path_)
        return result


class DatContainer(Dat, Generic[T]):
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
        self._dats: Union[DataState, List[T]] = DataState.NOT_LOADED

    def get_dat_paths(self) -> List[str]:
        """Lazy loaded list of full paths for the contained Dat."""
        if self._dat_paths is DataState.NOT_LOADED:
            self._dat_paths = DatContainer._find_dats_under(self._path)
        return self._dat_paths

    def get_dats(self) -> List[T]:
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
    def _find_dats_under(root_path):
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


DatMethod = Callable[[Dat, ...], Any]    # A Callable that serves as a method on a Dat


class MethodManager(object):
    """Manages a namespace of DatMethods that are  indexed by String"""

    @abstractmethod
    def __call__(self, name: str, *args, **kwargs) -> Any: ...

    @abstractmethod
    def mount(self, **kwargs): ...

    @abstractmethod
    def load(self, name: str) -> DatMethod: ...

    @abstractmethod
    def keys(self) -> Iterable[str]: ...


class SimpleMethodManager(MethodManager):
    def __init__(self):
        self._dat_methods: Dict[str, DatMethod] = {}

    def __call__(self, name, *args, **kwargs):
        return self._dat_methods[name](*args, **kwargs)

    def load(self, name: str) -> DatMethod:
        return self._dat_methods.get(name)

    def mount(self, value: DatMethod, at: str):
        self._dat_methods[at] = value

    def keys(self):
        return self._dat_methods.keys()


class DatManager(object):
    """Singleton class that manages the configuration and loading of Dats.

    Configuration info for the 'dat' module loaded from the .datconfig.json file.

    .datconfig.json
        The do module searches CWD and all parent dirs for the '.datconfig.json' file.
        If it is found, it expects a JSON object with a 'do_folder' key that indicates
        the path (relative to the .datconfig.json file itself) of the "do folder"
    """
    config: Dict[str, Any] = {}
    do: MethodManager = SimpleMethodManager()
    sync_folder: str
    sync_folders: List[str]   # Note: also includes the dat_folder
    dat_cache: Dict[str, Any] = weakref.WeakValueDictionary()  # Used in Dat.load

    DAT_ADDS_LIST = ".dat_adds.txt"  # List of Dat names to be updated in DVC

    def __init__(self, folder=None):
        self.folder = folder or os.getcwd()
        while True:
            if os.path.exists(config := os.path.join(self.folder, _DAT_CONFIG_JSON)):
                try:
                    with open(config, 'r') as f:
                        self.config = json.load(f)
                except json.JSONDecodeError as e:
                    raise Exception(f"Error loading {_DAT_CONFIG_JSON}: {e}")
                break
            if os.path.exists(config := os.path.join(self.folder, _DAT_CONFIG_YAML)):
                try:
                    with open(config, 'r') as f:
                        self.config = yaml.safe_load(f)
                except yaml.YAMLError as e:
                    raise Exception(f"Error loading {_DAT_CONFIG_YAML}: {e}")
                break
            if self.folder == '/':
                self.folder = os.getcwd()
                break
            self.folder = os.path.dirname(self.folder)

        self.sync_folder = self._lookup_path(self.folder, _DAT_FOLDER, None)
        if not self.sync_folder:
            s = f"No {_DAT_CONFIG_JSON} found or no \"{_DAT_FOLDER}\" specified."
            print(f"Warning: {s}")
            self.sync_folder = os.path.join(self.folder, _DEFAULT_DAT_FOLDER)
        dirs = self.config.get(_DAT_FOLDERS)
        dirs = ([self.sync_folder] + dirs) if dirs else [self.sync_folder]
        self.sync_folders = [os.path.join(self.folder, f) for f in dirs]
        assert self.sync_folder
        assert len(self.sync_folders) > 0

    def _lookup_path(self, folder_path: str, key, default=None) -> Union[str, None]:
        suffix = self.config[key] if key in self.config else default
        if suffix:
            path = os.path.join(folder_path, suffix)
            os.makedirs(path, exist_ok=True)
        else:
            path = None  # os.path.join(os.getcwd(), default)
        return path

    def create(self, *,
               path: str = None,
               spec: Spec = None,
               overwrite=()
               ) -> "Dat":
        """Creates a new Dat with the specified spec dict and backing folder at 'path'.

        Args:
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
        spec: Dict = spec or {}
        path: str = self.resolve_path(
            self.expand_dat_path(path, overwrite=overwrite))
        if not os.path.exists(path):
            os.makedirs(path)
        try:
            txt = yaml.safe_dump(spec, indent=2)
        except Exception as e:
            raise Exception(f"Non-JSON data in Dat.spec: {e}\nSPEC={spec}")
        with open(os.path.join(path, SPEC_YAML), "w") as out:
            out.write(txt)
            out.write("\n")
        return self._make_dat_instance(path, spec)

    def load(self, name_or_path: str, *,
             cwd: Optional[str] = None) -> T:
        """Loads (Instantiates) this Dat from disk.

        Dat-loading is generally lazy, so its attributes are loaded and
        cached only when accessed.

        Dats are searched in the following order:
        (1) as a fullpath to the folder of the Dat to load
        (2) as a relative path from the current working directory or cwd parameter
        (3) as a named dat under the DAT_ROOT folder
        (4) as a named dat on S3 (LATER)

        :param name_or_path: Either the fullpath to the folder of the Dat to
            load or its name to be searched for
        :param cwd: used instead of current working dir for dat search
        """
        if os.path.isabs(name_or_path):
            path = name_or_path
        elif os.path.exists(path := os.path.join(cwd or os.getcwd(), name_or_path)):
            pass
        elif os.path.exists(path := self.resolve_path(name_or_path)):
            pass
        else:
            raise KeyError(f"LOAD_DAT: Could not find {name_or_path!r}")
        if path in self.dat_cache:
            return self.dat_cache[path]
        path = os.path.abspath(path)
        try:
            spec = ()
            if os.path.exists(fpath := os.path.join(path, SPEC_JSON)):
                with open(fpath) as f:
                    spec = json.load(f)
            elif os.path.exists(fpath := os.path.join(path, SPEC_YAML)):
                with open(fpath) as f:
                    spec = yaml.safe_load(f)
        except Exception as e:
            if not os.path.exists(path):
                raise KeyError(F"LOAD_DAT: Folder not found {path!r}.")
            else:
                raise KeyError(f"LOAD_DAT: Error in spec file for {path!r}: {e}")
        if spec == ():
            raise KeyError(F"LOAD_DAT: Spec file missing for {path!r}.")
        dat = self._make_dat_instance(path, spec)
        try:
            with open(os.path.join(path, _RESULT_JSON)) as f:
                dat._result = json.load(f)
        except FileNotFoundError:
            pass
        return dat

    @staticmethod
    def exists(path: str) -> bool:
        """Checks if a given Dat exists (by looking for its _spec_ file)."""
        path = Dat.manager.resolve_path(path)
        return os.path.exists(os.path.join(path, SPEC_JSON)) or \
            os.path.exists(os.path.join(path, SPEC_YAML))

    def get_path_name(self, path):
        try:
            match = 1 + len(os.path.commonpath([self.sync_folder, path]))
            return path[match:] if match > 2 else path
        except ValueError:
            return path

    @staticmethod
    def get_path_tail(path) -> str:
        """Returns the shortname (last part of the path) of this Dat."""
        return path.split("/")[-1]

    def expand_dat_path(self, path_spec: Union[str, None], *,
                        variables: Dict[str, Any] = None,
                        overwrite: bool = False) -> str:
        """(See Dat.create for path expansion rules.)"""  # noqa
        if not path_spec:
            path_spec = _DEFAULT_PATH_TEMPLATE
        now, count = datetime.now(), 1
        while True:
            format_vars = {
                "YYYY": now.strftime("%Y"), "YY": now.strftime("%Y")[2:],
                "MM": now.strftime("%m"), "DD": now.strftime("%d"),
                "HH": now.strftime("%H"), "mm": now.strftime("%M"),
                "SS": now.strftime("%S"),
                "unique": "" if count == 1 else f"_{count}",
                "cwd": os.getcwd(),  # Current working directory
                **(variables or {})}
            expanded_path = os.path.join(self.sync_folder,
                                         path_spec.format_map(format_vars))
            if not os.path.exists(expanded_path):
                return expanded_path
            elif overwrite:
                shutil.rmtree(expanded_path)
                return expanded_path
            elif "{unique}" not in path_spec:
                raise Exception(f"DAT: Create failed, dir {expanded_path!r} exists")
            else:
                count += 1

    def resolve_path(self, name: str) -> str:
        for folder in self.sync_folders:
            path = os.path.join(folder, name)
            if os.path.exists(os.path.join(path, SPEC_JSON)) or \
                    os.path.exists(os.path.join(path, SPEC_YAML)):
                return path
        return os.path.join(self.sync_folder, name)

    def _make_dat_instance(self, path: str, spec: Dict) -> "Dat":
        from . import Dat
        klass_name = Dat.get(spec, _DAT_CLASS, "Dat")
        klass = self._find_subclass_by_name(Dat, klass_name)
        if not klass:
            raise Exception(f"Class {klass_name} is not a subclass of Dat")

        dat = klass(path=path, spec=spec, _no_backing=True)

        self.dat_cache[path] = dat
        return dat

    def _find_subclass_by_name(self, klass, name):
        if klass.__name__ == name:
            return klass
        for sub in klass.__subclasses__():
            if result := self._find_subclass_by_name(sub, name):
                return result
        return None


Dat.manager = DatManager()
