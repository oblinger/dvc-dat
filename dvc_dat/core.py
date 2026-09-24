"""dvc_dat core: configuration, the Dat manager, Dat, and spec expansion.

A Dat is a folder carrying a `_spec_.yaml` that is a complete, argumentless recipe
for itself, plus a `_result_.yaml` holding what running it produced.  The do-system
(`dvc_dat.do`) runs specs; this module stores and loads them.
"""

import contextlib
import contextvars
import hashlib
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
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, Generic, Iterator, List, Optional, Tuple, Type, TypeVar, Union

import yaml

logger = logging.getLogger(__name__)


# =============================================================================
# Utilities
# =============================================================================

def merge_dicts(*dicts: Dict, inplace: bool = False) -> Dict:
    """Recursively merge N dicts; each dict overrides the ones before it.

    Mappings merge key by key.  Two lists whose entries are all mappings with a
    `name` merge by name: a later entry merges into the earlier one of the same
    name, a new name is appended in the later list's order, and an entry
    `{name: X, remove: true}` deletes X.  Anything else, any other list
    included, is replaced whole by the later value.
    """
    if len(dicts) == 1:
        return dicts[0]
    dict_1 = dicts[0]
    if not inplace:
        dict_1 = deepcopy(dict_1)
    dict_2 = dicts[1]
    for k, v in dict_2.items():
        if isinstance(v, dict) and isinstance(dict_1.get(k), dict):
            dict_1[k] = merge_dicts(dict_1[k], v)
        elif _named_list(v) and _named_list(dict_1.get(k)):
            dict_1[k] = _merge_by_name(dict_1[k], v)
        else:
            dict_1[k] = deepcopy(v)
    return merge_dicts(dict_1, *dicts[2:])


def _named_list(value: Any) -> bool:
    """A non-empty list whose every entry is a mapping carrying a `name`."""
    return (isinstance(value, list) and bool(value)
            and all(isinstance(e, dict) and "name" in e for e in value))


def _merge_by_name(base: List[Dict], over: List[Dict]) -> List[Dict]:
    """`over` merged into `base` by each entry's `name` (see `merge_dicts`)."""
    merged = [deepcopy(e) for e in base]
    index = {e["name"]: i for i, e in enumerate(merged)}
    removed = set()
    for entry in over:
        name = entry["name"]
        if entry.get("remove") is True:
            removed.add(name)
        elif name in index:
            merged[index[name]] = merge_dicts(merged[index[name]], entry)
        else:
            index[name] = len(merged)
            merged.append(deepcopy(entry))
    return [e for e in merged if e["name"] not in removed]


# =============================================================================
# Configuration
# =============================================================================

DAT_CONFIG_FILE = ".datconfig.yaml"
DAT_CONFIG_OVERRIDE_FILE = ".datconfig.override.yaml"
ENV_PREFIX = "DAT_"
_CONFIG_KEYS = ("dat_folders", "art_folder", "manager", "run")    # `run`: `bin/dat` only
_DEFAULT_DAT_FOLDER = "data"
_DEFAULT_ART_FOLDER = "art"           # beside the dat folder, never inside it


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
    return values


def _check_keys(path: Optional[Path], values: Dict[str, Any], known: Tuple[str, ...]) -> None:
    """An unknown key is `ValueError`, naming the file and the known keys."""
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise ValueError(
            f"{path}: unknown config key(s) {unknown}; known keys are {list(known)}")


def _import_dotted(name: str) -> Any:
    """The object a dotted `module.attr` path names: the longest importable
    module, then `getattr` the rest."""
    parts = name.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:cut]))
        except ModuleNotFoundError as e:
            if e.name and ".".join(parts[:cut]).startswith(e.name):
                continue
            raise
        for attr in parts[cut:]:
            obj = getattr(obj, attr)
        return obj
    raise ImportError(f"no importable module in {name!r}")


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
DAT_DEPENDENCIES = "dat.dependencies"  # result: every dat and artifact the run loaded
DAT_SHA256 = "dat.sha256"              # result: the dat's content hash, stamped by save()
_HASH_PLACEHOLDER = "excluded"         # what dat.sha256 reads while the dat is hashed
DEP_MANUAL = "$MANUAL"                 # dependency of a dat sealed without a run
DEP_UNSEALED = "unsealed"              # the hash recorded for a dat not yet sealed

ART_PREFIX = "art:"                    # an artifact's name: art:<kind>/<rest>
ART_FILE = "_art_.yaml"                # an artifact's sidecar

# The dats recording right now, innermost last: a stack of (manager, dat).
_recording: "contextvars.ContextVar[Tuple[Tuple[DatManager, Dat], ...]]" = \
    contextvars.ContextVar("dvc_dat_recording", default=())

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


def _record(name: str, sha256: Optional[str]) -> None:
    """`name -> sha256` into the innermost recording dat's `dat.dependencies`;
    nothing when no dat is recording."""
    stack = _recording.get()
    if stack:
        results = stack[-1][1].get_results()
        deps = Dat.get(results, DAT_DEPENDENCIES, None)
        if deps is None:
            deps = {}
            Dat.set(results, DAT_DEPENDENCIES, deps)
        deps[name] = sha256


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_payload(folder: str, payload: str) -> str:
    """A file's hash is its bytes'; a folder's is the hash of its sorted
    `relpath\\0sha256\\n` lines, the top-level sidecar left out."""
    if payload != ".":
        return _sha256_file(os.path.join(folder, payload))
    lines = []
    for root, _, files in os.walk(folder):
        for file in files:
            rel = os.path.relpath(os.path.join(root, file), folder)
            if rel != ART_FILE:
                lines.append(f"{rel}\0{_sha256_file(os.path.join(root, file))}\n")
    return hashlib.sha256("".join(sorted(lines)).encode()).hexdigest()


def _hash_dat(folder: str, results: Dict[str, Any]) -> str:
    """`"sha256:<hex>"` over every file in a dat's folder, `_result_.yaml`
    included: it counts as its sorted-key dump with `dat.sha256` set to
    `excluded`, so the hash can sit inside the file it covers and a later
    check recomputes it the same way."""
    lines = []
    for root, _, files in os.walk(folder):
        for file in files:
            rel = os.path.relpath(os.path.join(root, file), folder)
            if rel != RESULT_YAML:
                lines.append(f"{rel}\0{_sha256_file(os.path.join(root, file))}\n")
    canonical = deepcopy(results or {})
    _dotted_set(canonical, DAT_SHA256.split("."), _HASH_PLACEHOLDER)
    text = yaml.dump(canonical, Dumper=_SpecDumper, sort_keys=True)
    lines.append(f"{RESULT_YAML}\0{hashlib.sha256(text.encode()).hexdigest()}\n")
    return "sha256:" + hashlib.sha256("".join(sorted(lines)).encode()).hexdigest()


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
    _art_folder: Optional[str]
    _config_dir: Optional[str]
    _dat_cache: "weakref.WeakValueDictionary[str, Dat]"
    _factories: Dict[str, Callable[[Path], Any]]

    def __init__(self, *, dat_folders: List[str], art_folder: Optional[str] = None,
                 do: Optional["Do"] = None):
        """A world on `dat_folders` -- searched in order by name, the first written
        to -- and `art_folder`, where artifacts live; with none, this world holds
        no artifacts.  The two never nest: an artifact folder inside a dat
        folder, or a dat folder inside it, is `ValueError`.  Nothing is read
        from disk.  `do` adopts an existing namespace with its mounts; adopting
        the default world's makes this the default world."""
        from .do import Do, _DefaultDo
        from . import dat_tools

        if isinstance(dat_folders, (str, Path)) or not isinstance(dat_folders, (list, tuple)):
            raise TypeError(f"DatManager: dat_folders is a list of folders, got {dat_folders!r}")
        if not dat_folders or not all(isinstance(f, (str, Path)) and str(f) for f in dat_folders):
            raise ValueError(f"DatManager: dat_folders needs at least one folder, got {dat_folders!r}")
        self._dat_folders = [os.path.realpath(str(f)) for f in dat_folders]
        self._art_folder = os.path.realpath(str(art_folder)) if art_folder is not None else None
        if self._art_folder is not None:
            for folder in self._dat_folders:
                if _within(self._art_folder, folder) or _within(folder, self._art_folder):
                    raise ValueError(
                        f"DatManager: art_folder {self._art_folder!r} and dat folder "
                        f"{folder!r} nest; artifact and dat names would collide -- keep "
                        "them apart (e.g. data/ and art/ side by side)")
        self._config_dir = None
        self._dat_cache = weakref.WeakValueDictionary()
        self._factories = {}

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
        `DAT_FOLDERS` / `DAT_ART_FOLDER` in the environment.  Relative folders
        resolve against the file's folder, which goes first on `sys.path`; with
        no file they resolve against `start`.  `art_folder` defaults to `art/`
        beside the file, a sibling of `data/`.  An unknown key is `ValueError`.
        `do` as in the constructor.

        A `manager:` key names the class to build, dotted (`mylab.store.Store`):
        a subclass of the class this is called on, imported once the config
        folder is on `sys.path`.  Its `CONFIG_KEYS` are extra keys it accepts,
        handed to its constructor as keyword arguments; any other unknown key is
        still an error.
        """
        start = Path(start) if start is not None else Path.cwd()
        name = DAT_CONFIG_FILE
        if start.is_file():
            start, name = start.parent, start.name
        config_path = _find_file_up(start, name)
        override_path = _find_file_up(start, DAT_CONFIG_OVERRIDE_FILE)
        file_values, override_values = _read_config(config_path), _read_config(override_path)
        values = merge_dicts(file_values, override_values)
        if (env := os.environ.get(ENV_PREFIX + "FOLDERS")):
            values["dat_folders"] = env
        if (env := os.environ.get(ENV_PREFIX + "ART_FOLDER")):
            values["art_folder"] = env
        root = os.path.realpath(config_path.parent if config_path else start)
        if root not in sys.path:
            sys.path.insert(0, root)    # the config folder is the import root
        klass = cls
        if (manager_name := values.get("manager")) is not None:
            if not isinstance(manager_name, str):
                raise ValueError(f"{config_path}: manager is a dotted class path, "
                                 f"got {manager_name!r}")
            klass = _import_dotted(manager_name)
            if not (isinstance(klass, type) and issubclass(klass, cls)):
                raise TypeError(f"{config_path}: manager {manager_name!r} is {klass!r}, "
                                f"not a subclass of {cls.__name__}")
        extra = tuple(getattr(klass, "CONFIG_KEYS", ()))
        _check_keys(config_path, file_values, _CONFIG_KEYS + extra)
        _check_keys(override_path, override_values, _CONFIG_KEYS + extra)
        folders = values.get("dat_folders", _DEFAULT_DAT_FOLDER)
        folders = [folders] if isinstance(folders, str) else folders
        if not isinstance(folders, list) or not all(isinstance(f, str) and f for f in folders):
            raise ValueError(f"{config_path}: dat_folders is a folder or a list of them, "
                             f"got {values.get('dat_folders')!r}")
        art_folder = values.get("art_folder", _DEFAULT_ART_FOLDER)
        if not (isinstance(art_folder, str) and art_folder):
            raise ValueError(f"{config_path}: art_folder is a folder, got {art_folder!r}")
        manager = klass(dat_folders=[os.path.join(root, f) for f in folders],
                        art_folder=os.path.join(root, art_folder), do=do,
                        **{k: values[k] for k in extra if k in values})
        manager._config_dir = root
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
        name: Union[str, Path],
        *,
        cache_after_load: bool = True,
    ) -> Any:
        """A dat, as the class its `dat.kind` names -- or an `art:<kind>/<rest>`
        artifact, through its kind's factory (a `Path` when none is registered).

        A dat is searched as an absolute path, in the do-system's mounts, then in
        each dat folder.  Inside a `recording`, the load lands in that dat's
        `dat.dependencies`.  `cache_after_load` applies to dats only.
        """
        if str(name).startswith(ART_PREFIX):
            return self._load_artifact(str(name))
        dat = self._load(name, cache_after_load=cache_after_load)
        _record(dat.get_path_name(), dat._sha256() or DEP_UNSEALED)
        return dat

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

    def load_path(self, name: Union[str, Path]) -> Path:
        """Where `load(name)` would find its object -- a dat's folder, or an
        artifact's payload -- as a `Path`, with nothing built: no factory runs.
        Recorded on the running dat exactly as `load` records it."""
        if str(name).startswith(ART_PREFIX):
            _, folder = self._art_path(str(name))
            sidecar_path = os.path.join(folder, ART_FILE)
            if not os.path.exists(sidecar_path):
                raise FileNotFoundError(f"load_path: no artifact {name!r} (no {sidecar_path})")
            sidecar = yaml.safe_load(Path(sidecar_path).read_text()) or {}
            _record(str(name), sidecar.get("sha256"))
            payload = sidecar.get("payload", ".")
            return Path(folder) if payload == "." else Path(folder, payload)
        dat = self._load(name)
        _record(dat.get_path_name(), dat._sha256() or DEP_UNSEALED)
        return Path(dat.get_path())

    def exists(self, name: Union[str, Path]) -> bool:
        """True if a dat's `_spec_` file is at `name` (resolved like `load`), or
        for an `art:` name, its `_art_.yaml`."""
        if str(name).startswith(ART_PREFIX):
            return os.path.exists(os.path.join(self._art_path(str(name))[1], ART_FILE))
        path = self._resolve_path(str(name))
        return os.path.exists(os.path.join(path, SPEC_JSON)) or os.path.exists(
            os.path.join(path, SPEC_YAML)
        )

    # -- artifacts -------------------------------------------------------------

    def register_artifact(self, kind: str, factory: Callable[[Path], Any]) -> None:
        """What `load` returns for `art:<kind>/...`: `factory(path)` -- a class whose
        constructor takes the path, else a lambda.  A second registration of a
        kind replaces the first."""
        if not isinstance(kind, str) or not kind or "/" in kind:
            raise ValueError(f"register_artifact: kind is a name without '/', got {kind!r}")
        if not callable(factory):
            raise TypeError(f"register_artifact: factory is a callable, got {factory!r}")
        self._factories[kind] = factory

    def save(self, source: Union[str, Path], name: str) -> str:
        """Copy the file or folder `source` in as artifact `name` (`art:<kind>/<rest>`),
        write its `_art_.yaml`, and return its hash, `"sha256:<hex>"`.

        A file lands as `<art_folder>/<kind>/<rest>/<basename>`, a folder's contents
        as `<art_folder>/<kind>/<rest>/`, the sidecar beside them.  Write-once: an
        existing name is `FileExistsError`.  Inside a `recording` the artifact
        lands in that dat's `dat.dependencies`.
        """
        kind, folder = self._art_path(name)
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(f"save: no file or folder at {str(source)!r}")
        if os.path.exists(folder):
            raise FileExistsError(f"save: artifact {name!r} exists at {folder!r}")
        if source.is_dir():
            shutil.copytree(source, folder)
            payload = "."
        else:
            os.makedirs(folder)
            shutil.copy2(source, os.path.join(folder, source.name))
            payload = source.name
        sha256 = "sha256:" + _hash_payload(folder, payload)
        sidecar = {"kind": kind, "name": name, "payload": payload, "sha256": sha256,
                   "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        Path(folder, ART_FILE).write_text(yaml.safe_dump(sidecar, sort_keys=False))
        _record(name, sha256)
        return sha256

    def _art_path(self, name: str) -> Tuple[str, str]:
        """`(kind, folder)` of an `art:<kind>/<rest>` name."""
        kind, _, rest = name[len(ART_PREFIX):].partition("/")
        if not name.startswith(ART_PREFIX) or not kind or not rest.strip("/"):
            raise ValueError(f"an artifact name is art:<kind>/<rest>, got {name!r}")
        if self._art_folder is None:
            raise RuntimeError(f"{name!r}: this manager has no art_folder; build it with "
                               "DatManager(..., art_folder=...) or set art_folder: in "
                               ".datconfig.yaml")
        folder = os.path.normpath(os.path.join(self._art_folder, kind, rest))
        if not _within(folder, os.path.join(self._art_folder, kind)):
            raise ValueError(f"artifact name {name!r} leaves the artifact folder")
        return kind, folder

    def _load_artifact(self, name: str) -> Any:
        kind, folder = self._art_path(name)
        sidecar_path = os.path.join(folder, ART_FILE)
        if not os.path.exists(sidecar_path):
            raise FileNotFoundError(f"load: no artifact {name!r} (no {sidecar_path})")
        sidecar = yaml.safe_load(Path(sidecar_path).read_text()) or {}
        _record(name, sidecar.get("sha256"))
        payload = sidecar.get("payload", ".")
        path = Path(folder) if payload == "." else Path(folder, payload)
        factory = self._factories.get(kind)
        return factory(path) if factory is not None else path

    # -- recording -------------------------------------------------------------

    @contextlib.contextmanager
    def recording(self, dat: "Dat") -> Iterator[None]:
        """Every `load` (and `save`) inside the block lands in `dat.dependencies`.
        `execute` runs its function inside one.  Blocks nest: when an inner block
        ends, its dat becomes one entry of the outer one."""
        with self._capture(dat) as outer:
            yield
        if outer is not None:
            _record(dat.get_path_name(), dat._sha256() or DEP_UNSEALED)

    @contextlib.contextmanager
    def _capture(self, dat: "Dat") -> Iterator[Optional["Dat"]]:
        """Push `dat` as the recording dat; yields the dat it would be recorded
        into when the block ends (None at top level, or when that is itself)."""
        stack = _recording.get()
        token = _recording.set(stack + ((self, dat),))
        try:
            yield stack[-1][1] if stack and stack[-1][1] is not dat else None
        finally:
            _recording.reset(token)

    def record_dependency(self, name: str, sha256: Optional[str] = None) -> None:
        """Add `name -> sha256` to the recording dat's `dat.dependencies`, for what
        a run used without a `load`.  `RuntimeError` when nothing is recording."""
        if not _recording.get():
            raise RuntimeError("record_dependency: no dat is recording")
        _record(name, sha256)

    def _roots(self, deps: Dict[str, Any]) -> Dict[str, Any]:
        """`deps` less every entry that some other entry's dat already lists
        among its own dependencies."""
        below: set = set()
        for name in deps:
            if name.startswith(ART_PREFIX) or name == DEP_MANUAL:
                continue
            try:
                dat = self._load(name)
            except (KeyError, FileNotFoundError):
                continue
            below.update(Dat.get(dat.get_results(), DAT_DEPENDENCIES, None) or {})
        return {k: v for k, v in deps.items() if k not in below}

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
        names, loaded through this world's `do`, inside `recording(dat)`; then
        records `dat.run_at`, `dat.run_time`, `dat.code` (the branch, commit and
        dirty flag of the git checkout holding `fn`'s source; nothing outside a
        checkout) and `dat.dependencies` (every dat and artifact the run loaded,
        name to hash) in its results.  It does not save them: a `dat.save()`
        inside `fn` seals the dat once `fn` returns, with the whole record, and
        one after the run seals it then.  A sealed dat is refused.  Every run in
        this world comes here -- `do(...)` and the `do(...)` calls nested inside a
        running function alike -- so a subclass that wraps this wraps every run.
        Returns `fn`'s value, or `dat` when there is no `dat.do`.
        """
        spec = dat.get_spec()
        fn = Dat.get(spec, DAT_DO, None)
        if fn is None:
            return dat
        if isinstance(fn, str):
            fn = self.do.load(fn)
        if not callable(fn):
            raise TypeError(f"{DAT_DO} in {dat!r} is {fn!r}, not callable")
        if dat.sealed:
            raise RuntimeError(f"execute: {dat!r} is sealed; fork it with do(dat, ...) "
                               "or copy it")
        args = list(Dat.get(spec, DAT_ARGS, None) or [])
        kwargs = dict(Dat.get(spec, DAT_KWARGS, None) or {})
        run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        Dat.set(dat.get_results(), DAT_DEPENDENCIES, {})    # a run with no loads says so
        before = time.time()
        dat._running, dat._save_asked = True, False
        try:
            with self._capture(dat) as outer:
                result = fn(dat, *args, **kwargs)
        finally:
            dat._running = False
        time_ms = (time.time() - before) * 1000
        exec_time = (time.strftime("%H:%M:%S", time.gmtime(time_ms // 1000))
                     + ".{:03d}".format(int(time_ms % 1000)))
        Dat.set(dat.get_results(), DAT_RUN_AT, run_at)
        Dat.set(dat.get_results(), DAT_RUN_TIME, exec_time)
        if (code := _code_of(fn)) is not None:
            Dat.set(dat.get_results(), DAT_CODE, code)
        if dat._save_asked:
            dat._seal(manual=False)
        if outer is not None:           # recorded by its final hash, if it has one
            _record(dat.get_path_name(), dat._sha256() or DEP_UNSEALED)
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
    `DatManager.load_dat_config()`.  `Run.manager is Dat.manager`.  And `do`,
    the default world's runner and namespace."""

    @property
    def do(cls) -> Any:
        """The default world's runner and namespace: a forwarder to
        `Dat.manager.do`, whichever manager that is when it is called, so
        `do = Dat.do` binds a shortcut that follows a later reassignment."""
        from .do import do
        return do

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
        self._running = False           # inside its own execute
        self._save_asked = False        # save() was called while running

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

    merge_dicts = staticmethod(merge_dicts)

    @staticmethod
    def cli_main(argv: Optional[List[str]] = None, *,
                 config: Union[None, str, Path] = None) -> int:
        """The `dat` command line, for a program's own main; see `dvc_dat.do.cli_main`."""
        from .do import cli_main
        return cli_main(argv, config=config)

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

    @property
    def sealed(self) -> bool:
        """True once the dat has been saved: its results carry `dat.sha256`."""
        return Dat.get(self._result, DAT_SHA256, None) is not None

    def save(self) -> None:
        """Seal the dat: write `_result_.yaml`, stamping `dat.sha256` with the hash
        of the whole folder as it now stands.  Once only -- a second save is
        refused.

        Called inside the dat's own run, the seal waits for the run to end, so
        the record is whole.  Called anywhere else, the dat gets the dependency
        `$MANUAL`: it was made or finished by hand, and its dependencies are
        incomplete.  A dependency
        that was itself unsealed when loaded taints the dat: it is written but
        never sealed, and may be saved again.  At the seal, a dependency that is
        already a dependency of another entry is dropped, so the map holds the
        roots only.
        """
        if self._running:
            self._save_asked = True
            return
        self._seal(manual=True)

    def _seal(self, *, manual: bool) -> None:
        if self.sealed:
            raise RuntimeError(f"save: {self!r} is sealed; a dat is saved once")
        deps = Dat.get(self._result, DAT_DEPENDENCIES, None)
        if manual:
            deps = dict(deps or {})
            deps.setdefault(DEP_MANUAL, "manual")
        if deps:
            deps = self._world()._roots(deps)
            Dat.set(self._result, DAT_DEPENDENCIES, deps)
        if DEP_UNSEALED not in (deps or {}).values():
            Dat.set(self._result, DAT_SHA256, _hash_dat(self._path, self._result))
        with Path(self.get_path(), RESULT_YAML).open("w") as out:
            yaml.dump(self._result, out, Dumper=_SpecDumper, sort_keys=False)

    def verify(self) -> bool:
        """True when the folder on disk still hashes to the `dat.sha256` its
        `_result_.yaml` carries -- the dat is exactly as it was last saved."""
        result_path = Path(self._path, RESULT_YAML)
        if not result_path.exists():
            return False
        on_disk = yaml.safe_load(result_path.read_text()) or {}
        stored = Dat.get(on_disk, DAT_SHA256, None)
        return stored is not None and stored == _hash_dat(self._path, on_disk)

    def _sha256(self) -> Optional[str]:
        """The seal's hash; None while the dat is unsealed."""
        return Dat.get(self._result, DAT_SHA256, None)

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

