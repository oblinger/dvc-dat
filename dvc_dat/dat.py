import json
import os
import shutil
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union
import yaml


SPEC_JSON = "_spec_.json"
SPEC_YAML = "_spec_.yaml"
RESULT_JSON = "_result_.json"
MAIN_CLASS = "main.class"
MAIN_KIND = "main.kind"
_DEFAULT_PATH_TEMPLATE = "anonymous/Dat{unique}"


# This default value is overridden by do._dat_setup()
# data_folder = os.path.join(os.path.dirname(__file__), "dat_data")


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
      Dat.create(path=, spec=) ...... Constructor
      Dat.create_from_template(path, spec) ...... Constructor
      .load(path) ........... Universal loader for all Persistables
      .get_spec() ........... Is the 'spec' dict for this dat
      .get_path() ........... Returns dat's path (its absolute path)
      .get_path_name() ........... Returns dat's name (its path relative to dat_folder)
      .get_path_tail() ...... Returns dat's shortname (last part of its path)
      .save([path]) ......... Saves persistable to disk (optionally sets its path)

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
    _path: str      # The immutable absolute path of this Dat
    _spec: Spec     # The immutable spec of this Dat
    _result: Spec   # The mutable state or result of this Dat

    @staticmethod
    def get(source: Union["Dat", dict],
            keys: Union[str, List[str]],
            default_value=None) -> Any:
        """Utility method to get value from a recursive dict tree or return None."""
        d = source._spec if isinstance(source, Dat) else source
        if isinstance(keys, str):
            keys = keys.split(".")
        for k in keys:
            if d is None:
                return default_value
            elif not isinstance(d, dict):
                raise ValueError(f"GET: Expected dict value for {k!r} not {d!r}")
            else:
                d = d.get(k)
        return d or default_value

    @staticmethod
    def set(source: dict, keys, value) -> None:
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
    def gets(source: Union["Dat", dict], *dotted_keys) -> List[Any]:
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

    @staticmethod
    def exists(path: str) -> bool:
        """Checks if a given Dat exists (by looking for its _spec_ file)."""
        return os.path.exists(Dat._resolve_path(os.path.join(path, SPEC_JSON))) or \
            os.path.exists(Dat._resolve_path(os.path.join(path, SPEC_YAML)))

    @classmethod
    def load(cls: Type[T], name_or_path: str, *,
             cwd: Optional[str] = None, **kwargs) -> T:
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
        :param kwargs: other kwargs are passed to the Dat constructor
        """
        from . import dat_config
        if os.path.isabs(name_or_path):
            path = name_or_path
        elif os.path.exists(path := os.path.join(cwd or os.getcwd(), name_or_path)):
            pass
        elif os.path.exists(path := os.path.join(dat_config.dat_folder,
                                                 Dat._resolve_path(name_or_path))):
            pass
        else:
            raise Exception(f"LOAD_DAT: Could not find {name_or_path!r}")
        try:
            if os.path.exists(fpath := os.path.join(path, SPEC_JSON)):
                with open(fpath) as f:
                    spec = json.load(f)
            else:
                with open(os.path.join(path, SPEC_YAML)) as f:
                    spec = yaml.safe_load(f)
        except Exception as e:
            if not os.path.exists(path):
                raise Exception(F"LOAD_DAT: Folder missing {path!r}.")
            else:
                raise Exception(f"LOAD_DAT: Error loading {path!r}s spec file: {e}")
        dat = Dat._make_dat_instance(path, spec)
        try:
            with open(os.path.join(path, RESULT_JSON)) as f:
                dat._result = json.load(f)
        except FileNotFoundError:
            pass
        return dat

    @classmethod
    def create(cls, path: str, spec: Spec, *, overwrite: bool = False) -> "Dat":
        """Creates a new Dat with the specified name and spec dict."""
        path: str = Dat._resolve_path(
            Dat._expand_dat_path(path, overwrite=overwrite))
        spec: Dict = spec or {}
        # Dat.set(spec, MAIN_CLASS, cls.__name__)
        if not os.path.exists(path):
            os.makedirs(path)
        try:
            txt = json.dumps(spec, indent=2)
        except Exception as e:
            raise Exception(f"Error non-JSON data in Dat.spec: {e}\nSPEC={spec}")
        with open(os.path.join(path, SPEC_JSON), "w") as out:
            out.write(txt)
            out.write("\n")

        return Dat._make_dat_instance(path, spec)

    def __init__(self,
                 *,
                 path: str = None,
                 spec: Dict = None,
                 overwrite: bool = False,
                 _no_backing: bool = False):
        """Creates a new Dat with the specified spec dict and backing folder at path.

        Args:
            path (str): The path to the folder where the Dat is stored.
            spec (Dict): The spec dict that describes the Dat.
            overwrite (bool): If True, the path will be overwritten if it exists.
            _no_backing (bool): If True, the Dat is created without a backing folder.

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
        super().__init__()
        self._result = {}
        if _no_backing:
            self._path, self._spec = path, spec
        else:
            raise Exception("Use Dat.create() to create a new Dat instances.")

    def __repr__(self):
        kind = Dat.get(self._spec, MAIN_KIND, self.__class__.__name__)
        return f"<{kind}: {self.get_path_name()}>"

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
        return self._path2name(self._path)

    def get_path_tail(self) -> str:
        """Returns the shortname (last part of the path) of this Dat."""
        return self._path.split("/")[-1]

    def save(self) -> None:
        """Flags a Dat to have a version of its folder's contents saved
        to in the backing store.
        """
        if self._result:
            with open(os.path.join(self._path, RESULT_JSON), "w") as out:
                out.write(json.dumps(self._result, indent=2))

    def delete(self, *, must_exist=True) -> bool:
        """Deletes the folder and its contents from the filesystem.
        This deletion will also be reflected as a deletion pushed to git.
        Still, the backing store will retain all previous versions of this Dat."""
        try:
            shutil.rmtree(self._path)
        except FileNotFoundError:
            if must_exist:
                raise Exception(f"DAT DELETE: Folder missing {self._path!r}.")
            else:
                return False
        return True

    @staticmethod
    def _expand_dat_path(path_spec: Union[str, None], *,
                         variables: Dict[str, Any] = None,
                         overwrite: bool = False) -> str:
        """
        Expands a path spec into a full path.  See __init__ for expansion rules.

        Args:
            path_spec (str): The path specification string with placeholders.
            variables (Dict[str, Any]): Additional variables provided by the user.
            overwrite (bool): If True, the path will be overwritten if it exists.

        Returns:
            str: The fully expanded path.

        Examples:
            _expand_path_spec("/data/{YYYY}/{MM}/{DD}/file_{unique}.txt", {})
            -> "/data/2024/05/03/file_123e4567-e89b-12d3-a456-426614174000.txt"
        """
        if not path_spec:
            path_spec = _DEFAULT_PATH_TEMPLATE
        if "{unique}" not in path_spec:
            path_spec += "{unique}"
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
            expanded_path = path_spec.format_map(format_vars)
            if not os.path.exists(expanded_path):
                return expanded_path
            elif overwrite:
                shutil.rmtree(expanded_path)
                return expanded_path
            elif "{unique}" not in path_spec:
                raise Exception(f"DAT: Create failed, dir {expanded_path!r} exists")
            else:
                count += 1

    @staticmethod
    def _make_dat_instance(path: str, spec: Dict) -> "Dat":

        klass_name = Dat.get(spec, MAIN_CLASS) or "Dat"
        klass = Dat._find_subclass_by_name(Dat, klass_name)
        if not klass:
            raise Exception(f"Class {klass_name} is not a subclass of Dat")

        dat = klass(path=path, spec=spec, _no_backing=True)
        return dat

    @staticmethod
    def _find_subclass_by_name(klass, name):
        if klass.__name__ == name:
            return klass
        for sub in klass.__subclasses__():
            if result := Dat._find_subclass_by_name(sub, name):
                return result
        return None

    @staticmethod
    def _path2name(path):
        from . import dat_config
        try:
            match = 1 + len(os.path.commonpath([dat_config.dat_folder, path]))
            return path[match:] if match > 2 else path
        except ValueError:
            return path

    @staticmethod
    def _resolve_path(name: str) -> str:
        from . import dat_config
        return os.path.join(dat_config.dat_folder, name)

        # if name and name[0] == "$":
        #     return name[1:].replace(".", "/")
        # else:
        #     return os.path.join(dat_config.dat_folder, name.replace(".", "/"))


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
    >>> game_set.get_dats()[0]  # a Game dat!

    Notes
    -----

    The spec structure is assumed to be:
    {
        "main": {
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
            self._dat_paths = DatContainer._find_dat_under(self._path)
        return self._dat_paths

    def get_dats(self) -> List[T]:
        """List of contained Dat objects.

        WARNING: ALL Dats remain in memory until this container is released.
        """
        if self._dats is DataState.NOT_LOADED:
            # these will load as the Dat class that was defined in each spec's
            # main.class, but we're loading them dynamically from Dat directly,
            # so we'll ignore the type and assume they will all be List[T]
            self._dats = [Dat.load(p) for p in self.get_dat_paths()]  # type: ignore
        return self._dats  # type: ignore

    @staticmethod
    def _find_dat_under(root_path):
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


load_dat = Dat.load

# import dvc_dat
# from dvc_dat import ml_dat_config
# dvc_dat.Dat = Dat
# dvc_dat.DatContainer = DatContainer
# dvc_dat.load_dat = load_dat
# data_folder = ml_dat_config.dat_config.dat_folder
