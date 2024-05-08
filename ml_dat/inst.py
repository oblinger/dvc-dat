import json
import os
import shutil
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union
import yaml


SPEC_JSON = "_spec_.json"
SPEC_YAML = "_spec_.yaml"
MAIN_CLASS = "main.class"
_DEFAULT_PATH_TEMPLATE = "anonymous/Inst{unique}"


# This default value is overridden by do._dat_setup()
# data_folder = os.path.join(os.path.dirname(__file__), "inst_data")


class DataState(Enum):
    NOT_LOADED = auto()


# A Value is possibly recursive dict of parameters within the Inst's spec.
# Often it is a dict of dict, but single level is ok as long as keys are
# strings.  The spec is stored in the _spec_ file in the Persistable's folder.
Value = Union[str, int, float, Dict[str, "Value"]]

T = TypeVar("T", bound="Inst")


class Inst(object):
    """
    A Instantiable (Inst) is a data container that is saved from one Python environment
    and can be instantiated into others.

    Each Inst:
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
      Inst(path, spec) ...... Constructor
      .load(path) ........... Universal loader for all Persistables
      .get_spec() ........... Is the 'spec' dict for this inst
      .get_path() ........... Returns inst's path (its absolute path)
      .get_path_name() ........... Returns inst's name (its path relative to inst_folder)
      .get_path_tail() ...... Returns inst's shortname (last part of its path)
      .save([path]) ......... Saves persistable to disk (optionally sets its path)

    Static Utility Methods
      .get(Inst|dict, [key1, key2, ...])
      .get(Inst|dict, "dotted.key.path")
      .set(dict, [key1, key2, ...], value)
      .set(dict, "dotted.key.path", value)

    Notes
    -----

    Information access guideline for Inst subclasses:
    - Anything that is instantaneously accessible, and that doesn't require parameters
      from the user to obtain information, should be implemented as a property
    - Everything else should be accessed by a method with a "get_" prefix. In other
      words, if any of the following is true, it should be accessed by a method:
      - If the data access performs IO
      - If the data requires non-trivial compute
      - If the data should be a candidate for caching
      - If lazy loading is beneficial

    """   # noqa
    _path: str   # The immutable absolute path of this Inst
    _spec: Dict  # The immutable spec of this Inst

    @staticmethod
    def get(source: Union["Inst", dict],
            keys: Union[str, List[str]],
            default_value=None) -> Any:
        """Utility method to get value from a recursive dict tree or return None."""
        d = source._spec if isinstance(source, Inst) else source
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
    def gets(source: Union["Inst", dict], *dotted_keys) -> List[Any]:
        assert source is not None, "gets method requires a non None dict"
        source_ = source._spec if isinstance(source, Inst) else source
        results = []
        for dotted_key in dotted_keys:
            keys = dotted_key.split(".")
            results.append(Inst.get(source_, keys))
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
            Inst.set(source, keys, value)

    @staticmethod
    def exists(path: str) -> bool:
        """Checks if a given Inst exists (by looking for its _spec_ file)."""
        return os.path.exists(Inst._resolve_path(os.path.join(path, SPEC_JSON))) or \
            os.path.exists(Inst._resolve_path(os.path.join(path, SPEC_YAML)))

    @classmethod
    def load(cls: Type[T], name_or_path: str, *,
             cwd: Optional[str] = None, **kwargs) -> T:
        """Loads (Instantiates) this Inst from disk.

        Inst loading is generally lazy, so its attributes are loaded and
        cached only when accessed.

        Inst are searched in the following order:
        (1) as a fullpath to the folder of the Inst to load
        (2) as a relative path from the current working directory or cwd parameter
        (3) as a named inst under the INST_ROOT folder
        (4) as a named inst on S3 (LATER)

        :param name_or_path: Either the fullpath to the folder of the Inst to
            load or its name to be searched for
        :param cwd: used instead of current working dir for inst search
        :param kwargs: other kwargs are passed to the Inst constructor
        """
        from . import dat_config
        if os.path.isabs(name_or_path):
            path = name_or_path
        elif os.path.exists(path := os.path.join(cwd or os.getcwd(), name_or_path)):
            pass
        elif os.path.exists(path := os.path.join(dat_config.inst_folder,
                                                 Inst._resolve_path(name_or_path))):
            pass
        else:
            raise Exception(f"LOAD_INST: Could not find {name_or_path!r}")
        try:
            if os.path.exists(fpath := os.path.join(path, SPEC_JSON)):
                with open(fpath) as f:
                    spec = json.load(f)
            else:
                with open(os.path.join(path, SPEC_YAML)) as f:
                    spec = yaml.safe_load(f)
        except Exception as e:
            if not os.path.exists(path):
                raise Exception(F"LOAD_INST: Folder missing {path!r}.")
            else:
                raise Exception(f"LOAD_INST: Error loading {path!r}s spec file: {e}")
        klass_name = Inst.get(spec, MAIN_CLASS) or "Inst"
        klass = Inst._find_subclass_by_name(Inst, klass_name)
        if not klass:
            raise Exception(f"Class {klass_name} is not a subclass of Inst")

        # inst = Inst.__new__(klass)
        # inst._path, inst._spec = path, spec
        inst = klass(path=path, spec=spec, raw=True, **kwargs)
        return inst

    def __init__(self,
                 *,
                 path: str = None,
                 spec: Dict = None,
                 overwrite: bool = False,
                 raw: bool = False):
        """Creates a new Inst folder with the specified spec dict and path string.

        exists_action: "error" | "overwrite" | "use"

        PATH EXPANSION RULES:
        - Path is relative to the Inst.path_root() folder.
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
        if raw:
            self._path, self._spec = path, spec
            return
        self._path: str = self._resolve_path(
            self._expand_inst_path(path, overwrite=overwrite))
        self._spec: Dict = spec or {}
        Inst.set(self._spec, MAIN_CLASS, self.__class__.__name__)
        if not os.path.exists(self._path):
            os.makedirs(self._path)
        spec = self.get_spec()
        try:
            txt = json.dumps(spec, indent=2)
        except Exception as e:
            raise Exception(f"Error non-JSON in Inst.spec: {e}\nSPEC={spec}")
        with open(os.path.join(self._path, SPEC_JSON), "w") as out:
            out.write(txt)
            out.write("\n")

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.get_path_name()!r}>"

    def __str__(self):
        return self.__repr__()

    def get_spec(self):
        """Returns the spec of this Instantiable."""
        return self._spec

    def get_path(self):
        """Returns the absolute path of this Instantiable."""
        return self._path

    def get_path_name(self):
        """Returns the name (relative path) of this Instantiable."""
        return self._path2name(self._path)

    def get_path_tail(self):
        """Returns the shortname (last part of the path) of this Instantiable."""
        return self._path.split("/")[-1]

    def save(self) -> None:
        """Flags an instantiable to have a version of its folder's contents saved
        to in the backing store.
        """
        pass

    def delete(self):
        """Deletes the folder and its contents from the filesystem.
        This deletion will also be reflected as a deletion pushed to git.
        Still, the backing store will retain all previous versions of this Inst."""
        try:
            shutil.rmtree(self._path)
        except FileNotFoundError:
            raise Exception(f"INST DELETE: Folder missing {self._path!r}.")
        return True

    @staticmethod
    def _expand_inst_path(path_spec: Union[str, None], *,
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
                raise Exception(f"INST: Create failed, dir {expanded_path!r} exists")
            else:
                count += 1

    @staticmethod
    def _find_subclass_by_name(klass, name):
        if klass.__name__ == name:
            return klass
        for sub in klass.__subclasses__():
            if result := Inst._find_subclass_by_name(sub, name):
                return result
        return None

    @staticmethod
    def _path2name(path):
        from . import dat_config
        try:
            match = 1 + len(os.path.commonpath([dat_config.inst_folder, path]))
            return path[match:] if match > 2 else path
        except ValueError:
            return path

    @staticmethod
    def _resolve_path(name):
        from . import dat_config
        return os.path.join(dat_config.inst_folder, name)

        # if name and name[0] == "$":
        #     return name[1:].replace(".", "/")
        # else:
        #     return os.path.join(dat_config.inst_folder, name.replace(".", "/"))


class InstContainer(Inst, Generic[T]):
    """Container of multiple Insts.

    This Inst looks for other Insts recursively under its path, and exposes them via
    the attributes `insts` and `inst_paths`.

    The container can be type annotated with the containers that it's expected to have.

    Properties
    ----------
    inst_paths : List[str]
        List of pahts corresponding to the insts under this InstContainer.
    insts : List[Inst]
        List of Insts under this InstContainer

    Examples
    --------
    >>> game_set: InstContainer[Inst] = InstContainer.load("name/of/game/set")
    >>> game_set.insts[0]  # a Game inst!

    Notes
    -----

    The spec structure is assumed to be:
    {
        "main": {
            "class": "InstContainer"
        }
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._inst_paths: Union[DataState, List[str]] = DataState.NOT_LOADED
        self._insts: Union[DataState, List[T]] = DataState.NOT_LOADED

    @property
    def inst_paths(self) -> List[str]:
        """Lazy loaded list of full paths for the contained Inst."""
        if self._inst_paths is DataState.NOT_LOADED:
            self._inst_paths = InstContainer._find_inst_under(self._path)
        return self._inst_paths

    @property
    def insts(self) -> List[T]:
        """List of contained Inst objects.

        WARNING: ALL Insts remain in memory until this container is released.
        """
        if self._insts is DataState.NOT_LOADED:
            # these will load as the Inst class that was defined in each spec's
            # main.class, but we're loading them dynamically from Inst directly,
            # so we'll ignore the type and assume they will all be List[T]
            self._insts = [Inst.load(p) for p in self.inst_paths]  # type: ignore
        return self._insts  # type: ignore

    @staticmethod
    def _find_inst_under(root_path):
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


load_inst = Inst.load

# import ml_dat
# from ml_dat import ml_dat_config
# ml_dat.Inst = Inst
# ml_dat.InstContainer = InstContainer
# ml_dat.load_inst = load_inst
# data_folder = ml_dat_config.dat_config.inst_folder
