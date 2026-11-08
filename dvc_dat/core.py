"""dvc_dat core: configuration, the Dat manager, Dat, and spec expansion.

A Dat is a folder carrying a `_spec_.yaml` that is a complete, argumentless recipe
for itself, plus a `_result_.yaml` holding what running it produced.  The namespace
(`dvc_dat.do`) names specs; this module stores and loads them.  A Dat is also a
ledger `Value` (DAT 1038): its folder is its bytes, by the folder codec below, so
`dat.seal(t)` saves it and `rev.load(name)` brings it back with no subclass.
"""

import contextlib
import contextvars
import hashlib
import importlib
import inspect
import json
import logging
import os
import shutil
import socket
import subprocess
import time
import weakref
from copy import deepcopy
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Generic, Iterator, List, Optional, Tuple, Type, TypeVar, Union

import yaml

from .expand import UNIQUE_REF, Template, has_unique, refuse_old_name
from .ledger import hooks
from .ledger.codec import NO_DEFAULT, dotted_get, dotted_set
from .ledger.env import CODE_PATHSPEC
from .ledger.ledger import refuse_removed
from .ledger.value import FrozenPreds, Value, check_name

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
        elif _named_list(v):                # nothing to merge into: a `remove` entry deletes nothing
            dict_1[k] = _merge_by_name([], v)
        else:
            dict_1[k] = deepcopy(v)
    return merge_dicts(dict_1, *dicts[2:])


def _named_list(value: Any) -> bool:
    """A non-empty list whose every entry is a mapping carrying a `name`."""
    return (isinstance(value, list) and bool(value)
            and all(isinstance(e, dict) and "name" in e for e in value))


def _merge_by_name(base: List[Dict], over: List[Dict]) -> List[Dict]:
    """`over` merged into `base` by each entry's `name` (see `merge_dicts`)."""
    merged = [deepcopy(e) for e in base if e.get("remove") is not True]
    for entry in over:                      # in order: a name removed, then given again, is back
        at = next((i for i, e in enumerate(merged) if e["name"] == entry["name"]), None)
        if entry.get("remove") is True:
            if at is not None:
                del merged[at]
        elif at is not None:
            merged[at] = merge_dicts(merged[at], entry)
        else:
            merged.append(deepcopy(entry))
    return merged


# =============================================================================
# Configuration
# =============================================================================

DAT_CONFIG_FILE = ".datconfig.yaml"
ENV_PREFIX = "DAT_"
_CONFIG_KEYS = ("dat_folders", "art_folder", "index", "manager", "verify",
                "run",                 # `just run` only
                "root", "default", "mounts", "stores",    # the ledger's (`ledgers`, `L`, `register_store`), read there
                "namespace")           # `ledger`: the project's names are its ledger's
_DEFAULT_DAT_FOLDER = "data"
_DEFAULT_ART_FOLDER = "art"           # beside the dat folder, never inside it


def _ledger_namespace(config_path: Optional[Path], values: Dict[str, Any]) -> bool:
    """Whether the project's names are its active ledger's `db/mount` rows (DAT 1046): `namespace: ledger`, the
    one switch (SVP 239)."""
    mode = values.get("namespace")
    if mode is None:
        return False
    if mode != "ledger":
        raise ValueError(f"{config_path}: namespace is 'ledger' or absent, got {mode!r}")
    return True


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
DAT_DEFAULTS = "dat.defaults"          # plain values, read by a template as ${dat.defaults.x}
DAT_PREDS = "dat.preds"                # preds the value carries, each an expanded string
DAT_RUN_AT = "dat.run_at"              # run: when it started
DAT_RUN_TIME = "dat.run_time"          # run: how long it took
DAT_RUN_REV = "dat.run_rev"            # run: the `<ledger>@<rev>` it ran against, when it ran on a ledger
DAT_CODE = "dat.code"                  # run: branch, commit, dirty of the code it ran
DAT_HOST = "dat.host"                  # run: the machine
DAT_PID = "dat.pid"                    # run: the process
DAT_CONTENT = "dat.content"            # run: the dat.sha256 it sealed
DAT_DEPENDENCIES = "dat.dependencies"  # result: every dat and artifact the run loaded
DAT_SHA256 = "dat.sha256"              # result: the dat's content hash, stamped by save()
_HASH_PLACEHOLDER = "excluded"         # what dat.sha256 reads while the dat is hashed
DAT_HASH = "dat.hash"                  # result: `functional` since 3.0 -- the rule dat.sha256 follows
HASH_FUNCTIONAL = "functional"         # ... name and run/ left out; the only rule (SVP 1467 Q9)
DEP_MANUAL = "$MANUAL"                 # dependency of a dat sealed without a run
DEP_UNSEALED = "unsealed"              # the hash recorded for a dat still open
DAT_STANDING = "dat.standing"          # spec: a demand; results: what the last save earned

# A dat's standing, a ladder of how far it can be relied on.  `rolling` is saved
# again at will; `open` may still change; `sealed` is frozen; `referenceable` is
# frozen and made from clean committed code out of referenceable inputs only.
ROLLING, OPEN, SEALED, REFERENCEABLE = "rolling", "open", "sealed", "referenceable"
STANDINGS = (ROLLING, OPEN, SEALED, REFERENCEABLE)
_FROZEN = (SEALED, REFERENCEABLE)
_RANK = {OPEN: 0, SEALED: 1, REFERENCEABLE: 2}   # as an input, rolling counts as sealed
_SPEC_DEMANDS = (ROLLING, REFERENCEABLE)          # what a spec may ask for

URN_PREFIX = "sha256:"                 # every stored thing answers to sha256:<hex>
ART_FILE = "_art_.yaml"                # an artifact's sidecar
INDEX_FILE = "_index_.json"            # names and URNs of the store, one namespace
_URN_FOLDER = "sha256"                 # where an unnamed artifact lives: sha256/<hex>/
RUN_FOLDER = "run"                     # the run sub-dat: the one execution that made the dat
WORK_FOLDER = "work"                   # its scratch, the working directory while it runs

# The dats recording right now, innermost last: a stack of (manager, dat).
_recording: "contextvars.ContextVar[Tuple[Tuple[DatManager, Dat], ...]]" = \
    contextvars.ContextVar("dvc_dat_recording", default=())

_DEFAULT_PATH_TEMPLATE = "anonymous/Dat${unique:}"
_NAME_KEY = "_dat_name_"            # where the folder's name template sits while the spec resolves


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


def _record_dat(dat: "Dat") -> None:
    """Record `dat` in the running dat's dependencies -- by its hash, `unsealed`
    while it is open -- and refuse it when that dat demands `dat.standing:
    referenceable` and `dat` is not.  A dat inside the running dat's folder is
    its subdat, output and not input: nothing is recorded."""
    stack = _recording.get()
    if not stack:
        return
    runner = stack[-1][1]
    if _inside(dat.get_path(), runner.get_path()):
        return                          # a subdat is the running dat's output, never its input (SVP 241)
    standing = dat._standing()
    sha256 = dat._sha256()
    _record(dat.get_path_name(),
            DEP_UNSEALED if standing == OPEN or sha256 is None else sha256)
    if runner._demands_referenceable() and standing != REFERENCEABLE:
        raise RuntimeError(f"{runner!r} demands dat.standing: referenceable, and "
                           f"{dat.get_path_name()!r} is {standing}")


def _inside(path: Union[str, Path], folder: Union[str, Path]) -> bool:
    """Is `path` strictly inside `folder`?"""
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path.startswith(folder + os.sep)


def is_subdat_dir(path: Union[str, Path]) -> bool:
    """Is the folder `path` a dat: does its `_spec_.yaml` or `_spec_.json` name `dat.kind`?  Inside another
    dat's folder such a folder is a subdat, like a git repo inside a git repo: out of the enclosing dat's
    bytes and both its hashes, and sealed as a value of its own (SVP 241)."""
    path = os.fspath(path)
    if not (os.path.exists(os.path.join(path, SPEC_YAML)) or os.path.exists(os.path.join(path, SPEC_JSON))):
        return False
    return Dat.spec_kind(path) is not None


def subdat_dirs(folder: Union[str, Path]) -> Iterator[Tuple[str, Path]]:
    """`(relpath, path)` of each subdat of the dat folder `folder`, sorted: the nearest dats below it; what
    lies inside a subdat is that subdat's."""
    for root, dirs, _names in os.walk(folder):
        kept = []
        for d in sorted(dirs):
            p = Path(root, d)
            if d == "__pycache__":
                continue
            if is_subdat_dir(p):
                yield p.relative_to(folder).as_posix(), p
            else:
                kept.append(d)
        dirs[:] = kept


def _standing_of(spec: Dict[str, Any], result: Dict[str, Any]) -> str:
    """A dat's standing from its spec and its results as written: the one every
    save stamps; with none (never saved), rolling when the spec demands it,
    else open."""
    stamped = Dat.get(result, DAT_STANDING, None)
    if stamped is not None:
        return stamped
    return ROLLING if Dat.get(spec, DAT_STANDING, None) == ROLLING else OPEN


def _sidecar_names(sidecar: Dict[str, Any]) -> List[str]:
    """Every name an artifact's sidecar gives it."""
    return list(sidecar.get("names") or [])


def _payload_size(path: Path) -> int:
    """Bytes in a file, or in every file of a folder but its top-level sidecar."""
    if not path.is_dir():
        return path.stat().st_size
    total = 0
    for root, _, files in os.walk(path):
        for file in files:
            full = os.path.join(root, file)
            if os.path.relpath(full, path) != ART_FILE:
                total += os.path.getsize(full)
    return total


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


def _hash_dat(folder: Union[str, Path], results: Dict[str, Any]) -> str:
    """`"sha256:<hex>"` over a dat's folder by the functional rule, the only one
    (`dat.hash: functional`, stamped by every save, names it; a hash a 2.x save
    stamped does not verify, SVP 1467 Q9).

    Every file but its subdats (`is_subdat_dir`: `run/` and any other dat in
    its folder tree) and `dat.name` -- a subdat is a value of its own, and the
    name is the dat's address, neither is content -- so two runs of one recipe
    at two places hash the same when the code is functional.  `_spec_.yaml` counts as its sorted-key dump with
    `dat.name` left out, `_result_.yaml` as its sorted-key dump with
    `dat.sha256` set to `excluded`, so the hash can sit inside the file it
    covers and a later check recomputes it the same way."""
    folder = os.fspath(folder)          # a Path would never equal os.walk's str root
    lines = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not is_subdat_dir(os.path.join(root, d))]
        for file in files:
            rel = os.path.relpath(os.path.join(root, file), folder)
            if rel in (RESULT_YAML, SPEC_YAML, SPEC_JSON):
                continue
            lines.append(f"{rel}\0{_sha256_file(os.path.join(root, file))}\n")
    if os.path.exists(os.path.join(folder, SPEC_YAML)):
        spec = yaml.safe_load(Path(folder, SPEC_YAML).read_text()) or {}
    else:                               # a `_spec_.json` is read too (spec-format), and hashed as its spec
        spec = json.loads(Path(folder, SPEC_JSON).read_text()) or {}
    if isinstance(spec.get("dat"), dict):
        spec["dat"].pop("name", None)
    text = yaml.dump(spec, Dumper=_SpecDumper, sort_keys=True)
    lines.append(f"{SPEC_YAML}\0{hashlib.sha256(text.encode()).hexdigest()}\n")
    canonical = deepcopy(results or {})
    dotted_set(canonical, DAT_SHA256.split("."), _HASH_PLACEHOLDER)
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
    on a detached HEAD; `dirty` counts tracked files only, and none whose path
    the repo's `.gitattributes` marks `dat-noncode`."""
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
    status = _git(folder, "status", "--porcelain", "--untracked-files=no", "--", *CODE_PATHSPEC)
    return {"branch": None if branch in (None, "HEAD") else branch,
            "commit": commit, "dirty": bool(status)}


def _write_run(run: "Dat") -> None:
    """Write a run sub-dat's `_result_.yaml`: no hash (its scratch is not
    content, and may be large), `dat.standing: sealed` once it has finished."""
    results = run.get_results()
    if Dat.get(results, DAT_RUN_TIME, None) is not None:
        Dat.set(results, DAT_STANDING, SEALED)
    with Path(run.get_path(), RESULT_YAML).open("w") as out:
        yaml.dump(results, out, Dumper=_SpecDumper, sort_keys=False)
    run._written = _standing_of(run.get_spec(), results)


_NO_ARG = NO_DEFAULT


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


def check_preds(spec: Dict[str, Any]) -> None:
    """Refuse an expanded spec's `dat.preds` (SVP 1508) unless it is a mapping of pred names (str, not
    `db/...`) to strings, numbers or bools."""
    preds = Dat.get(spec, DAT_PREDS, None)
    if preds is None:
        return
    if not isinstance(preds, dict):
        raise TypeError(f"dat.preds is a mapping of pred names to values, not {preds!r}")
    for k, v in preds.items():
        if not isinstance(k, str) or not k or k.startswith("db/"):
            raise ValueError(f"dat.preds: {k!r} is not a pred name (a non-empty str outside db/)")
        if not isinstance(v, (str, int, float, bool)):
            raise TypeError(f"dat.preds: {k} expanded to {type(v).__name__}, not a string, number or bool")


# =============================================================================
# DatManager
# =============================================================================

class DatManager:
    """A world of dats: the dat folders, and the namespace that names things in them.

    A manager owns its `ns` -- a `Namespace` bound to it, carrying its mounts and its
    `load` -- and everything the manager does (a dotted spec, `dat.base`, `{}`
    expansion, path resolution, every run) goes through that `ns`.  `run` is the
    one way to run a dat outside a ledger.  The process's default world is
    `Dat.manager`, built on first use by `DatManager.load_dat_config()` and
    replaced by assigning to it.  Any number of others coexist.  `ns` is the
    only public attribute.
    """

    ns: "Namespace"
    _dat_folders: List[str]
    _art_folder: Optional[str]
    _config_dir: Optional[str]
    _config_file: Optional[str]
    _dat_cache: "weakref.WeakValueDictionary[str, Dat]"
    _index_file: str

    def __init__(self, *, dat_folders: List[str], art_folder: Optional[str] = None,
                 index: Optional[str] = None, ns: Optional["Namespace"] = None,
                 verify: bool = False):
        """A world on `dat_folders` -- searched in order, the first written to -- and `art_folder`, where artifacts live.

        With none, this world holds no artifacts. The two never nest: an artifact folder inside a dat folder, or a dat
        folder inside it, is `ValueError`. Nothing is read from disk. `ns` adopts an existing namespace with its
        mounts, and adopting the default world's makes this the default world; with none, a fresh `Namespace` is
        built. Every manager mounts `dvc_dat.dat_tools` at `dt`. `verify` sets the default of every load's `verify`,
        which re-hashes against the stored `sha256` (see `load`). `index` is the file keying every name and `sha256:`
        URN of the store, default `_index_.json` in the artifact folder, else in the first dat folder.

        A string (or any non-list) for `dat_folders` is `TypeError`, an empty list `ValueError`; a non-bool `verify`
        is also `TypeError`.
        """
        from .do import _DefaultNamespace
        from .namespace import Namespace
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
        self._config_file = None       # the .datconfig.yaml load_dat_config read, if any
        self._dat_cache = weakref.WeakValueDictionary()
        self._index_file = os.path.realpath(str(index)) if index is not None else \
            os.path.join(self._art_folder or self._dat_folders[0], INDEX_FILE)
        self._index_cache: Optional[Tuple[Tuple[int, int], Dict[str, Dict[str, str]]]] = None
        if not isinstance(verify, bool):
            raise TypeError(f"DatManager: verify is True or False, got {verify!r}")
        self._verify = verify

        default = False
        if isinstance(ns, _DefaultNamespace):
            ns, default = ns._current(), True
        elif ns is not None and _default_manager is not None and ns is _default_manager.ns:
            default = True
        self.ns = Namespace(manager=self) if ns is None else ns
        """The namespace of this world, its only public attribute.

        `m.ns.mount(...)` adds names to it, `m.ns.load(...)` resolves them; it is not callable.
        """
        self.ns._manager = self
        self.ns._reg_module("dt", dat_tools, allow_redefine=True)     # the world's own names, any `ns`
        self.ns._reg_value("dt.list", dat_tools.cmd_list)
        if default:
            Dat.manager = self

    @classmethod
    def load_dat_config(cls, start: Union[str, Path, None] = None, *,
                        ns: Optional["Namespace"] = None) -> "DatManager":
        """A new manager from the `.datconfig.yaml` found walking up from `start`.

        Default the working directory; a file path names the config file itself. Precedence, lowest to highest: the
        file, then `DAT_FOLDERS` (one folder, not split) / `DAT_ART_FOLDER` in the environment; there is no override
        file (SVP 239), and one beside the config is `ValueError`, as is a removed key (`ledger:`, `ledgers:`) naming
        what replaces it. Relative folders resolve against the file's folder, which goes first on `sys.path`; with no file
        they resolve against `start`. `art_folder` defaults to `art/` beside the file, a sibling of `data/`; `index:`
        moves the store's index file. An unknown key, or a malformed value, is `ValueError`. `ns` as in the
        constructor.

        `namespace: ledger`, the one switch (SVP 239), makes the namespace the active ledger's (DAT 1046): `ns` is a
        `LedgerNamespace`, its names the ledger's `db/mount` rows at the head, and `mount` refused; an adopted `ns`
        that is not one is not kept. `root:` and `default:` alone keep the plain namespace.

        A `manager:` key names the class to build, dotted (`mylab.store.Store`): a subclass of the class this is
        called on, imported once the config folder is on `sys.path`; a `manager:` that is not a subclass is
        `TypeError`. Its `CONFIG_KEYS` are extra keys it accepts, handed to its constructor as keyword arguments; any
        other unknown key is still an error. See [Configuration][configuration].
        """
        start = Path(start) if start is not None else Path.cwd()
        name = DAT_CONFIG_FILE
        if start.is_file():
            start, name = start.parent, start.name
        config_path = _find_file_up(start, name)
        file_values = _read_config(config_path)
        refuse_removed(config_path, file_values)
        values = dict(file_values)
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
        folders = values.get("dat_folders", _DEFAULT_DAT_FOLDER)
        folders = [folders] if isinstance(folders, str) else folders
        if not isinstance(folders, list) or not all(isinstance(f, str) and f for f in folders):
            raise ValueError(f"{config_path}: dat_folders is a folder or a list of them, "
                             f"got {values.get('dat_folders')!r}")
        verify = values.get("verify", False)
        if not isinstance(verify, bool):
            raise ValueError(f"{config_path}: verify is true or false, got {verify!r}")
        art_folder = values.get("art_folder", _DEFAULT_ART_FOLDER)
        if not (isinstance(art_folder, str) and art_folder):
            raise ValueError(f"{config_path}: art_folder is a folder, got {art_folder!r}")
        extra_values = {k: values[k] for k in extra if k in values}
        if (index := values.get("index")) is not None:
            if not (isinstance(index, str) and index):
                raise ValueError(f"{config_path}: index is a file, got {index!r}")
            extra_values["index"] = os.path.join(root, index)
        make_default = False
        if config_path is not None and _ledger_namespace(config_path, values):
            from .do import _DefaultNamespace
            from .ledger.namespace import LedgerNamespace

            adopted = ns._current() if isinstance(ns, _DefaultNamespace) else ns
            make_default = ns is not None and (isinstance(ns, _DefaultNamespace) or (
                _default_manager is not None and ns is _default_manager.ns))
            ns = adopted if isinstance(adopted, LedgerNamespace) else LedgerNamespace(config=config_path)
        manager = klass(dat_folders=[os.path.join(root, f) for f in folders],
                        art_folder=os.path.join(root, art_folder), ns=ns, verify=verify,
                        **extra_values)
        manager._config_dir = root
        manager._config_file = str(config_path) if config_path is not None else None
        if make_default:
            Dat.manager = manager
        return manager

    def create(self, spec: Union[Dict, str, None] = None, *, path: Union[str, Path, None] = None,
               **kwargs: Any) -> "Dat":
        """Create a dat, as the class its `dat.kind` names, and run nothing.

        Merge `dat.base`, merge `kwargs` into `dat.kwargs`, run `validate_spec`, place it, write `_spec_.yaml` with
        its keys sorted, so equal specs give the same bytes (no `_result_.yaml` is written). `spec` may be a dict or a
        dotted name loaded through `ns`. `kwargs` are data
        (1467 Q2 (A)): they reach `dat.kwargs` as given, `${` and all (`spec` and `path` are this call's own names,
        never keywords). The folder is `path` if given, else the spec's `dat.name` template, else
        `anonymous/Dat${unique:}`, under the first dat folder; `dat.target_exists` says what happens when the folder is
        already there -- `FileExistsError` by default, and `use` returns the dat already there. Every `${…}` in the
        spec is resolved here, once, with the same moment and count the folder got (doc/expand.md): `${batch}` a node
        of the merged spec, `${ns:a.b}` a namespace name, `${now:%Y}`, `${unique:}`, `${cwd:}` the built-ins.
        `dat.preds` (a mapping) is resolved with the rest, and each value must come out a string, number or bool:
        they are the dat's own preds, carried onto the value when it is sealed. The resolved spec is what is written,
        except `dat.name`: the spec stores the path template as given (`path`, else the spec's own), never the path it
        resolved to (F447 Q36); the folder's path is the dat's name. A `dat.name` in the `{…}` grammar retired in 3.0
        (`{YYYY}`, `{unique}`, `{a.b}`) is `ValueError` naming its new spelling. `dat.kind` is written as the
        class's dotted `module.qualname`. `run` is `create` and then the run.

        A name an artifact holds is `FileExistsError`; a spec that is not YAML data once resolved is `TypeError`. See
        [The spec is the record][the-spec-is-the-record].
        """
        return self._create(spec, path=path, kwargs=kwargs)[0]

    def _create(self, spec: Union[Dict, str, None], *, path: Union[str, Path, None] = None,
                kwargs: Optional[Dict[str, Any]] = None) -> Tuple["Dat", bool]:
        """`create`, returning `(dat, skipped)`: `skipped` when `dat.target_exists: use` found the
        dat already there (it is loaded, not made)."""
        from .namespace import Namespace

        spec = self._spec_of(spec)
        if kwargs:
            spec = Namespace._fork_spec(spec, (), kwargs)
        dat_class = self._class_of(spec["dat"].get("kind"))
        spec["dat"]["kind"] = _kind_name(dat_class)
        spec = dat_class.validate_spec(spec)

        own = Dat.get(spec, DAT_NAME, None)
        if path is None:
            path = own or _DEFAULT_PATH_TEMPLATE
        path = str(path)
        template = path
        refuse_old_name(template)
        target_exists = Dat.get(spec, DAT_TARGET_EXISTS, "error")
        if target_exists == "overwrite" and path.lower() == "${cwd:}":
            target_exists = "error"  # never wipe the working directory
        if target_exists == "increment" and not has_unique(path):
            path += UNIQUE_REF       # a plain name counts up as `_2`, `_3`, ...

        # one resolve of the spec, the folder's name at its root: `${dat.kwargs.game}` in a name reads the spec,
        # and the name is resolved again as the count climbs, with the same moment
        names = Template({**spec, _NAME_KEY: path}, load=self.ns.load, tz=self.ns._tz())
        expanded_path, skip_execution, count = self._place(path, lambda n: names.name(_NAME_KEY, n),
                                                           target_exists=target_exists, wipe=False)
        if skip_execution:
            return self.load(expanded_path), True

        path = self._resolve_path(expanded_path)
        spec = names.tree(count)
        spec.pop(_NAME_KEY)
        check_preds(spec)
        if own is not None:
            Dat.set(spec, DAT_NAME, own)            # the template, never its resolution (Q36)
        within = _within(os.path.realpath(path), self._dat_folders[0])
        if within:
            Dat.set(spec, DAT_NAME, template if "${" in template else self._get_path_name(path))
            if self._artifact_folder(self._get_path_name(path)) is not None:
                raise FileExistsError(f"Dat.create: {self._get_path_name(path)!r} is an "
                                      "artifact's name; dats and artifacts share one namespace")
        try:
            text = yaml.dump(spec, Dumper=_SpecDumper, sort_keys=True)
        except yaml.representer.RepresenterError as e:
            raise TypeError(
                f"Dat.create: the spec is not data once resolved ({e.args[0]}); a "
                "`${...}` reference in a spec must resolve to something YAML can hold"
            ) from None
        if target_exists == "overwrite" and os.path.exists(path):
            self._refuse_delete_on_a_ledger("Dat.create with target_exists: overwrite would delete "
                                            f"{self._get_path_name(path)!r}")
            # wiped only now the new spec is in hand: a create that fails keeps the old dat
            self._dat_cache.pop(os.path.abspath(path), None)    # a held object is not the new dat
            if within:
                self._index_forget(self._get_path_name(path))
            shutil.rmtree(path)
        os.makedirs(path, exist_ok=True)
        logger.info("Creating Dat %s under path: <%s>", dat_class, path)
        Path(path, SPEC_YAML).write_text(text)
        return self._load(path, dat_class=dat_class), False

    def _spec_of(self, spec: Union[Dict, str, None]) -> Dict:
        """A private copy of `spec` (a dict, or a dotted name loaded through `ns`),
        merged over its `dat.base`, with a `dat` mapping."""
        if spec is None:
            spec = {}
        if isinstance(spec, str):
            spec = self.ns.load(spec)
        if not isinstance(spec, dict):
            raise TypeError(f"Dat.create: spec must be a dict or a dotted name, not {spec!r}")
        spec = self.ns._merge_bases(deepcopy(spec))
        if not isinstance(spec.setdefault("dat", {}), dict):
            raise TypeError(f"Dat.create: spec['dat'] is a mapping, got {spec['dat']!r}")
        return spec

    def load(
        self,
        name: Union[str, Path],
        *,
        cache_after_load: bool = True,
        verify: Optional[bool] = None,
    ) -> Any:
        """What `name` names: a dat, as the class its `dat.kind` names, or an artifact, handed to its recorded type.

        An artifact with no recorded type is handed back as its payload's `Path`. `name` is a dat's name or path, an
        artifact's name, or the `sha256:` URN (`sha256:<hex>`) of either; a name held by both a dat and an artifact is
        `ValueError`.

        A dat is searched as an absolute path, in `ns`'s mounts, then in each dat folder; not found is `KeyError`, a
        folder with no spec `FileNotFoundError`. Dats are cached by path, weakly, so a second load returns the same
        object while it lives; `cache_after_load` applies to dats only, and `cache_after_load=False` skips the cache.
        Inside a `recording`, the load lands in that dat's `dat.dependencies`. `verify` (default: the manager's)
        re-hashes what is handed back and raises `ValueError` naming both hashes when it differs from the stored one;
        a dat with no hash has nothing to check.
        """
        kind, where = self._locate(name)
        if kind == "art":
            return self._load_artifact(str(name), where, verify)
        dat = self._load(where, cache_after_load=cache_after_load)
        self._check_urn(name, dat)
        self._check(dat, verify)
        _record_dat(dat)
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

    def load_path(self, name: Union[str, Path], *, verify: Optional[bool] = None) -> Path:
        """Where `load(name)` would find its object -- a dat's folder, or an artifact's payload -- as a `Path`.

        With no type called. Recorded, and verified, exactly as `load` does.
        """
        kind, where = self._locate(name)
        if kind == "art":
            return self._artifact_payload(str(name), where, verify)[0]
        dat = self._load(where)
        self._check_urn(name, dat)
        self._check(dat, verify)
        _record_dat(dat)
        return Path(dat.get_path())

    def exists(self, name: Union[str, Path]) -> bool:
        """`True` when `name` (a dat's name, an artifact's, or a URN) names something stored.

        A dat counts when its folder holds a spec file.
        """
        try:
            kind, where = self._locate(name)
        except (KeyError, FileNotFoundError):
            return False
        if kind == "art":
            return True
        path = self._resolve_path(where)
        return os.path.exists(os.path.join(path, SPEC_JSON)) or os.path.exists(
            os.path.join(path, SPEC_YAML))

    # -- the store: names, URNs, the index --------------------------------------

    def _locate(self, name: Union[str, Path]) -> Tuple[str, str]:
        """`("art", folder)` for an artifact, `("dat", name_or_path)` for a dat.
        A URN not in the index is looked for in the dat folders, as `reindex()` does
        (each saved dat's stored hash, nothing re-hashed); the first dat holding it
        is keyed to it and found, so deleting one of two same-hash dats never strands
        the other (1467 Q4 (A)). `KeyError` when none does; a name both hold is
        `ValueError`."""
        text = str(name)
        if text.startswith(URN_PREFIX):
            entry = self._read_index().get(text) or self._rekey_dat(text)
            if entry is None:
                raise KeyError(f"load: {text} is not in the index {self._index_file}, and no saved dat "
                               "holds it")
            if "art" in entry:
                return "art", os.path.join(self._require_art_folder(text), entry["art"])
            return "dat", entry["dat"]
        folder = None if os.path.isabs(text) else self._artifact_folder(text)
        if folder is not None:
            if self._dat_exists(text):
                raise ValueError(f"{text!r} names both a dat and an artifact; "
                                 "rename one -- they share one namespace")
            return "art", folder
        return "dat", text

    def _require_art_folder(self, name: str) -> str:
        if self._art_folder is None:
            raise RuntimeError(f"{name!r}: this manager has no art_folder; build it with "
                               "DatManager(..., art_folder=...) or set art_folder: in "
                               ".datconfig.yaml")
        return self._art_folder

    def _artifact_folder(self, name: Union[str, Path]) -> Optional[str]:
        """The folder of the artifact `name` (a name or a URN) holds, else None:
        the index first, then the folder the name is."""
        if self._art_folder is None:
            return None
        key = str(name)
        entry = self._read_index().get(key)
        if entry is not None:
            return os.path.join(self._art_folder, entry["art"]) if "art" in entry else None
        if key.startswith(URN_PREFIX) or not self._valid_name(key):
            return None
        folder = os.path.normpath(os.path.join(self._art_folder, key))
        return folder if os.path.exists(os.path.join(folder, ART_FILE)) else None

    @staticmethod
    def _valid_name(name: str) -> bool:
        parts = name.split("/")
        return (bool(name) and not name.startswith(URN_PREFIX) and not os.path.isabs(name)
                and all(p not in ("", ".", "..") for p in parts))

    def _dat_exists(self, name: str) -> bool:
        path = self._resolve_path(name)
        return os.path.exists(os.path.join(path, SPEC_YAML)) or os.path.exists(
            os.path.join(path, SPEC_JSON))

    def _read_index(self) -> Dict[str, Dict[str, str]]:
        """Every key of the index -- names and `sha256:` URNs -- to its entry,
        `{art: <folder under the artifact folder>}` or `{dat: <name>}`.  A
        subclass that keeps the index elsewhere overrides this and
        `_index_update`."""
        try:
            st = os.stat(self._index_file)
        except FileNotFoundError:
            return {}
        stamp = (st.st_mtime_ns, st.st_size)
        if self._index_cache is None or self._index_cache[0] != stamp:
            data = json.loads(Path(self._index_file).read_text() or "{}")
            self._index_cache = (stamp, dict(data.get("entries") or {}))
        return self._index_cache[1]

    @contextlib.contextmanager
    def _index_update(self) -> Iterator[Dict[str, Dict[str, str]]]:
        """The index, locked against other processes, to change in place; written
        back through a temporary file and a rename, so a crash never leaves it
        torn."""
        import fcntl                            # POSIX; only a store write needs it
        folder = os.path.dirname(self._index_file)
        os.makedirs(folder, exist_ok=True)
        lock_path = os.path.splitext(self._index_file)[0] + ".lock"
        with open(lock_path, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._index_cache = None
            entries = dict(self._read_index())
            yield entries
            tmp = f"{self._index_file}.{os.getpid()}.tmp"
            Path(tmp).write_text(json.dumps(
                {"dvc_dat_index": 1, "entries": entries}, indent=1, sort_keys=True))
            os.replace(tmp, self._index_file)
            self._index_cache = None

    def _index_dat(self, dat: "Dat", old: Optional[str]) -> None:
        """Key `dat`'s current hash to it, dropping the hash it replaced."""
        name, sha256 = dat.get_path_name(), dat._sha256()
        with self._index_update() as index:
            if old and index.get(old) == {"dat": name}:
                del index[old]
            if sha256:
                index[sha256] = {"dat": name}

    def _index_forget(self, name: str) -> None:
        """Drop every key that leads to the dat `name`."""
        if not os.path.exists(self._index_file):
            return
        with self._index_update() as index:
            for key in [k for k, v in index.items() if v == {"dat": name}]:
                del index[key]

    def reindex(self) -> int:
        """Rebuild the index -- `_index_.json` by default -- from the folders.

        Every artifact's names and URN come from its `_art_.yaml`, every saved dat's URN from its `_result_.yaml`.
        Returns the number of keys.
        """
        entries: Dict[str, Dict[str, str]] = {}
        if self._art_folder is not None and os.path.isdir(self._art_folder):
            for root, dirs, files in os.walk(self._art_folder):
                if ART_FILE not in files:
                    continue
                dirs[:] = []                    # a payload folder holds no artifacts
                rel = os.path.relpath(root, self._art_folder)
                sidecar = yaml.safe_load(Path(root, ART_FILE).read_text()) or {}
                if sidecar.get("sha256"):
                    entries.setdefault(sidecar["sha256"], {"art": rel})
                for name in _sidecar_names(sidecar):
                    entries[name] = {"art": rel}
        for root, sha256 in self._saved_dats():
            entries.setdefault(sha256, {"dat": self._get_path_name(root)})
        with self._index_update() as index:
            index.clear()
            index.update(entries)
        return len(entries)

    def _saved_dats(self) -> Iterator[Tuple[str, str]]:
        """`(folder, sha256)` of every saved dat under the dat folders: a folder holding a
        spec and a `_result_.yaml` that records its hash, read from that yaml, never re-hashed."""
        for folder in self._dat_folders:
            for root, _, files in os.walk(folder):
                if RESULT_YAML in files and (SPEC_YAML in files or SPEC_JSON in files):
                    result = yaml.safe_load(Path(root, RESULT_YAML).read_text()) or {}
                    if (sha256 := Dat.get(result, DAT_SHA256, None)):
                        yield root, sha256

    def _rekey_dat(self, urn: str) -> Optional[Dict[str, str]]:
        """The index entry of the first saved dat whose stored hash is `urn`, written to the
        index, else None: the miss path of `_locate`."""
        root = next((r for r, h in self._saved_dats() if h == urn), None)
        if root is None:
            return None
        entry = {"dat": self._get_path_name(root)}
        with self._index_update() as index:
            index[urn] = entry
        return entry

    def _check_urn(self, name: Union[str, Path], dat: "Dat") -> None:
        """A dat loaded by URN must still hash to it."""
        if str(name).startswith(URN_PREFIX) and dat._sha256() != str(name):
            raise ValueError(f"load: the index keys {name} to {dat.get_path_name()!r}, "
                             f"which was saved again as {dat._sha256()}; reindex()")

    # -- artifacts -------------------------------------------------------------

    def save_artifact(self, source: Union[str, Path], *,
                      type: Union[None, str, Callable] = None,
                      name: Optional[str] = None, link: bool = False) -> str:
        """Store the file or folder `source` as an artifact and return its URN, `sha256:<hex>` (`"sha256:<hex>"`).

        `type` is what `load` hands the payload's path to: a class or callable, recorded as its dotted name, or that
        name as a string -- anything `ns.load` resolves, a mounted value included; one that does not load back by its
        name is `TypeError`. With no type, `load` returns the path. `name` is a path-like name of your choosing, held
        once and never overwritten; with none, the artifact answers to its URN only. Bytes already stored are not
        stored again: the new name becomes a second key to them. A file lands as `<art_folder>/<name>/<basename>`, a
        folder's contents as `<art_folder>/<name>/` (`sha256/<hex>/` with no name), with the sidecar `_art_.yaml`
        beside them. `link` hard-links the payload instead of copying it (same filesystem only). Inside a `recording`
        the artifact lands in that dat's `dat.dependencies`.

        Errors: no artifact folder `RuntimeError`, a malformed name `ValueError`, a missing source
        `FileNotFoundError`, a name already held by a dat or an artifact `FileExistsError`. See [Artifacts and the
        index][artifacts-and-the-index].
        """
        art = self._require_art_folder(str(name or source))
        type_name = self._type_name(type)
        key = None if name is None else str(name)
        if key is not None and not self._valid_name(key):
            raise ValueError(f"save_artifact: an artifact name is a relative path of plain "
                             f"segments, got {name!r}")
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(f"save_artifact: no file or folder at {str(source)!r}")
        payload = "." if source.is_dir() else source.name
        sha256 = URN_PREFIX + (_hash_payload(str(source), ".") if source.is_dir()
                               else _sha256_file(str(source)))
        size = _payload_size(source)
        if key is not None and self._dat_exists(key):
            raise FileExistsError(f"save_artifact: {key!r} is a dat's name; dats and artifacts "
                                  "share one namespace")
        with self._index_update() as index:
            if key is not None:
                self._check_name_free(key, index)
            held = index.get(sha256)
            if held is not None and "art" in held:
                self._add_name(held["art"], sha256, size, type_name, key, index)
            else:
                rel = key if key is not None else f"{_URN_FOLDER}/{sha256[len(URN_PREFIX):]}"
                folder = os.path.join(art, rel)
                if source.is_dir():
                    shutil.copytree(source, folder,
                                    copy_function=os.link if link else shutil.copy2)
                else:
                    os.makedirs(folder)
                    (os.link if link else shutil.copy2)(source, os.path.join(folder, source.name))
                sidecar = {"type": type_name, "names": [key] if key is not None else [],
                           "payload": payload, "sha256": sha256, "size": size,
                           "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                Path(folder, ART_FILE).write_text(yaml.safe_dump(sidecar, sort_keys=False))
                index[sha256] = {"art": rel}
                if key is not None:
                    index[key] = {"art": rel}
        _record(key if key is not None else sha256, sha256)
        return sha256

    def load_artifact(self, name: Union[str, Path], *,
                      verify: Optional[bool] = None) -> Any:
        """The artifact `name` (a name, an `art:` name or a URN) names, handed to the type recorded at its save.

        With none, its payload's `Path`. A name that is a dat's is `KeyError`; `load` takes either. A type that no
        longer resolves is `ImportError`.
        """
        kind, where = self._locate(name)
        if kind != "art":
            raise KeyError(f"load_artifact: no artifact {str(name)!r}"
                           + ("; it is a dat -- load it with load()"
                              if self._dat_exists(where) else ""))
        return self._load_artifact(str(name), where, verify)

    def _check_name_free(self, key: str, index: Dict[str, Dict[str, str]]) -> None:
        """A name is held once: not by another artifact, not as a folder of
        other artifacts, not inside one."""
        art = self._art_folder
        folder = os.path.normpath(os.path.join(art, key))
        if key in index or os.path.exists(folder):
            raise FileExistsError(f"save_artifact: artifact {key!r} exists")
        parts = key.split("/")
        for cut in range(1, len(parts)):
            if os.path.exists(os.path.join(art, *parts[:cut], ART_FILE)):
                raise ValueError(f"save_artifact: {key!r} lies inside the artifact "
                                 f"{'/'.join(parts[:cut])!r}")

    def _add_name(self, rel: str, sha256: str, size: int, type_name: Optional[str],
                  key: Optional[str], index: Dict[str, Dict[str, str]]) -> None:
        """Bytes already stored at `rel`: check they are the same, and give them
        the name `key` too; nothing is copied."""
        sidecar_path = Path(self._art_folder, rel, ART_FILE)
        sidecar = yaml.safe_load(sidecar_path.read_text()) or {}
        if sidecar.get("size") is not None and sidecar["size"] != size:
            raise ValueError(f"save_artifact: {sha256} is stored at {rel!r} with "
                             f"{sidecar['size']} bytes, and this source has {size}")
        if type_name is not None and sidecar.get("type") != type_name:
            raise ValueError(f"save_artifact: these bytes are stored at {rel!r} with type "
                             f"{sidecar.get('type')!r}, not {type_name!r}")
        if key is not None:
            sidecar["names"] = _sidecar_names(sidecar) + [key]
            sidecar_path.write_text(yaml.safe_dump(sidecar, sort_keys=False))
            index[key] = {"art": rel}

    def _type_name(self, type: Union[None, str, Callable]) -> Optional[str]:
        """The dotted name `type` is recorded as, checked to resolve back to it."""
        if type is None:
            return None
        if isinstance(type, str):
            try:
                obj = self.ns.load(type)
            except (ImportError, AttributeError, KeyError) as e:
                raise ValueError(f"save_artifact: type {type!r} does not resolve through "
                                 f"ns.load: {e}") from None
            if not callable(obj):
                raise TypeError(f"save_artifact: type {type!r} is {obj!r}, not callable")
            return type
        if not callable(type):
            raise TypeError(f"save_artifact: type is a class, a callable or its dotted name, "
                            f"got {type!r}")
        hint = ("; mount it -- Dat.ns.mount(value=..., at='some.name') -- and pass "
                "type='some.name'")
        try:
            dotted = self.ns.name_of(type)
        except ValueError:
            raise TypeError(f"save_artifact: {type!r} has no importable dotted name{hint}") from None
        if self.ns.load(dotted, default=None) is not type:
            raise TypeError(f"save_artifact: {type!r} does not load back as {dotted!r}{hint}")
        return dotted

    def _load_artifact(self, name: str, folder: str, verify: Optional[bool]) -> Any:
        path, sidecar = self._artifact_payload(name, folder, verify)
        if not sidecar.get("type"):
            return path
        try:
            factory = self.ns.load(sidecar["type"])
        except (ImportError, AttributeError, KeyError) as e:
            raise ImportError(f"load: artifact {name!r} has type {sidecar['type']!r}, "
                              f"which does not resolve through ns.load: {e}") from None
        return factory(path)

    def _artifact_payload(self, name: str, folder: str,
                          verify: Optional[bool]) -> Tuple[Path, Dict[str, Any]]:
        """An artifact's payload path and sidecar, checked, verified and recorded."""
        sidecar_path = os.path.join(folder, ART_FILE)
        if not os.path.exists(sidecar_path):
            raise FileNotFoundError(f"load: no artifact {name!r} (no {sidecar_path}); "
                                    "reindex() rebuilds the index from the folders")
        sidecar = yaml.safe_load(Path(sidecar_path).read_text()) or {}
        payload = sidecar.get("payload", ".")
        if (self._verify if verify is None else verify) and sidecar.get("sha256"):
            actual = "sha256:" + _hash_payload(folder, payload)
            if actual != sidecar["sha256"]:
                raise ValueError(f"load: artifact {name!r} hashes to {actual}, "
                                 f"not its stored {sidecar['sha256']}")
        _record(str(name), sidecar.get("sha256"))
        return (Path(folder) if payload == "." else Path(folder, payload)), sidecar

    def _check(self, dat: "Dat", verify: Optional[bool]) -> None:
        """The verifying load of a dat: its folder against its stored hash."""
        if not (self._verify if verify is None else verify):
            return
        result_path = Path(dat.get_path(), RESULT_YAML)
        on_disk = (yaml.safe_load(result_path.read_text()) or {}) if result_path.exists() else {}
        stored = Dat.get(on_disk, DAT_SHA256, None)
        if stored is not None and (actual := _hash_dat(dat.get_path(), on_disk)) != stored:
            raise ValueError(f"load: dat {dat.get_path_name()!r} hashes to {actual}, "
                             f"not its stored {stored}")

    def standing(self, name: Union[str, Path, "Dat"]) -> Optional[str]:
        """How far `name` can be relied on, read from its files without building it.

        `rolling`, `open`, `sealed` or `referenceable`; `None` when nothing is stored under it. An artifact is
        `referenceable`; a `Dat` instance answers from its last write. See [Standing][standing].
        """
        if isinstance(name, Dat):
            return name._standing()
        try:
            kind, where = self._locate(name)
        except (KeyError, FileNotFoundError):
            return None
        if kind == "art":
            return REFERENCEABLE
        path = self._resolve_path(where)
        if Path(path, SPEC_YAML).exists():
            spec = yaml.safe_load(Path(path, SPEC_YAML).read_text()) or {}
        elif Path(path, SPEC_JSON).exists():
            spec = json.loads(Path(path, SPEC_JSON).read_text()) or {}
        else:
            return None
        result_path = Path(path, RESULT_YAML)
        result = (yaml.safe_load(result_path.read_text()) or {}) if result_path.exists() else {}
        return _standing_of(spec, result)

    # -- recording -------------------------------------------------------------

    @contextlib.contextmanager
    def recording(self, dat: "Dat") -> Iterator[None]:
        """Every `load`, `load_path` and `save_artifact` inside the block lands in `dat`'s `dat.dependencies`.

        Name to hash. Blocks nest: when an inner block ends, its dat becomes one entry of the outer one. A run
        (`_execute`) calls its function inside one; a builder gathering a dat's inputs outside a run uses it directly.
        See [Dependency capture][dependency-capture].
        """
        with self._capture(dat) as outer:
            yield
        if outer is not None:
            _record_dat(dat)

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
        """Add `name -> sha256` to the recording dat's `dat.dependencies`, for what a run used without a `load`.

        An input that reached the run around the manager -- a URL, a file read directly. `RuntimeError` when nothing
        is recording.
        """
        if not _recording.get():
            raise RuntimeError("record_dependency: no dat is recording")
        _record(name, sha256)

    @staticmethod
    def code_of(fn: Callable) -> Optional[Dict[str, Any]]:
        """`{branch, commit, dirty}` of the git checkout holding `fn`'s source, as a run records it in `dat.code`.

        `branch` is `None` on a detached HEAD; `dirty` counts tracked files outside the paths the repo's
        `.gitattributes` marks `dat-noncode` (`CODE_PATHSPEC`). `None` when the source is outside a checkout.
        """
        return _code_of(fn)

    def roots(self, deps: Dict[str, Any]) -> Dict[str, Any]:
        """`deps` less every entry that another entry's dat lists among its own dependencies -- the trim a seal applies.
        """
        below: set = set()
        for name in deps:
            if name == DEP_MANUAL or self._artifact_folder(name) is not None:
                continue
            try:
                dat = self._load(name)
            except (KeyError, FileNotFoundError):
                continue
            below.update(Dat.get(dat.get_results(), DAT_DEPENDENCIES, None) or {})
        return {k: v for k, v in deps.items() if k not in below}

    def _dep_standing(self, name: str, value: Any) -> str:
        """An input's standing: an artifact or a `$MANUAL` mark referenceable,
        an entry recorded `unsealed` open, a dat its own, anything else
        recorded by hand referenceable when it carries a hash."""
        if name == DEP_MANUAL:
            return REFERENCEABLE
        if value == DEP_UNSEALED:
            return OPEN
        if self._artifact_folder(name) is not None:
            return REFERENCEABLE
        try:
            dat = self._load(name)
        except (KeyError, FileNotFoundError):
            return REFERENCEABLE if value is not None else SEALED
        return dat._standing()

    def _earned(self, dat: "Dat", deps: Dict[str, Any]) -> Tuple[str, str]:
        """The standing a seal earns, and why it is no higher: the least of its
        inputs' (rolling counts as sealed), capped at sealed by a run's code
        that is dirty or outside a checkout.  The run is `dat.run`; a dat with
        none has no run record to cap it."""
        earned, why = REFERENCEABLE, ""

        def cap(to: str, reason: str) -> None:
            nonlocal earned, why
            if _RANK[to] < _RANK[earned]:
                earned, why = to, reason
        run = dat.run
        record = run.get_results() if run is not None else {}
        if Dat.get(record, DAT_RUN_AT, None) is not None:
            code = Dat.get(record, DAT_CODE, None)
            if code is None:
                cap(SEALED, "its code is outside a git checkout")
            elif code.get("dirty"):
                cap(SEALED, "its code is dirty")
        for name, value in deps.items():
            standing = self._dep_standing(name, value)
            cap(SEALED if standing == ROLLING else standing,
                f"its input {name!r} is {standing}")
        return earned, why

    def _get_path_name(self, path: Union[str, Path]) -> str:
        path = str(path)
        real = os.path.realpath(path)
        for folder in self._dat_folders:
            if real != folder and _within(real, folder):
                return os.path.relpath(real, folder)
        return path

    def run(self, target: Any, /, *args: Any, **kwargs: Any) -> Any:
        """Create a dat and run it, in this world: the one way to run a dat outside a ledger, fixed (2.35, DAT 1049).

        `target` is first loaded through `ns` when it is a name. A **spec** (a dict, or a dotted name that loads to
        one) is a template: `args` replace `dat.args`, `kwargs` merge into `dat.kwargs` (see `create`, which this is
        followed by the run); the new dat runs with no call-site arguments, and `dat.target_exists: use` returns the
        existing one unrun. A **callable** (or a dotted name that loads to one) is called with `args`/`kwargs`.
        Anything else is `TypeError`. A keyword is data: a template reads it by its node, `${dat.kwargs.game}`.

        A dat's run calls `fn(dat, *dat.args, **dat.kwargs)` with `fn` the object `dat.do` names, loaded through this
        world's `ns`, inside `recording(dat)`, with a fresh `run/` sub-dat holding the run's record and `run/work/` as
        the working directory, and records the run in `dat.run` (see `_execute`); the return value is `fn`'s, or the
        dat when the spec has no `dat.do` -- as does `dat.target_exists: use` finding the dat already there. Saves
        nothing by itself; a `dat.save()` inside `fn` is answered with the seal when `fn` returns. A `Dat` is
        `TypeError`: a dat is run once, by the call that makes it; another run of its recipe is `run(dat.get_spec(),
        ...)` (`run(dat.get_spec(), **kwargs)`), a new dat (SVP 1508). A sealed dat is `RuntimeError`, a non-callable
        `dat.do` `TypeError`, and a spec demanding `referenceable` is `RuntimeError` when the code is dirty or outside
        a git checkout. Every error is re-raised as `Exception("In <target>")` chained from the original. Every run in
        the world -- nested ones and a ledger's dat runs included -- is recorded this way; `dat.run` is the `run/`
        sub-dat. Names load through this world's `ns`, so in a ledger project they are the ledger's. Fixed: a project
        needing other run machinery subclasses the manager, not `Dat`. See [The spec is the
        record][the-spec-is-the-record] and [The run sub-dat][the-run-sub-dat].
        """
        ns = self.ns
        obj = ns.load(target) if isinstance(target, str) else target
        try:
            if isinstance(obj, Dat):
                raise TypeError(f"run: {obj!r} is a dat, made and run once; run its recipe again as a new dat "
                                "with Dat.manager.run(dat.get_spec(), **kwargs) (a stored spec is expanded "
                                "already: one holding a literal `${` is quoted first, Dat.ns.quote_spec, its "
                                "dat.name put back)")
            if callable(obj):
                return obj(*args, **kwargs)
            if not isinstance(obj, dict):
                raise TypeError(f"run: cannot run {obj!r}; expected a callable or a spec")
            spec = ns._fork_spec(obj, args, kwargs)
            dat, skip_execution = ns._dat_from_template(spec, manager=self)
            if skip_execution:
                return dat
            return self._execute(dat)
        except Exception as e:
            raise Exception(f"In {target!r}") from e

    def _execute(self, dat: "Dat") -> Any:
        """Run `dat` as its spec says, and record the run in `dat.run`.

        Calls `fn(dat, *dat.args, **dat.kwargs)` with `fn` the object `dat.do`
        names, loaded through this world's `ns`, inside `recording(dat)`.  The
        run is a sub-dat, `run/` inside the dat, made fresh here: its results
        take `dat.run_at`, `dat.host`, `dat.pid`, `dat.code` (the branch,
        commit and dirty flag of the git checkout holding `fn`'s source; nothing
        outside a checkout) and, on a ledger, `dat.run_rev` before `fn` starts,
        `dat.run_time` when it returns,
        and `dat.content`, the hash the dat sealed, after the seal.  `fn` runs
        with `run/work/` as the working directory, so what it writes without
        naming a place lands in scratch, outside the dat's hash.  The dat's own
        results take `dat.dependencies` (every dat and artifact the run loaded,
        name to hash).  It saves nothing by itself: a `dat.save()` inside `fn`
        writes a checkpoint and asks for the seal, which comes when `fn`
        returns, with the whole record.  A sealed dat is refused (a rolling one
        runs again, and its `run/` is replaced).  A spec saying `dat.standing:
        referenceable` demands it: a load of an input that is not referenceable
        raises there, and so does code that is dirty or outside a checkout.
        Every run in this world comes here -- `run(...)` and the `run(...)` calls
        nested inside a running function alike -- so a subclass that wraps this
        wraps every run.  Returns `fn`'s value, or `dat` when there is no
        `dat.do`.
        """
        spec = dat.get_spec()
        fn = Dat.get(spec, DAT_DO, None)
        if fn is None:
            return dat
        if isinstance(fn, str):
            fn = self.ns.load(fn)
        from .ledger.fn import Fn
        if isinstance(fn, Fn):                  # a ledger project's name for a function (DAT 1046)
            if fn.kind != "dat":
                raise TypeError(f"{DAT_DO} in {dat!r} is the ledger function {fn.name}; "
                                f"rev.run({fn.name!r}, ...) runs it")
            fn = fn._function()                 # a plain run: here, nothing memoised
        if not callable(fn):
            raise TypeError(f"{DAT_DO} in {dat!r} is {fn!r}, not callable")
        if dat._standing() in _FROZEN:
            raise RuntimeError(f"run: {dat!r} is sealed; run its recipe as a new dat with "
                               "Dat.manager.run(dat.get_spec(), ...), or copy it")
        code = _code_of(fn)
        if dat._demands_referenceable() and (code is None or code.get("dirty")):
            raise RuntimeError(f"run: {dat!r} demands dat.standing: referenceable, and "
                               f"the code of {fn!r} is "
                               f"{'dirty' if code else 'outside a git checkout'}")
        args = list(Dat.get(spec, DAT_ARGS, None) or [])
        kwargs = dict(Dat.get(spec, DAT_KWARGS, None) or {})
        Dat.set(dat.get_results(), DAT_DEPENDENCIES, {})    # a run with no loads says so
        run = self._start_run(dat, code)
        dat._running, dat._save_asked = True, False
        before = time.time()
        cwd = os.getcwd()
        os.chdir(os.path.join(run.get_path(), WORK_FOLDER))
        try:
            with self._capture(dat) as outer:
                result = fn(dat, *args, **kwargs)
        finally:
            os.chdir(cwd)
            dat._running = False
            if (at := dat.__dict__.get("_at")) is not None:
                dat.__dict__["_at"] = at._plain()   # the run is over: nothing records any more
        time_ms = (time.time() - before) * 1000
        exec_time = (time.strftime("%H:%M:%S", time.gmtime(time_ms // 1000))
                     + ".{:03d}".format(int(time_ms % 1000)))
        Dat.set(run.get_results(), DAT_RUN_TIME, exec_time)
        _write_run(run)
        if dat._save_asked:
            dat._seal(manual=False)
        if outer is not None:           # recorded by its final hash, if it has one
            _record_dat(dat)
        return result

    def _start_run(self, dat: "Dat", code: Optional[Dict[str, Any]]) -> "Dat":
        """A fresh `run/` sub-dat inside `dat` -- the one before it, if any,
        removed -- with its start facts written, and `dat.run` pointing at it."""
        path = os.path.join(dat.get_path(), RUN_FOLDER)
        if os.path.exists(path):
            shutil.rmtree(path)
        os.makedirs(os.path.join(path, WORK_FOLDER))
        spec = {"dat": {"kind": _kind_name(Dat)}}
        Path(path, SPEC_YAML).write_text(yaml.dump(spec, Dumper=_SpecDumper, sort_keys=True))
        run = Dat(path=path, spec=spec)
        run._manager = self
        Dat.set(run.get_results(), DAT_RUN_AT, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        Dat.set(run.get_results(), DAT_HOST, socket.gethostname())
        Dat.set(run.get_results(), DAT_PID, os.getpid())
        if code is not None:
            Dat.set(run.get_results(), DAT_CODE, code)
        from .ledger.trace import current_run
        frame = current_run()
        dat.__dict__.pop("_at", None)
        if frame is not None:                   # a run on a ledger: `dat.at` is its recording Rev (SVP 1521)
            Dat.set(run.get_results(), DAT_RUN_REV, frame.at)
            dat.__dict__["_at"] = frame.rev
        _write_run(run)
        dat._run_dat = run
        return run

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

    def _place(self, path_spec: str, name_at: Callable[[int], str], *, target_exists: str = "error",
               wipe: bool = True) -> Tuple[str, bool, int]:
        """Settle where a dat goes, under the dat folder: `(path, skip_execution, count)`. `name_at(count)` is the
        path template resolved at that count. `skip_execution` is True only for `target_exists: use` on an existing
        folder; `overwrite` deletes the folder (`wipe=False`: leaves it for the caller to remove, `create` once its
        spec is made); a `${unique:}` in the template counts up (`increment` appended one) until no folder is
        there, and `count` is where it stopped, so the spec resolves at the very same count."""
        counts = has_unique(path_spec)
        count = 1
        while True:
            expanded = name_at(count)
            if not isinstance(expanded, str) or not expanded:
                raise TypeError(f"dat.name {path_spec!r} resolved to {expanded!r}, not a path")
            expanded_path = os.path.join(self._dat_folders[0], expanded)
            if not os.path.exists(expanded_path):
                return expanded_path, False, count
            elif target_exists == "use":
                return expanded_path, True, count
            elif target_exists == "overwrite":
                self._refuse_wipe(expanded_path, path_spec)
                if wipe:
                    shutil.rmtree(expanded_path)
                return expanded_path, False, count
            elif counts:
                count += 1
            else:
                raise FileExistsError(f"DAT: Create failed, dir {expanded_path!r} exists")

    def _refuse_delete_on_a_ledger(self, what: str) -> None:
        """`TypeError` on a ledger project (its `ns` a `LedgerNamespace`, the test that refuses
        `Dat.ns.mount`): a ledger only appends rows, so no delete can reclaim saved bytes (1467 Q15 (A))."""
        from .ledger.namespace import LedgerNamespace

        if isinstance(self.ns, LedgerNamespace):
            raise TypeError(f"{what}, and a ledger never deletes. To stop a dat being in the current view, "
                            "retract its rows in a transaction (`del t[s]`), which appends remove rows and "
                            "keeps every earlier revision. The folder is a local copy, and the ledger does "
                            "not reclaim its bytes.")

    def _refuse_wipe(self, path: str, template: str) -> None:
        """`overwrite` never deletes a folder holding the working directory, a dat folder, the
        artifact folder or the config's folder: a name such as `.` or `..` expands to one. Nor
        one outside every dat folder and the artifact folder: an absolute name (or a `..`) may
        place a dat anywhere, but overwrite deletes only inside the store (1467 Q13 (A))."""
        real = os.path.realpath(path)
        for keep in (os.getcwd(), *self._dat_folders, self._art_folder, self._config_dir):
            if keep and _within(os.path.realpath(keep), real):
                raise ValueError(f"dat.target_exists overwrite: {template!r} names {real!r}, which "
                                 f"holds {keep!r}; refusing to delete it")
        if not any(f and _within(real, os.path.realpath(f)) for f in (*self._dat_folders, self._art_folder)):
            raise ValueError(f"dat.target_exists overwrite: {template!r} names {real!r}, outside the dat "
                             "folders and the art folder; refusing to delete it")

    def _resolve_path(self, name: Union[str, Path]) -> str:
        name = str(name)
        if os.path.isabs(name):
            return name
        if (mount_path := self.ns._resolve_dat_folder(name)) is not None:
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
    `DatManager.load_dat_config()`.  `Run.manager is Dat.manager`.  And `ns`,
    the default world's namespace."""

    @property
    def ns(cls) -> Any:
        """The default world's namespace (not callable: `Dat.manager.run` runs): a
        forwarder to `Dat.manager.ns`, whichever manager that is when it is used, so
        `ns = Dat.ns` binds a shortcut that follows a later reassignment."""
        from .do import ns
        return ns

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
            value.ns._manager = value       # its namespace answers to it again
        _default_manager = value


class Dat(Value, metaclass=_DatMeta):
    """A folder of data described by its `_spec_.yaml`; on a ledger, a value.

    The spec is the complete recipe: `dat.do` names the function, `dat.args` and
    `dat.kwargs` its arguments, `dat.name` the path template, `dat.base` what it
    inherited from.  Every `{}` reference in it was expanded once, when the dat was
    created, and `get_spec()` returns it as written.  `get_results()` is the
    mutable `_result_.yaml`.

    A dat is a ledger `Value` (DAT 1038): its bytes are its folder's content
    manifest, `{"files": {relpath: sha256}}`, the files themselves going to the
    art store, so `dat.seal(t, name=...)` saves the folder of a saved dat and
    `rev.load(name)` rebuilds it, as a view in the ledger's data folder.  Its
    `preds` default to the scalar `dat.kwargs` of its spec and the scalar
    top-level entries of its results (`dat:` aside), read from the folder;
    `@ledger_class(preds=...)` on a subclass adds names.  `Dat(path)` is the dat
    already in the folder `path`, its spec and results read from there (a
    folder with no spec is a plain folder value).

    Subclasses override `validate_spec` to check or coerce a spec on create and load
    (a schema library inside it is the subclass's choice and dependency).
    """

    ns: Any
    """The forwarder ``dvc_dat.do.ns``: every attribute goes to ``Dat.manager.ns``.

    Whichever manager that is at the moment of use. Not callable -- running is ``Dat.manager.run`` (2.35) -- so ``ns =
    Dat.ns`` binds a shortcut that follows a later reassignment. It is defined on the metaclass, so ``Dat.ns`` works
    and ``some_dat.ns`` is ``AttributeError``.
    """

    @property
    def manager(self) -> DatManager:
        """``Dat.manager``: the manager that loaded this dat, else the default; on the class, the default world itself.

        A plain assignable attribute, built on first read by ``DatManager.load_dat_config()``, shared by every
        subclass (see ``_DatMeta``), and replaced by assigning a ``DatManager`` -- anything else is ``TypeError``;
        assigning ``None`` clears it, so the next read builds it again. See [The manager is the
        world][the-manager-is-the-world].
        """
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
        *,
        name: Optional[str] = None,
    ) -> None:
        """The dat already in the folder ``path``, its spec and results read from ``_spec_.yaml`` and ``_result_.yaml``.

        A value whose bytes are the folder's content manifest; each file reads as ``{}`` when absent. ``name`` is the
        name a save gives it. ``Dat.create(spec=...)`` and ``Dat.load(name)`` make one through the dat manager ([DAT
        Class API](https://github.com/oblinger/dvc-dat/blob/main/doc/DAT%20Design/DAT%20API/DAT%20Class%20API.md)).
        """
        if not isinstance(path, (str, Path)):
            raise TypeError(
                f"{type(self).__name__}(path): a dat is the folder at a path, not {path!r}; "
                f"Dat.create(spec=...) makes one on disk, Dat.load(name) finds one")
        self._path = os.path.abspath(str(path))
        if spec is None:
            spec, result = _read_folder(self._path)
        self._spec = spec
        self._result = result or {}
        self._manager = None
        self._running = False           # inside its own _execute
        self._save_asked = False        # save() was called while running
        self._run_dat: Optional["Dat"] = None   # the run sub-dat, once known
        self._written = _standing_of(self._spec, self._result)   # as last written
        if name is not None:
            self.name = name
            """The name a save gives it."""

    @classmethod
    def _from_folder(cls: Type[DatType], path: Union[str, Path]) -> DatType:
        """The dat in `path` as this class (a ledger load): `cls(path)`, the spec and results read from
        the folder, as `DatManager` calls a kind with `(path, spec, result)`."""
        return cls(path)

    @property
    def path(self) -> Path:
        """The dat's folder, ``get_path()`` as a ``Path``.

        After a save it is the stored copy under ``art/dats/<16 hex>/``, or ``art/dats/<name>/`` when named; after a
        load by an alias, ``art/dats/<alias>/`` -- its view in the ledger's data folder. Those files are hardlinks
        into the art store where the filesystem allows: write a new folder and seal it, never edit one in place.
        """
        return Path(self._path)

    @path.setter
    def path(self, value: Union[str, Path]) -> None:
        self._path = os.path.abspath(os.fspath(value))

    def _move_to(self, path: Path) -> None:
        """Point this object at the folder `path`, which holds the same files (a view)."""
        if self._manager is not None:
            self._manager._dat_cache.pop(self._path, None)
        self.path = path
        self._run_dat = None

    def __getstate__(self) -> Dict[str, Any]:
        """Pickled without its world or its run sub-dat (both are found again from the folder)."""
        state = dict(self.__dict__)
        state["_manager"] = None
        state["_run_dat"] = None
        state.pop("_at", None)
        return state

    @property
    def run(self) -> Optional["Dat"]:
        """The sub-dat ``run/`` that the last run (``Dat.manager.run``) made, or ``None`` for a dat never run.

        Its results hold ``dat.run_at``, ``dat.run_time``, ``dat.host``, ``dat.pid``, ``dat.code``, ``dat.run_rev``
        (on a ledger) and ``dat.content``, and its ``work/`` is the run's scratch. ``None`` is also returned for a dat
        filled by hand, and for one loaded off a ledger with no ``run/`` in its folder: its run is a subdat, a value
        of its own under the alias ``<name>/run``, placed by a load of that name and by nothing else (SVP 241). Loaded
        as a plain ``Dat``, outside the load cache.

        A run is not content: it is outside the dat's hash, and nothing may depend on it. So a run function reads the
        ledger through ``dat.at``, and a result must not vary with the revision string ``dat.run_rev`` itself.
        """
        if self._run_dat is None:
            path = os.path.join(self._path, RUN_FOLDER)
            if os.path.exists(os.path.join(path, SPEC_YAML)):
                self._run_dat = self._world()._load(path, dat_class=Dat, cache_after_load=False)
        return self._run_dat

    @property
    def at(self) -> Any:
        """The ``Rev`` the dat's run was against, named by ``dat.run_rev`` (``<ledger>@<rev>``).

        The ledger is named rather than fixed, since a run may be on any ledger (SVP 1521). During the run it is the
        recording ``Rev``, so a read through it enters the entry's provenance and a memo hit stays sound; afterwards a
        plain one, its ledger the value's, else the one open under that name, else ``ledgers[name]`` (root's registry). A run
        function reads through it, and a result must not vary with the string ``dat.run_rev`` itself. A runtime
        attribute, never in ``_spec_.yaml`` or the hash. ``ValueError`` for a dat not run on a ledger.
        """
        held = self.__dict__.get("_at")
        if held is not None:
            return held
        run = self.run
        text = Dat.get(run.get_results(), DAT_RUN_REV, None) if run is not None else None
        if text is None:
            sealed = super().at                 # off the ledger, its `run/` a subdat left unplaced: its `db/at` row
            if sealed is None:
                raise ValueError(f"{self!r} ran on no ledger: its run records no {DAT_RUN_REV}")
            return sealed
        from .ledger.named import rev_named
        return rev_named(text, self.rev.ledger if self.rev is not None else self.__dict__.get("_ledger"))

    def _world(self) -> DatManager:
        """The manager that loaded this dat, else the default one."""
        return self._manager if self._manager is not None else Dat.manager

    @classmethod
    def validate_spec(cls, spec: SpecDict) -> SpecDict:
        """Check a spec on create and on load, on the class ``dat.kind`` names; return it, possibly coerced.

        The default fills ``dat.kind`` with the class, and requires ``spec`` and ``spec['dat']`` to be mappings
        (``TypeError``); ``dat.standing`` to be ``rolling`` or ``referenceable`` (``ValueError``); and ``dat.kind``,
        ``dat.name``, ``dat.do``, ``dat.target_exists`` to be strings, which catches a ``{reference}`` left unquoted
        in YAML -- a mapping with a ``dat`` key whose string fields are strings, else it would arrive as a dict. A
        subclass calls ``super()`` and adds its own checks.
        """
        if not isinstance(spec, dict):
            raise TypeError(f"{cls.__name__}: a spec is a mapping, got {type(spec).__name__}")
        dat = spec.setdefault("dat", {})
        if not isinstance(dat, dict):
            raise TypeError(f"{cls.__name__}: spec['dat'] is a mapping, got {type(dat).__name__}")
        dat.setdefault("kind", _kind_name(cls))
        if dat.get("standing") is not None and dat["standing"] not in _SPEC_DEMANDS:
            raise ValueError(f"{cls.__name__}: dat.standing in a spec is one of "
                             f"{list(_SPEC_DEMANDS)}, got {dat['standing']!r}")
        for key in ("kind", "name", "do", "target_exists"):
            if key in dat and dat[key] is not None and not isinstance(dat[key], str):
                raise TypeError(
                    f"{cls.__name__}: dat.{key} is a string, got {dat[key]!r} "
                    f"(a value starting with '{{' must be quoted in YAML)"
                )
        return spec

    merge_dicts = staticmethod(merge_dicts)
    """Merge dicts left to right, each overriding the ones before -- the zipper merge ``dat.base`` uses.

    Mappings merge key by key; lists of mappings that all carry a ``name`` merge by name (``{name: X, remove: true}``
    deletes X); anything else is replaced whole. The first dict is copied unless ``inplace``. The way to vary an
    existing spec.
    """

    @staticmethod
    def cli_main(argv: Optional[List[str]] = None, *,
                 config: Union[None, str, Path] = None) -> int:
        """The command line (``just run``, ``x``), ``dvc_dat.do.cli_main``, for a program's own main.

        The program imports and mounts what it needs, then hands over its arguments; returns the exit code.
        """
        from .do import cli_main
        return cli_main(argv, config=config)

    def get_spec(self) -> SpecDict:
        """The spec as written to ``_spec_.yaml`` -- every ``{}`` was expanded once, when the dat was created.

        ``dat.name`` is the exception, keeping the path template as given (the folder the dat landed in is
        ``get_path_name()``); ``dat.base`` is already merged in. Nothing rewrites it.
        """
        return self._spec

    def get_results(self) -> SpecDict:
        """The mutable results dict of this dat, persisted by ``save()`` as ``_result_.yaml``.

        The run's function writes into it; it holds ``dat.dependencies`` during a run before anything is saved.
        """
        return self._result

    def get_path(self) -> str:
        """The absolute path of this dat's folder."""
        return self._path

    def get_path_name(self) -> str:
        """The path relative to the dat folder that holds it: this dat's name in every lookup and dependency map.

        The absolute path, for a dat outside every dat folder.
        """
        return self._world()._get_path_name(self._path)

    @classmethod
    def load(
        cls: Type[DatType],
        name_or_path: Union[str, Path],
        *,
        cache_after_load: bool = True,
    ) -> DatType:
        """Load the dat at ``name_or_path`` in the default world, as the class its ``dat.kind`` names.

        ``Dat.manager.load(name_or_path)``, checked to be an instance of ``cls``; ``TypeError`` when that class is not
        ``cls`` or a subclass -- an artifact's name is ``TypeError`` too. Takes no ``verify``; the default world's own
        setting applies. Recorded as a dependency inside a run, as every load is.
        """
        dat = cls.manager.load(name_or_path, cache_after_load=cache_after_load)
        return cls._require(dat, f"{cls.__name__}.load({str(name_or_path)!r})")

    @classmethod
    def create(
        cls: Type[DatType],
        spec: Union[Dict, str, None] = None,
        *,
        path: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> DatType:
        """Create a dat from ``spec`` at ``path`` (or the spec's ``dat.name`` template); run nothing.

        ``Dat.manager.create(spec, path=path, **kwargs)`` in the default world, the keywords merged into
        ``dat.kwargs`` as data (a template reads them as ``${dat.kwargs.x}``); ``path`` comes first,
        positionally. A spec with no ``dat.kind`` gets ``cls``; one naming a class outside ``cls`` is ``TypeError``
        before anything is written.
        """
        manager = cls.manager
        spec = manager._spec_of(spec)
        kind = spec["dat"].get("kind")
        if kind is None:
            spec["dat"]["kind"] = _kind_name(cls)
        elif not issubclass(named := manager._class_of(kind), cls):
            raise TypeError(f"{cls.__name__}.create: dat.kind {kind!r} is "
                            f"{named.__name__}, not a {cls.__name__}")
        return cls._require(manager.create(spec, path=path, **kwargs), f"{cls.__name__}.create")

    @classmethod
    def _require(cls: Type[DatType], dat: "Dat", what: str) -> DatType:
        if not isinstance(dat, cls):
            raise TypeError(f"{what}: {dat!r} is a {type(dat).__name__}, not a {cls.__name__}")
        return dat

    @staticmethod
    def standing(name: Union[str, Path, "Dat"]) -> Optional[str]:
        """``Dat.manager.standing(name)``: the stored standing of ``name``, or ``None`` when nothing is stored.

        One of ``rolling``, ``open``, ``sealed``, or ``referenceable``.
        """
        return Dat.manager.standing(name)

    def _standing(self) -> str:
        return self._written

    @staticmethod
    def save_artifact(source: Union[str, Path], *, type: Union[None, str, Callable] = None,
                      name: Optional[str] = None, link: bool = False) -> str:
        """``Dat.manager.save_artifact(...)``: store a file or folder as an artifact, returning its ``sha256:<hex>`` URN.

        The artifact is recorded under ``type``, with ``name`` as its chosen name. Bytes already stored are not stored
        again: a new ``name`` becomes a second key to them, nothing copied.
        """
        return Dat.manager.save_artifact(source, type=type, name=name, link=link)

    @staticmethod
    def load_artifact(name: Union[str, Path], *, verify: Optional[bool] = None) -> Any:
        """``Dat.manager.load_artifact(name, verify=verify)``: an artifact by name or URN, built by its recorded type.

        Its payload's ``Path`` with none.
        """
        return Dat.manager.load_artifact(name, verify=verify)

    def _demands_referenceable(self) -> bool:
        return Dat.get(self._spec, DAT_STANDING, None) == REFERENCEABLE

    def save(self) -> None:
        """Write ``_result_.yaml``, stamping ``dat.sha256`` and ``dat.standing``; the first save that counts seals the dat.

        The hash is stamped ``dat.hash: functional``, covers the folder as it now stands, with its subdats (``run/``
        among them) and ``dat.name`` left out, and is keyed in the index. Inside the dat's own run a save writes a
        checkpoint (``open``, or ``rolling``) and asks for the seal, which comes when the run returns; anywhere else
        it seals now and adds the dependency ``$MANUAL``: made or finished by hand, its dependencies incomplete. A dat
        already ``sealed`` or ``referenceable`` is ``RuntimeError``, and so is a seal that earns less than a spec's
        ``dat.standing: referenceable`` demand.

        The seal trims the dependency map to its roots and stamps the least standing of its inputs (a rolling one
        counts as sealed), capped at ``sealed`` by a run's code that is dirty or outside a checkout; an input recorded
        ``unsealed`` keeps it ``open`` for good. A spec saying ``dat.standing: rolling`` saves at will and never
        freezes.
        """
        standing = self._standing()
        if standing in _FROZEN:
            raise RuntimeError(f"save: {self!r} is sealed; a dat is saved once")
        if self._running:
            self._save_asked = True
            self._write(ROLLING if standing == ROLLING else OPEN)   # a checkpoint
            return
        self._seal(manual=True)

    def _seal(self, *, manual: bool) -> None:
        manager = self._world()
        deps = Dat.get(self._result, DAT_DEPENDENCIES, None)
        if manual:
            deps = dict(deps or {})
            deps.setdefault(DEP_MANUAL, "manual")
        if deps:
            deps = manager.roots(deps)
            Dat.set(self._result, DAT_DEPENDENCIES, deps)
        if self._standing() == ROLLING:
            self._write(ROLLING)
            return
        earned, why = manager._earned(self, deps or {})
        if self._demands_referenceable() and earned != REFERENCEABLE:
            raise RuntimeError(f"save: {self!r} demands dat.standing: referenceable, "
                               f"and {why}")
        self._write(earned)

    def _write(self, standing: str) -> None:
        old = self._sha256()
        if isinstance(self._result.get("dat"), dict):
            self._result["dat"].pop("referenceable", None)     # 2.13's key
        Dat.set(self._result, DAT_STANDING, standing)
        Dat.set(self._result, DAT_HASH, HASH_FUNCTIONAL)
        Dat.set(self._result, DAT_SHA256, _hash_dat(self._path, self._result))
        with Path(self.get_path(), RESULT_YAML).open("w") as out:
            yaml.dump(self._result, out, Dumper=_SpecDumper, sort_keys=False)
        self._written = standing
        self._world()._index_dat(self, old)
        run = self.run
        if run is not None and Dat.get(run.get_results(), DAT_RUN_TIME, None) is not None:
            Dat.set(run.get_results(), DAT_CONTENT, self._sha256())   # what the run sealed
            _write_run(run)

    def verify(self) -> bool:
        """``True`` when the folder on disk, ``run/`` left out, still hashes to its ``dat.sha256``.

        The hash it hashes to is the one its ``_result_.yaml`` carries -- the dat is exactly as it was last saved.
        ``False`` when it does not, when there is no ``_result_.yaml``, or when it carries no hash. Reads the file,
        not the in-memory results.
        """
        result_path = Path(self._path, RESULT_YAML)
        if not result_path.exists():
            return False
        on_disk = yaml.safe_load(result_path.read_text()) or {}
        stored = Dat.get(on_disk, DAT_SHA256, None)
        return stored is not None and stored == _hash_dat(self._path, on_disk)

    def _sha256(self) -> Optional[str]:
        """The hash of the last save; None before the first."""
        return Dat.get(self._result, DAT_SHA256, None)

    def delete(self, *, must_exist=True) -> bool:
        """Delete the folder and its contents; ``TypeError`` on a ledger project, which never deletes.

        Drops the dat from the load cache and its keys from the index, then removes the folder. ``True`` when removed;
        a missing folder raises ``Exception`` with ``must_exist``, else returns ``False``.
        """
        self._world()._refuse_delete_on_a_ledger(
            f"Dat.delete: {self.get_path_name()!r} is in a ledger project")
        self._world()._dat_cache.pop(self._path, None)
        self._world()._index_forget(self.get_path_name())
        try:
            shutil.rmtree(self._path)
        except FileNotFoundError:
            if must_exist:
                raise Exception(f"DAT DELETE: Folder missing {self._path!r}.")
            return False
        return True

    def copy(self: DatType, new_path: Union[str, Path], *, run: bool = True) -> DatType:
        """A copy of the folder at ``new_path`` (a name resolves under the first dat folder), loaded as the same class.

        ``run=False`` leaves ``run/`` behind, which changes nothing about the copy's hash. An existing target raises
        ``Exception``. The copy is not indexed until it is saved.
        """
        manager = self._world()
        new_path_ = manager._resolve_path(new_path)
        if os.path.exists(new_path_):
            raise Exception(f"DAT COPY: Folder exists {new_path!r}.")
        ignore = None if run else (
            lambda folder, names: [RUN_FOLDER] if folder == self._path else [])
        shutil.copytree(self._path, new_path_, ignore=ignore)
        return manager._load(new_path_, dat_class=type(self))

    def move(self: DatType, new_path: Union[str, Path]) -> DatType:
        """Move this dat's folder to ``new_path``; returns the dat loaded from its new place.

        Drops the old name's index keys and keys the moved dat's hash to its new name. An existing target raises
        ``Exception``. Dependency maps that recorded the old name keep it.
        """
        manager = self._world()
        manager._dat_cache.pop(self._path, None)
        new_path_ = manager._resolve_path(new_path)
        if os.path.exists(new_path_):
            raise Exception(f"DAT MOVE: Folder exists {new_path!r}.")
        manager._index_forget(self.get_path_name())
        shutil.move(self._path, new_path_)
        moved = manager._load(new_path_, dat_class=type(self))
        if moved._sha256():
            manager._index_dat(moved, None)
        return moved

    def __repr__(self) -> str:
        """`<Dat: tables/table12>`, its name in its dat folder.

        Once a value is sealed from it, its label as every value prints (`<Dat table/12>`,
        `<Dat sealed #2db69ce1>`, DAT 1036).
        """
        if self.sealed:
            return Value.__repr__(self)
        return f"<{type(self).__name__}: {self.get_path_name()}>"

    # -- the value: preds and the folder codec (DAT 1038) ----------------------

    @property
    def preds(self) -> Dict[str, Any]:  # type: ignore[override]
        """Unsealed, the folder's facts (``_default_preds``); sealed, the read-only mapping the seal fixed.

        Unsealed, read afresh on each access and built from the scalar entries of the spec's ``dat.kwargs``, then the
        scalar top-level entries of ``_result_.yaml`` other than ``dat:``, then the spec's ``dat.preds`` (SVP 1508; a
        later source wins a clash), under every pred written by hand, which wins. The names are the class's
        ``@ledger_class(preds=...)`` plus the folder's own; the ``dat:`` record of the results (dependencies,
        standing, sha256) is never a pred.
        """
        d = self.__dict__.get("_preds")
        if isinstance(d, FrozenPreds):
            return d
        if not isinstance(d, _DatPreds):
            d = self.__dict__["_preds"] = _DatPreds(d or {})
        d._refresh(self._default_preds())
        return d

    @preds.setter
    def preds(self, value: Any) -> None:
        if self.sealed:
            raise TypeError("cannot modify a sealed value's preds")
        self.__dict__["_preds"] = _DatPreds(dict(value))

    def _default_preds(self) -> Dict[str, Any]:
        """A dat's own preds: the scalar entries of its spec's `dat.kwargs`, then the scalar top-level
        entries of `_result_.yaml` other than `dat:`, then its spec's `dat.preds` (SVP 1508), read from the
        folder; a later source wins a clash."""
        spec, result = _read_folder(self._path)
        dat = spec.get("dat")
        kwargs = dat.get("kwargs") if isinstance(dat, dict) else None
        preds = dat.get("preds") if isinstance(dat, dict) else None
        out: Dict[str, Any] = {}
        for source in (kwargs if isinstance(kwargs, dict) else {}, result, preds if isinstance(preds, dict) else {}):
            for k, v in source.items():
                if source is result and k == "dat":
                    continue
                if isinstance(k, str) and k and not k.startswith("db/") and isinstance(v, (str, int, float, bool)):
                    out[k] = v
        return out

    def _pred_names(self) -> Tuple[str, ...]:
        """The class's declared names, then the folder's own (`_default_preds`)."""
        declared = type(self)._ledger_preds
        return tuple(declared) + tuple(k for k in self._default_preds() if k not in declared)

    def _sealable(self) -> None:
        """A folder whose `_spec_` names a `dat.kind` is a dat, and seals as a value only once saved:
        an open one (never saved, or a checkpoint) is `ValueError`."""
        spec, result = _read_folder(self._path)
        dat = spec.get("dat")
        if isinstance(dat, dict) and dat.get("kind") is not None and _standing_of(spec, result) == OPEN:
            raise ValueError(f"{self!r} is open: a dat seals as a value once saved; dat.save() first "
                             "(a run function's dat.save() does it when the run returns)")

    def _walk(self) -> Iterator[Tuple[str, Path]]:
        """`(relpath, path)` of every file in the value, in sorted order (`__pycache__` and the subdats
        skipped: `is_subdat_dir`)."""
        for root, dirs, names in os.walk(self._path):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__" and not is_subdat_dir(os.path.join(root, d)))
            for n in sorted(names):
                p = Path(root, n)
                yield p.relative_to(self._path).as_posix(), p

    def _subdats(self) -> List[Tuple[str, "Dat"]]:
        """`(relpath, the subdat)` of each dat in the folder tree, as the class its `dat.kind` names; one
        sealed by `v.seal()` and not saved since comes back as it was sealed (`sealed_at_path`)."""
        from .ledger.sandbox import unguarded

        out: List[Tuple[str, Dat]] = []
        for rel, p in subdat_dirs(self._path):
            cls = self._world()._class_of(Dat.spec_kind(p))
            with unguarded():                   # the ledger's own read of the kept folder
                child = cls.sealed_at_path(p)
            out.append((rel, child if child is not None else cls._from_folder(p)))
        return out

    def _manifest(self) -> Dict[str, str]:
        """`{relpath: sha256}` of the folder, rehashing only files whose (size, mtime, inode) moved.

        Each file is hashed in 1 MiB blocks and never held in memory; the per-file hashes are cached
        on the object, so `encode`, `_parts` and a save walk the folder but hash a file once."""
        from .ledger.store import file_sha

        cache = self.__dict__.get("_shas") or {}
        new: Dict[str, Tuple[tuple, str]] = {}
        for rel, p in self._walk():
            st = p.stat()
            sig = (st.st_size, st.st_mtime_ns, st.st_ino, st.st_dev)
            hit = cache.get(rel)
            new[rel] = (sig, hit[1] if hit is not None and hit[0] == sig else file_sha(p))
        self.__dict__["_shas"] = new
        return {rel: h for rel, (_sig, h) in sorted(new.items())}

    def _forget(self) -> None:
        self.__dict__.pop("_shas", None)

    def _seal_path(self) -> Optional[str]:
        return str(Path(self._path).resolve())

    def _seal_bytes(self, size: int) -> int:
        return sum(sig[0] for sig, _h in (self.__dict__.get("_shas") or {}).values())

    @classmethod
    def sealed_at_path(cls, path: Any, *, name: Optional[str] = None) -> Optional["Dat"]:
        """The last seal record of the folder ``path``, reopened as the sealing process left it (``kept``).

        The ``Dat`` sealed last at ``path`` by ``v.seal()`` in any process and not saved since; ``None`` when no
        record names the folder. ``v.seal(t)`` on it saves it exactly as the sealing process would have: the same
        subject (its deps, provenance, environment and time are the record's), ``SealBroken`` when a byte of the
        folder changed since unless kept, the kept bytes when kept. The object is the class the record names, a
        subclass of the class called on (else ``TypeError``), made from its folder. ``name`` is the alias it will be
        saved under: a value sealed with it as a dep before it is saved binds the dep through that name at its own
        save, which refuses until the name holds these bytes.
        """
        from .ledger.kept import Kept

        record = Kept().for_path(path)
        if record is None:
            return None
        try:
            kind = _import_dotted(record["kind"])
        except (ImportError, AttributeError, ValueError):
            raise ImportError(f"{path}: sealed as {record['kind']}, which does not import") from None
        if not (isinstance(kind, type) and issubclass(kind, cls)):
            raise TypeError(f"{path}: sealed as {record['kind']}, not a {cls.__name__}")
        obj = kind._from_folder(Path(record["path"]))
        obj._reopen(record, name)
        return obj

    def _present(self) -> bool:
        """Is the folder this value was loaded into still there, the same folder (a stat)?"""
        import stat

        try:
            st = os.stat(self._path)
        except OSError:
            return False
        return stat.S_ISDIR(st.st_mode) and self.__dict__.get("_dir_id") in (None, (st.st_dev, st.st_ino))

    def encode(self, out: Any) -> None:
        """Write the folder's content manifest, `{"files": {relpath: sha256}}`, canonical JSON, to `out`.

        The files themselves are `_parts`, stored one by one, never read whole.
        """
        from .ledger.codec import canonical

        out.write(canonical({"files": self._manifest()}).encode())

    def _parts(self) -> List[Tuple[str, Path]]:
        seen: Dict[str, Path] = {}
        manifest = self._manifest()
        for rel, p in self._walk():
            seen.setdefault(manifest[rel], p)
        return list(seen.items())

    @classmethod
    def _stored_hashes(cls, store: Any, h: str) -> List[str]:
        """The files of the manifest stored under `h`."""
        return list(dict.fromkeys(cls._stored_manifest(store, h).values()))

    @classmethod
    def kind_ok(cls, kind: str) -> bool:
        """Whether a folder whose ``_spec_`` names ``dat.kind`` ``kind`` loads as this class.

        The class is its ``db/value`` row's. Default: ``kind`` names this class or a subclass, by dotted name (or a
        bare name written before 2.3); a subclass widens it.
        """
        if kind in (_kind_name(cls), cls.__name__):
            return True
        try:
            named = _import_dotted(kind) if "." in kind else _find_subclass_by_name(cls, kind)
        except (ImportError, AttributeError, ValueError):
            return False
        return isinstance(named, type) and issubclass(named, cls)

    @staticmethod
    def spec_kind(path: Union[str, Path]) -> Optional[str]:
        """The ``dat.kind`` a folder's ``_spec_.yaml`` (or ``_spec_.json``) names, if any."""
        spec, _result = _read_folder(str(path))
        dat = spec.get("dat")
        kind = dat.get("kind") if isinstance(dat, dict) else None
        return kind if isinstance(kind, str) else None

    @staticmethod
    def _stored_manifest(store: Any, h: str) -> Dict[str, str]:
        """`{relpath: sha256}` of the manifest stored under `h`, read from the store as a stream."""
        with store.open(h) as src:
            return json.load(src)["files"]

    @staticmethod
    def _materialise(h: str, files: Dict[str, str], store: Any, name: Optional[str] = None) -> Path:
        """The folder of the manifest `files` (hash `h`), under `<store root>/dats/` (the data folder): at
        `<name>` when a name is given (an absolute path: there), else at the hash's first 16 hex. Files are
        placed by `store.get_to` (hardlinks on the same filesystem); a named folder holding other
        content is replaced by a new folder, never edited in place, a subdat placed inside it kept."""
        from .ledger.sandbox import unguarded     # the store's own write, also inside a sandboxed body

        if name is not None and os.path.isabs(name):
            dest = Path(name)
        elif name is not None:
            dest = store.dats / Path(*Path(check_name(name)).parts)
        else:
            dest = store.dats / h[:16]
        with unguarded():
            if name is not None and dest.exists() and not _holds(dest, files, store):
                old = dest.with_name(f"{dest.name}.old-{os.getpid()}-{id(files):x}")
                subdats = list(subdat_dirs(dest))
                dest.rename(old)
                for rel, _p in subdats:         # a subdat placed here is not this dat's to replace
                    (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                    (old / rel).rename(dest / rel)
                shutil.rmtree(old, ignore_errors=True)
            for rel, h in files.items():
                p = dest / rel
                if not p.exists():
                    store.get_to(h, p)
            dest.mkdir(parents=True, exist_ok=True)
        return dest

    @classmethod
    def decode(cls, src: Any, store: Any, *, name: Optional[str] = None) -> "Dat":
        """The dat the manifest read from ``src`` names: its folder rebuilt in the data folder.

        Placed under ``<art>/dats/<name>/`` when loaded by a ``name``, else ``<art>/dats/<first 16 hex of the manifest
        hash>/``; each file is placed by ``store.get_to`` (``ArtStore.get_to``). A named folder holding other content
        (the alias was re-pointed) is replaced. Its spec and results are read from there, the manifest itself read
        whole (paths and hashes).
        """
        from .ledger.codec import sha256

        data = src.read()
        return cls._from_folder(cls._materialise(sha256(data), json.loads(data)["files"], store, name))

    def _after_seal(self, store: Any, name: Optional[str] = None) -> None:
        self._forget()
        h = self.hash
        self._move_to(self._materialise(h, self._stored_manifest(store, h), store, name))   # as stored

    def _at_name(self, store: Any, name: str) -> None:
        self._forget()
        h = self.hash
        self._move_to(self._materialise(h, self._stored_manifest(store, h), store, name))

    @staticmethod
    def get(source: Union["Dat", dict], keys: Union[str, List[str]],
            default_value: Any = _NO_ARG) -> Any:
        """The value at a dotted key path (``"dat.do"``, or a list of keys) in a dict tree, or a dat's spec.

        ``source`` may be a dict tree or a ``Dat``. A missing key, or a value that is ``None``, returns
        ``default_value``, and is ``KeyError`` when none is given; a non-dict on the path is ``ValueError``.
        """
        return _dotted_get(source=source, keys=keys, default_value=default_value)

    @staticmethod
    def set(source: SpecDict, keys, value) -> None:
        """Set ``value`` at a dotted key path in a dict tree, creating missing levels as dicts.

        A non-dict on the path raises ``Exception``.
        """
        dotted_set(source, keys, value)


class DatContainer(Dat, Generic[DatType]):
    """A Dat whose folder holds other Dats, exposed through `get_dats()` / `get_dat_paths()`."""

    def get_dat_paths(self) -> List[str]:
        """The absolute paths of every dat folder below this one, sorted, the container itself left out.

        A child's `run/` folder is skipped. Computed on first call and kept.
        """
        if "_dat_paths" not in self.__dict__:
            self.__dict__["_dat_paths"] = DatContainer._find_dats_under(self._path)
        return self.__dict__["_dat_paths"]

    def get_dats(self) -> List[DatType]:
        """The contained Dats, loaded lazily through the container's manager.

        Each load is recorded inside a run. Computed on first call, then held in memory until this container is
        released.
        """
        if "_dats" not in self.__dict__:
            manager = self._world()
            self.__dict__["_dats"] = [manager.load(p) for p in self.get_dat_paths()]
        return self.__dict__["_dats"]

    @staticmethod
    def _find_dats_under(root_path: Union[str, Path]):
        root_path = str(root_path)
        results = []
        for root, dirs, files in os.walk(root_path):
            if SPEC_YAML in files or SPEC_JSON in files:
                dirs[:] = [d for d in dirs if d != RUN_FOLDER]   # a dat's run is not a child
            for name in files:
                if name == SPEC_JSON or name == SPEC_YAML:
                    results.append(os.path.dirname(os.path.join(root, name)))
        results.sort()
        assert os.path.abspath(results[0]) == os.path.abspath(root_path)
        del results[0]
        return results


# =============================================================================
# The folder codec's helpers
# =============================================================================

def _read_folder(path: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """`(spec, results)` as the folder holds them now: `_spec_.yaml` (or `.json`) and
    `_result_.yaml`, each `{}` when absent."""
    spec: Any = {}
    if os.path.exists(spec_path := os.path.join(path, SPEC_YAML)):
        with open(spec_path) as f:
            spec = yaml.safe_load(f) or {}
    elif os.path.exists(spec_path := os.path.join(path, SPEC_JSON)):
        with open(spec_path) as f:
            spec = json.load(f)
    if not isinstance(spec, dict):
        raise TypeError(f"{spec_path}: a spec is a mapping, got {type(spec).__name__}")
    result: Any = {}
    if os.path.exists(result_path := os.path.join(path, RESULT_YAML)):
        with open(result_path) as f:
            result = yaml.safe_load(f) or {}
    return spec, result if isinstance(result, dict) else {}


class _DatPreds(dict):
    """An unsealed dat's preds: the folder's own under every key written by hand (or deleted), which wins."""

    def __init__(self, explicit: Dict[str, Any]) -> None:
        super().__init__(explicit)
        self._explicit = set(explicit)
        self._dropped: set = set()

    def __setitem__(self, k: str, v: Any) -> None:
        self._explicit.add(k)
        self._dropped.discard(k)
        super().__setitem__(k, v)

    def __delitem__(self, k: str) -> None:
        super().__delitem__(k)
        self._explicit.discard(k)
        self._dropped.add(k)

    def update(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        for k, v in dict(*args, **kwargs).items():
            self[k] = v

    def __ior__(self, other: Any) -> "_DatPreds":  # type: ignore[override]
        self.update(other)
        return self

    def setdefault(self, k: str, v: Any = None) -> Any:
        if k not in self:
            self[k] = v
        return self[k]

    def pop(self, k: str, *default: Any) -> Any:
        if k in self:
            v = dict.__getitem__(self, k)
            del self[k]
            return v
        if default:
            return default[0]
        raise KeyError(k)

    def popitem(self) -> Tuple[str, Any]:
        k = next(reversed(list(self)))
        return k, self.pop(k)

    def clear(self) -> None:
        for k in list(self):
            del self[k]

    def _refresh(self, defaults: Dict[str, Any]) -> None:
        for k in [k for k in self if k not in self._explicit]:
            dict.__delitem__(self, k)
        for k, v in defaults.items():
            if k not in self._explicit and k not in self._dropped:
                dict.__setitem__(self, k, v)


def _holds(dest: Path, files: Dict[str, str], store: Any) -> bool:
    """Does the folder hold exactly these files with these hashes (a linked file is checked by inode)?  A
    subdat placed inside it is not among them."""
    from .ledger.store import file_sha

    found = set()
    for root, dirs, names in os.walk(dest):
        dirs[:] = [d for d in dirs if not is_subdat_dir(os.path.join(root, d))]
        for n in names:
            found.add(Path(root, n).relative_to(dest).as_posix())
    if found != set(files):
        return False
    for rel, h in files.items():
        p, blob = dest / rel, store.path(h)
        try:
            if os.path.samefile(p, blob):
                continue
        except OSError:
            pass
        if file_sha(p) != h:
            return False
    return True


# =============================================================================
# Dotted-key helpers
# =============================================================================

def _dotted_get(source: Union[Dat, dict], keys: Union[str, List[str]], default_value: Any = _NO_ARG):
    d = source.get_spec() if isinstance(source, Dat) else source
    return dotted_get(d, keys, default_value)



hooks.register_dat_layer(Dat=Dat)       # a dat is a ledger Value from here on; the ledger never imports this module
