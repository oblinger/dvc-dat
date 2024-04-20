import json
import os
from enum import Enum, auto
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union
import yaml


# TODO:
# - Refactor Martin accessors into static methods
# - Get Inst into the folder structure properly, and provide
#   a copy of this for others to download locally for themselves
# - (with Dan) Get agreement from the team on toplevel on the inst folder.


SPEC_JSON = "_spec_.json"
SPEC_YAML = "_spec_.yaml"
MAIN_CLASS = "main.class"

# This default value is overridden by do._dat_setup()
data_folder = os.path.join(os.path.dirname(__file__), "inst_data")


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
    - The path indicating a folder in the local filesystem where the data for
      this persistable is stored.  (This path may also be the local caching
      for source contents that are stored in S3 or other locations.)
    - The spec can be
      - a dict, or
      - or the name of a loadable dict
    - In either case it is recursively expanded (see )
    - The expanded spec is saved in _spec_.json or _spec_.yaml in its folder.

    Persistable API
      .spec ................. Is the 'spec' dict for this inst
      .path ................. Returns the Path for this inst
      .name ................. Returns the name for this inst
      .load(path) ........... Universal loader for all Persistables
      .save([path]) ......... Saves persistable to disk (optionally sets its path)

    Utility Methods
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

    """
    path: str
    name: str
    spec: Dict

    def __init__(self, *, path: str, spec: Dict):
        self.path: str = os.path.abspath(path)
        self.name: str = self._path2name(self.path)
        self.spec: Dict = spec

    @staticmethod
    def get(source: Union["Inst", dict],
            keys: Union[str, List[str]],
            default_value=None) -> Any:
        """Utility method to get value from a recursive dict tree or return None."""
        d = source.spec if isinstance(source, Inst) else source
        if isinstance(keys, str):
            keys = keys.split(".")
        for k in keys:
            if d is None:
                return default_value
            elif not isinstance(d, dict):
                raise Exception(f"GET: Expected dict value for {k!r} not {d!r}")
            else:
                d = d.get(k)
        return d

    def __repr__(self):
        # kind = Inst.get(self, MAIN_CLASS) or "Inst"
        # parent = os.path.basename(os.path.dirname(self.path))
        # folder_name = os.path.basename(self.path)
        return f"<{self.__class__.__name__.upper()} {self.name}>"

    def __str__(self):
        return self.__repr__()

    @property
    def shortname(self):
        """Returns the shortname (last part of the name) of this Instantiable."""
        return self.name.split(".")[-1]

    @staticmethod
    def set(source: dict, keys, value) -> None:
        """Utility method into a recursive dict tree."""
        assert source is not None, "set method requires a non None dict"
        assert len(keys) > 0, "set method requires at least one key"
        d = source.spec if isinstance(source, Inst) else source
        if isinstance(keys, str):
            keys = keys.split(".")
        for k in keys[:-1]:
            if not isinstance(d, dict):
                raise Exception(f"Expected dict value for {k!r} not {d!r}")
            sub = d.get(k)
            if sub is None:
                sub = d[k] = {}
            d = sub
        d[keys[-1]] = value

    @staticmethod
    def gets(source: Union["Inst", dict], *dotted_keys) -> List[Any]:
        assert source is not None, "gets method requires a non None dict"
        source_ = source.spec if isinstance(source, Inst) else source
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

    @classmethod
    def load(
        cls: Type[T],
        name_or_path: str,
        *,
        cwd: Optional[str] = None,
        **kwargs,
    ) -> T:
        """Loads (Instantiates) this Inst from disk.

        Inst loading is generally lazy, so its attributes are loaded and
        cached only when accessed.

        When passed a name, it is searched in the following order:
        (1) searches the current working directory
        (2) then searches under INST_ROOT
        (3) then searches S3 (LATER)
        (4) then searches existing ML Flow artifacts (LATER)

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
        elif os.path.exists(path := os.path.join(dat_config.inst_folder, name_or_path)):
            pass
        else:
            path = os.path.abspath(path).replace(".", "/")
        try:
            if os.path.exists(fpath := os.path.join(path, SPEC_JSON)):
                with open(fpath) as f:
                    spec = json.load(f)
            else:
                with open(os.path.join(path, SPEC_YAML)) as f:
                    spec = yaml.safe_load(f)
        except FileNotFoundError:
            if not os.path.exists(path):
                raise Exception(F"Folder {path} isn't an instantiable, it's missing.")
            else:
                raise Exception(
                    f"Folder {path} is not an instantiable.  "
                    + "It does not have a _spec_... file."
                )
        klass_name = Inst.get(spec, MAIN_CLASS) or "Inst"
        klass = Inst._find_subclass_by_name(Inst, klass_name)
        if not klass:
            raise Exception(f"Class {klass_name} is not a subclass of Inst")
        inst = klass(path=path, spec=spec, **kwargs)
        return inst

    def save(self) -> None:
        """Writes an instantiable to disk.

        LATER: this will also push to S3 or ML Flow store
        """
        Inst.set(self.spec, MAIN_CLASS, self.__class__.__name__)
        if not os.path.exists(self.path):
            os.makedirs(self.path)
        with open(os.path.join(self.path, SPEC_JSON), "w") as out:
            txt = json.dumps(self.spec, indent=2)
            out.write(txt)
            out.write("\n")

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
        try:
            prefix = os.path.commonpath([data_folder, path])
            return path[len(prefix):].replace("/", ".")
        except ValueError:
            return "$" + path.replace("/", ".")[1:]

    @staticmethod
    def _name2path(name):
        if name and name[0] == "$":
            return name[1:].replace(".", "/")
        else:
            return os.path.join(data_folder, name.replace(".", "/"))


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
            self._inst_paths = InstContainer._find_inst_under(self.path)
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
