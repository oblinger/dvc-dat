---
description: "`Dat`, `DatManager`, `DatContainer`, `Namespace`: the folder that is its own recipe, and the world that makes, loads, runs and seals it. Source: `dvc_dat/core.py`, `dvc_dat/do.py`."
---
:>> [DAT](../DAT%20Track/DAT.md) → [DAT Dat](ha://p/DAT%20Dat) 
# DAT Dat
A dat is a folder whose `_spec_.yaml` is a complete, argumentless recipe for itself and whose `_result_.yaml` holds what running it produced, sealed under a content hash.

![DAT Dat](DAT%20Dat.svg) 

**Classes:** [Dat](#Dat%20Interface) · [DatManager](#DatManager%20Interface) · [DatContainer](#DatContainer%20Interface) · [Namespace](#Namespace%20Interface) · [module functions](#dvc_dat%20Interface) 

*The spec is the record* is the topic that governs the Namespace node (arguments fork a new spec; they never ride beside one); the other topics annotate the nodes they govern.

This page covers the dat half of `dvc_dat`: `Dat`, `DatManager` and `DatContainer` in `dvc_dat/core.py`, `Namespace` in `dvc_dat/do.py`, and the package's exports; the figure above is the heart. The per-file detail page is [dat.md](dat.md); the history half, the ledger, has its own module doc, [DAT Ledger](ledger/DAT%20Ledger.md); the spec file is [Spec Format](../spec-format.md) and the command line [Command Line](../cli.md).



## Dat Interface
A folder of data described by its `_spec_.yaml`, held in memory as the spec as written, the mutable results, and the path. A dat is made by `Dat.create` or `DatManager.create` and read by `Dat.load` or `DatManager.load`; `Dat(path, spec, result)` is the constructor those call, and `Dat(path)` alone is the dat already in that folder, its spec and results read from there (`{}` each when absent). A dat is also a ledger value, one class (DAT 1038): `Dat` subclasses `dvc_dat.ledger.Value` and carries the folder codec, so `seal`, `preds`, `subject`, `sealed` and `hash` are on every dat; its bytes are the folder's manifest, its preds default to the spec's scalar `dat.kwargs` and the results' scalar top-level entries, and a dat seals as a value once saved ([DAT Ledger § Dat Interface](ledger/DAT%20Ledger.md#Dat%20Interface)). Subclasses are the dat's kinds: `dat.kind` in the spec names one, and a subclass overrides `validate_spec` to check its own fields. The class-level members act on the default world, `Dat.manager`; an instance acts on the manager that loaded it.

| Dat | |
| --- | --- |
| [manager](#^manager) | The default world on the class; the dat's own world on an instance |
| [ns](#^dat-ns) | The default world's namespace, class-level only; not callable |
| [load](#^load) | Open a dat on disk in the default world |
| [create](#^create) | Make a dat on disk in the default world |
| [get_spec](#^get-spec) | The spec as written |
| [get_results](#^get-results) | The mutable results, persisted by save |
| [get_path](#^get-path) | The folder's absolute path |
| [get_path_name](#^get-path-name) | The name: the path relative to its dat folder |
| [run](#^run) | The run sub-dat that made this dat |
| [save](#^save) | Write the results, stamp the hash and standing; seal |
| [verify](#^verify) | Does the folder still hash to its stored hash? |
| [standing](#^standing) | How far a stored name can be relied on |
| [save_artifact](#^save-artifact) | Store a file or folder as an artifact |
| [load_artifact](#^load-artifact) | An artifact by name or URN |
| [delete](#^delete) | Remove the folder |
| [copy](#^copy) | Copy the folder to a new path |
| [move](#^move) | Move the folder to a new path |
| [validate_spec](#^validate-spec) | The subclass hook that checks a spec |
| [get](#^get) | Read a dotted key path in a dict tree |
| [set](#^set) | Write a dotted key path in a dict tree |
| [merge_dicts](#^merge-dicts) | The zipper merge `dat.base` uses |
| [cli_main](#^cli-main) | The command line (`just run`), for a program's main |

**manager**`: DatManager`
    On the class, the process's default world: a plain assignable attribute, built on first read by `DatManager.load_dat_config()`, shared by every subclass, and replaced by assigning a `DatManager` (anything else is `TypeError`; assigning `None` clears it, so the next read builds it again). On an instance, read-only: the manager that loaded the dat, else the default. See [The manager is the world](#The%20manager%20is%20the%20world). ^manager

**ns**`: Any` (class property)
    The forwarder `dvc_dat.do.ns`: every attribute goes to `Dat.manager.ns`, whichever manager that is at the moment of use, and it is not callable (running is `Dat.manager.run`, 2.35), so `ns = Dat.ns` binds a shortcut that follows a later reassignment. It is defined on the metaclass, so `Dat.ns` works and `some_dat.ns` is `AttributeError`. ^dat-ns

**load**`(name_or_path: str | Path, *, cache_after_load: bool = True) -> Dat` (classmethod)
    `Dat.manager.load(name_or_path)`, checked to be an instance of `cls`: a dat built as the class its `dat.kind` names, and `TypeError` when that class is not `cls` or a subclass (an artifact's name is `TypeError` too). Takes no `verify`; the default world's own setting applies. Recorded as a dependency inside a run, as every load is. ^load

**create**`(path: str | Path | None = None, spec: dict | str | None = None) -> Dat` (classmethod)
    `Dat.manager.create(spec, path=path)` with the class filled in: a spec with no `dat.kind` gets `cls`, and one naming a class outside `cls` is `TypeError` before anything is written. `path` comes first, positionally. ^create

**get_spec**`() -> SpecDict`
    The spec as written to `_spec_.yaml`: every `{}` reference already expanded except `dat.name`, which keeps the path template as given (the folder the dat landed in is `get_path_name()`), `dat.base` already merged in. Nothing rewrites it. ^get-spec

**get_results**`() -> SpecDict`
    The results dict, mutable; the run's function writes into it and `save` persists it as `_result_.yaml`. Holds `dat.dependencies` during a run before anything is saved. ^get-results

**get_path**`() -> str`
    The absolute path of the dat's folder. ^get-path

**get_path_name**`() -> str`
    The path relative to the dat folder that holds it, which is the dat's name in every lookup and dependency map; the absolute path for a dat outside every dat folder. ^get-path-name

**run**`: Dat | None` (property)
    The sub-dat `run/` that the last run (`Dat.manager.run`) made: its results hold `dat.run_at`, `dat.run_time`, `dat.host`, `dat.pid`, `dat.code` and `dat.content`, and its `work/` is the run's scratch. `None` for a dat never run. Loaded as a plain `Dat`, outside the load cache. See [The run sub-dat](#The%20run%20sub-dat). ^run

**save**`() -> None`
    Write `_result_.yaml`, stamping `dat.sha256`, `dat.hash: functional` and `dat.standing`, and key the new hash in the index. Inside the dat's own run it writes a checkpoint (`open`, or `rolling`) and asks for the seal, which comes when the run returns; anywhere else it seals now and adds the dependency `$MANUAL`. A dat already `sealed` or `referenceable` is `RuntimeError`, and so is a seal that earns less than a spec's `dat.standing: referenceable` demand. See [Sealing and the content hash](#Sealing%20and%20the%20content%20hash) and [Standing](#Standing). ^save

**verify**`() -> bool`
    `True` when the folder on disk, `run/` left out, still hashes to the `dat.sha256` its `_result_.yaml` carries; `False` when it does not, when there is no `_result_.yaml`, or when it carries no hash. Reads the file, not the in-memory results. ^verify

**standing**`(name: str | Path | Dat) -> str | None` (static)
    `Dat.manager.standing(name)`: `rolling`, `open`, `sealed` or `referenceable`, or `None` when nothing is stored under `name`. ^standing

**save_artifact**`(source: str | Path, *, type: str | Callable | None = None, name: str | None = None, link: bool = False) -> str` (static)
    `Dat.manager.save_artifact(...)`: store a file or folder as an artifact and return its URN, `sha256:<hex>`. ^save-artifact

**load_artifact**`(name: str | Path, *, verify: bool | None = None) -> Any` (static)
    `Dat.manager.load_artifact(name, verify=verify)`: an artifact by name or URN, handed to its recorded type, its payload's `Path` with none. ^load-artifact

**delete**`(*, must_exist=True) -> bool`
    Drop the dat from the load cache and its keys from the index, then remove the folder. `True` when removed; a missing folder raises `Exception` with `must_exist`, else returns `False`. ^delete

**copy**`(new_path: str | Path, *, run: bool = True) -> Dat`
    Copy the folder to `new_path` (a name resolves under the first dat folder) and load the copy as the same class. `run=False` leaves `run/` behind, which does not change the copy's hash. An existing target raises `Exception`. The copy is not indexed until it is saved. ^copy

**move**`(new_path: str | Path) -> Dat`
    Move the folder to `new_path`, drop the old name's index keys, and key the moved dat's hash to its new name. Returns the dat loaded from its new place. An existing target raises `Exception`. Dependency maps that recorded the old name keep it. ^move

**validate_spec**`(spec: SpecDict) -> SpecDict` (classmethod)
    Check a spec on create and on load, on the class `dat.kind` names, and return it, possibly coerced. The default fills `dat.kind` with the class, requires `spec` and `spec['dat']` to be mappings (`TypeError`), `dat.standing` to be `rolling` or `referenceable` (`ValueError`), and `dat.kind`, `dat.name`, `dat.do`, `dat.target_exists` to be strings, which catches a `{reference}` left unquoted in YAML. A subclass calls `super()` and adds its own checks. ^validate-spec

**get**`(source: Dat | dict, keys: str | list[str], default_value: Any = <required>) -> Any` (static)
    The value at a dotted key path (`"dat.do"` or a list of keys) in a dict tree, or in a dat's spec when `source` is a `Dat`. A missing key, or a value that is `None`, returns `default_value`, and is `KeyError` when none is given; a non-dict on the path is `ValueError`. ^get

**set**`(source: SpecDict, keys, value) -> None` (static)
    Set `value` at a dotted key path, creating the missing levels as dicts; a non-dict on the path raises `Exception`. ^set

**merge_dicts**`(*dicts: Dict, inplace: bool = False) -> Dict` (static)
    Merge dicts left to right, each overriding the ones before: mappings merge key by key, lists of mappings that all carry a `name` merge by name (`{name: X, remove: true}` deletes X), and anything else is replaced whole. The first dict is copied unless `inplace`. The merge `dat.base` uses, and the way to vary an existing spec. ^merge-dicts

**cli_main**`(argv: list[str] | None = None, *, config: str | Path | None = None) -> int` (static)
    The command line (`just run`, `x`), `dvc_dat.do.cli_main`, for a program's own main: the program imports and mounts what it needs, then hands over its arguments. Returns the exit code. ^cli-main



## DatManager Interface
A world of dats: the dat folders searched by name (the first is where new dats are made), the artifact folder beside them, the index of names and URNs, and an `ns` namespace that names things; `run` runs dats, specs and callables. Every dotted spec, `dat.base`, `{}` expansion, path lookup and run goes through the manager's `ns`, so every load inside a run passes through the manager and is recorded. Any number of managers coexist; `Dat.manager` is the default one. `run` is fixed; a subclass that overrides the private `_execute` and calls `super()` wraps every run in its world.

| DatManager | |
| --- | --- |
| [__init__](#^--init--) | A world on a list of dat folders; reads nothing from disk |
| [load_dat_config](#^load-dat-config) | A world from the nearest `.datconfig.yaml` |
| [ns](#^datmanager-ns) | The manager's own `Namespace` |
| [create](#^datmanager-create) | Resolve, validate, place, expand and write a new dat |
| [load](#^datmanager-load) | A dat or an artifact by name or URN |
| [load_path](#^load-path) | Where load would find it, with nothing built |
| [exists](#^exists) | Is anything stored under this name? |
| [standing](#^datmanager-standing) | How far a stored name can be relied on |
| [run](#^datmanager-run) | Run a dat, a template spec or a callable; the one run |
| [recording](#^recording) | Capture every load in a block into a dat's dependencies |
| [record_dependency](#^record-dependency) | Record an input that no load went through |
| [roots](#^roots) | A dependency map trimmed to its roots |
| [code_of](#^code-of) | The git branch, commit and dirty flag of a function |
| [save_artifact](#^datmanager-save-artifact) | Store a file or folder by hash |
| [load_artifact](#^datmanager-load-artifact) | An artifact only, by name or URN |
| [reindex](#^reindex) | Rebuild the index from the folders |
| [expand](#^expand) | Expand `{}` references through this world |
| [expand_spec](#^expand-spec) | Merge a spec's `dat.base`, then expand every string, through this world |

**__init__**`(*, dat_folders: list[str], art_folder: str | None = None, index: str | None = None, ns: Namespace | None = None, verify: bool = False)`
    A world on `dat_folders`, searched in order, the first written to; `art_folder` holds the artifacts, and with none this world holds no artifacts. `index` is the index file, default `_index_.json` in the artifact folder, else in the first dat folder. `ns` adopts an existing namespace with its mounts, and adopting the default world's `ns` makes this manager the default world; with none the manager builds a fresh `Namespace`. Every manager mounts `dvc_dat.dat_tools` at `dt`. `verify` sets the default of every load's `verify`. Reads nothing from disk. A string for `dat_folders` is `TypeError`, an empty list `ValueError`, an artifact folder nested with a dat folder `ValueError`, a non-bool `verify` `TypeError`. ^--init--

**load_dat_config**`(start: str | Path | None = None, *, ns: Namespace | None = None) -> DatManager` (classmethod)
    A new manager from the `.datconfig.yaml` found walking up from `start` (default the working directory; a file path names the config file itself), with `.datconfig.override.yaml` over it and `DAT_FOLDERS` / `DAT_ART_FOLDER` over both. Relative folders resolve against the config's folder, which goes first on `sys.path`. A `manager:` key builds that dotted subclass instead, and its `CONFIG_KEYS` class attribute names extra keys passed to its constructor. An unknown key, or a malformed value, is `ValueError`; a `manager:` that is not a subclass is `TypeError`. See [Configuration](#Configuration). ^load-dat-config

**ns**`: Namespace`
    The manager's namespace, its only public attribute: `m.ns.mount(...)` adds names to it, `m.ns.load(...)` resolves them; it is not callable. ^datmanager-ns

**create**`(spec: dict | str | None = None, *, path: str | Path | None = None) -> Dat`
    Make a dat as the class its `dat.kind` names. `spec` is a dict or a dotted name loaded through `ns`; `dat.base` is merged in, `validate_spec` runs, and the folder is `path`, else the spec's `dat.name` template, else `anonymous/Dat{unique}`, under the first dat folder. `dat.target_exists` settles an existing folder, and `use` returns the dat already there. Every `{}` in the spec is expanded once, with the same `now` and `unique` the folder got, `dat.name` keeps the path template (`path` as given, else the spec's own; a constant path is its own template), never its expansion, and the result is written as `_spec_.yaml`; no `_result_.yaml` is written. A name an artifact holds is `FileExistsError`; a spec that is not YAML data once expanded is `TypeError`, and the folder is removed. See [The spec is the record](#The%20spec%20is%20the%20record). ^datmanager-create

**load**`(name: str | Path, *, cache_after_load: bool = True, verify: bool | None = None) -> Any`
    What `name` names: a dat, built as the class its `dat.kind` names, or an artifact, handed to the type recorded at its save. `name` is a dat's name or path, an artifact's name, or the `sha256:` URN of either. A dat is searched as an absolute path, then among the dats mounted in `ns`, then in each dat folder; not found is `KeyError`, a folder with no spec `FileNotFoundError`, a name both a dat and an artifact hold `ValueError`. Dats are cached by path, weakly, so a second load returns the same object while it lives; `cache_after_load=False` skips the cache. `verify` (default the manager's) re-hashes and raises `ValueError` naming both hashes on a mismatch. Inside a recording the load lands in the recording dat's `dat.dependencies`. ^datmanager-load

**load_path**`(name: str | Path, *, verify: bool | None = None) -> Path`
    The dat's folder or the artifact's payload that `load(name)` would use, as a `Path`, with no type called. Recorded and verified exactly as `load`. ^load-path

**exists**`(name: str | Path) -> bool`
    `True` when `name` (a dat's name, an artifact's, or a URN) names something stored; a dat counts when its folder holds a spec file. ^exists

**standing**`(name: str | Path | Dat) -> str | None`
    How far `name` can be relied on, read from its files without building it: `rolling`, `open`, `sealed` or `referenceable`; `None` when nothing is stored under it. An artifact is `referenceable`; a `Dat` instance answers from its last write. See [Standing](#Standing). ^datmanager-standing

**run**`(target: str | dict | Dat | Callable, *args, **kwargs) -> Any`
    The one way to run a dat outside a ledger, fixed (2.35, DAT 1049). `target` is first loaded through `ns` when it is a name. A callable is called with `args` and `kwargs`. A template spec is forked: `args` replace `dat.args`, `kwargs` update `dat.kwargs` key by key, the new spec creates a dat (`dat.target_exists: use` returns the existing one unrun), and that dat runs with no call-site arguments. A `Dat` runs in place with no arguments, which a sealed dat refuses, and with arguments forks a new dat from its spec that lands beside it (`target_exists` `error` becomes `increment`). Anything else is `TypeError`. Returns the run's value, or the dat when the spec has no `dat.do`. Every error is re-raised as `Exception("In <target>")` chained from the original. See [The spec is the record](#The%20spec%20is%20the%20record).

    A dat's run (the private `_execute`) calls `fn(dat, *dat.args, **dat.kwargs)`, with `fn` the object `dat.do` names loaded through this world's `ns`, inside `recording(dat)`, with a fresh `run/` sub-dat holding the run's record and `run/work/` as the working directory. Returns `fn`'s value, or the dat when the spec has no `dat.do`. Saves nothing by itself; a `dat.save()` inside `fn` is answered with the seal when `fn` returns. A sealed dat is `RuntimeError`, a non-callable `dat.do` `TypeError`, and a spec demanding `referenceable` is `RuntimeError` when the code is dirty or outside a git checkout. Every run in the world, nested ones and a ledger's dat runs included, comes there; `dat.run` is the `run/` sub-dat. See [The run sub-dat](#The%20run%20sub-dat). ^datmanager-run

**recording**`(dat: Dat)` (context manager)
    Every `load`, `load_path` and `save_artifact` inside the block lands in `dat`'s `dat.dependencies`, name to hash. Blocks nest: when an inner block ends, its dat becomes one entry of the outer one. A run calls its function inside one; a builder gathering a dat's inputs outside a run uses it directly. See [Dependency capture](#Dependency%20capture). ^recording

**record_dependency**`(name: str, sha256: str | None = None) -> None`
    Add `name -> sha256` to the recording dat's dependencies, for an input that reached the run around the manager (a URL, a file read directly). `RuntimeError` when nothing is recording. ^record-dependency

**roots**`(deps: Dict[str, Any]) -> Dict[str, Any]`
    `deps` less every entry that another entry's dat already lists among its own dependencies; the trim a seal applies. ^roots

**code_of**`(fn: Callable) -> Dict[str, Any] | None` (static)
    `{branch, commit, dirty}` of the git checkout holding `fn`'s source, as a run records it in `dat.code`: `branch` is `None` on a detached HEAD, `dirty` counts tracked files outside the paths the repo's `.gitattributes` marks `dat-noncode`. `None` when the source is outside a checkout. ^code-of

**save_artifact**`(source: str | Path, *, type: str | Callable | None = None, name: str | None = None, link: bool = False) -> str`
    Store the file or folder `source` in the artifact folder and return its URN, `sha256:<hex>`. `type` is what a load hands the payload's path to: a class or callable, recorded by its dotted name, or that name as a string, anything `ns.load` resolves; one that does not load back by its name is `TypeError`. `name` is a relative path held once; with none the artifact answers to its URN only. Bytes already stored are not stored again: the new name becomes a second key to them. `link` hard-links instead of copying. Errors: no artifact folder `RuntimeError`, a malformed name `ValueError`, a missing source `FileNotFoundError`, a name already held by a dat or an artifact `FileExistsError`. Recorded inside a recording. See [Artifacts and the index](#Artifacts%20and%20the%20index). ^datmanager-save-artifact

**load_artifact**`(name: str | Path, *, verify: bool | None = None) -> Any`
    The artifact `name` (a name or a URN) names, handed to its recorded type, or its payload's `Path` with none. A dat's name is `KeyError`; `load` takes either. A type that no longer resolves is `ImportError`. ^datmanager-load-artifact

**reindex**`() -> int`
    Rebuild the index from the folders: every artifact's names and URN from its `_art_.yaml`, every saved dat's URN from its `_result_.yaml`. Returns the number of keys. ^reindex

**expand**`(text: str, vars: Dict[str, Any] | None = None) -> Any`
    Expand the `{}` references in `text`, dotted names resolved through this manager's `ns`; the module function `dvc_dat.core.expand` with this world's resolver. A text that is exactly one reference returns the object itself. ^expand

**expand_spec**`(spec: Any, vars: Dict[str, Any] | None = None) -> Any`
    A copy of `spec` merged over its `dat.base` chain (a name, a spec, or a list of them, later entries winning, bases named through this `ns`), recursively, with `dat.base` dropped, then with every string value expanded as `expand` does; keys are left alone. A spec that is not a dict has no bases and is only expanded. `create` stores what this returns, except `dat.name`. ^expand-spec



## DatContainer Interface
A `Dat` whose folder holds other dats: every folder below it carrying a spec file, found lazily and loaded through the container's own world. A child's `run/` sub-dat is not a child. Made and loaded like any dat, with `dat.kind` naming `DatContainer` or a subclass.

| DatContainer | |
| --- | --- |
| [get_dat_paths](#^get-dat-paths) | The full paths of the contained dats |
| [get_dats](#^get-dats) | The contained dats, loaded |

**get_dat_paths**`() -> List[str]`
    The absolute paths of every dat folder below this one, sorted, the container itself left out; computed on first call and kept. ^get-dat-paths

**get_dats**`() -> List[Dat]`
    The contained dats, each loaded through the container's manager, so each load is recorded inside a run. Computed on first call and held in memory until the container is released. ^get-dats



## Namespace Interface
A namespace of dotted names, bound to the `DatManager` whose world it names; not callable (running is `manager.run`). Every manager builds its own, reached as `manager.ns`; `Dat.ns` forwards to `Dat.manager.ns`. `Namespace(manager=None)` is the constructor: a bare `Namespace()` mounts, loads and names with no world, and its `manager` is `RuntimeError` until a manager built with `ns=` adopts it. A dotted name is a mounted name first, else exactly what `import` means in this environment, `getattr` below that.

| Namespace | |
| --- | --- |
| [manager](#^do-manager) | The world this namespace belongs to |
| [load](#^do-load) | The object a dotted name names |
| [name_of](#^name-of) | The dotted name that loads back to an object |
| [mounts](#^mounts) | The mount table, `{prefix: location}` |
| [mount](#^mount) | Add a folder, file, module or value to the namespace |

**manager**`: DatManager` (property)
    The manager this namespace belongs to; `RuntimeError` when it has none. ^do-manager

**load**`(dotted_name: str, *, default: Any = <required>, kind: Type | None = None) -> Any`
    The object `dotted_name` names: the longest mounted prefix first (values, modules, files, folders; a `.py`, `.yaml` or `.json` mount's contents as loaded, a string starting `yaml` parsed as YAML), else the longest importable prefix, imported, with `getattr` for the rest. Dict results are deep copies. With nothing found the `ImportError`, `AttributeError` or `KeyError` propagates unless `default` is given, which is also returned for a `None` result. `kind` makes a result of another type `TypeError`. ^do-load

**name_of**`(obj: Any) -> str` (static)
    The dotted `module.qualname` that `load` takes back to `obj`, a module, class or function; `ValueError` for an object with no importable name, such as a lambda or a function defined inside another. ^name-of

**mounts**`() -> Dict[str, str]`
    The mount table: each mounted prefix and where it loads from (a file, a folder entry, a module's import name); a `value` mount has no location and is not listed. ^mounts

**mount**`(*, folder: str | None = None, file: str | None = None, module: ModuleType | str | None = None, value: Any = None, at: str = "", relative_to: str = ".")`
    Mount exactly one of a `folder` of loadables (indexed by path under `at`, so `catalog/models/baseline` answers to `catalog.models.baseline`), a single `file`, a `module` (object, import name or path) or a literal `value`, at the dotted name `at`; folder and file paths join to `relative_to`. Mounts live in this namespace only. A mounted top-level name that Python can import from elsewhere is `ValueError`: a mount never shadows an import. See [Mounts](../mount-commands.md). ^mount



## dvc_dat Interface
`from dvc_dat import Dat, DatContainer, DatManager, Namespace` is the package's `__all__`; importing it reads no file. `dvc_dat.do` is the submodule, not the namespace: the default world's namespace is `Dat.ns`, or `from dvc_dat.do import do`. The module functions `expand`, `expand_spec` and `merge_dicts` are importable from `dvc_dat.core`. The ledger is its own subpackage, `dvc_dat.ledger`.

| dvc_dat | |
| --- | --- |
| [Dat](#^dat) | The folder that is its own recipe |
| [DatContainer](#^datcontainer) | A dat holding dats |
| [DatManager](#^datmanager) | A world of dats |
| [Namespace](#^namespace) | A namespace bound to a world |
| [__version__](#^--version--) | The package version |

**Dat**`(class)`
    From `dvc_dat.core`; see [Dat Interface](#Dat%20Interface). ^dat

**DatContainer**`(class)`
    From `dvc_dat.core`; see [DatContainer Interface](#DatContainer%20Interface). ^datcontainer

**DatManager**`(class)`
    From `dvc_dat.core`; see [DatManager Interface](#DatManager%20Interface). ^datmanager

**Namespace**`(class)`
    From `dvc_dat.do`; see [Namespace Interface](#Namespace%20Interface). ^namespace

**__version__**`: str`
    The package version, `"2.22.0"` at this checkout. ^--version--




# Dat Semantics

## The spec is the record
A dat's `_spec_.yaml` is the whole recipe, written once at create and never rewritten. `dat.base` is merged in and dropped, every `{}` reference is expanded with the same `now` and `unique` the folder got, and `dat.name` holds the path template, never the path it expanded to (F447 Q36), so the file on disk is a record of the recipe and the folder is the dat's name. Arguments never ride beside it: `Dat.manager.run(template, *args, **kwargs)` writes them into a new spec (`dat.args` replaced, `dat.kwargs` updated key by key), creates that dat, and runs it with none, so the arguments of every run are in the spec of the dat it produced. Handing an existing dat arguments forks a new one beside it and leaves the original untouched; there is no method that edits a spec, and a variation is `merge_dicts(d.get_spec(), {...})` passed to `create`.

| `dat` key | Holds |
| --- | --- |
| `kind` | The dotted class path the dat is built as |
| `base` | A spec, a name, or a list to inherit from; never stored |
| `name` | The path template; stored as the name the dat landed at |
| `do` | The dotted name of the function to run |
| `args`, `kwargs` | Its arguments, after the dat itself |
| `target_exists` | What create does when the folder is there |
| `standing` | A demand: `rolling` or `referenceable` |

| `target_exists` | When the folder exists |
| --- | --- |
| `error` (default) | `FileExistsError` |
| `use` | Return the existing dat, unrun |
| `overwrite` | Delete it and create afresh; refused on `{cwd}` |
| `increment` | Count up `_2`, `_3`, … until free |

A `{unique}` in the template increments whatever `target_exists` says. The `{}` grammar: an undotted name is a built-in (`YYYY YY MM DD HH mm SS now cwd unique`) or a key of `vars`; a dotted name resolves through `ns.load` and is called when it is a function or method; `{a.b(1, k=2)}` calls it with Python literals; `{{` and `}}` are literal braces. The full file format is [Spec Format](../spec-format.md).



## Sealing and the content hash
Every `save` writes `_result_.yaml` and stamps `dat.sha256`, the hash of the dat's content: the sha256 of sorted `relpath\0sha256` lines over every file in the folder except `run/`, with `_spec_.yaml` counted as its sorted-key YAML dump less `dat.name`, and `_result_.yaml` as its sorted-key dump with `dat.sha256` set to `excluded`, so the hash sits inside the file it covers. `dat.hash: functional` in the results names this rule; a results file without it is hashed with every file as its bytes. The name and the run are not content, so two runs of one recipe at two places hash the same when the code is functional, and a dat that hashes differently from its twin wrote something undeclared.

The save that counts seals the dat, after which `save` and a run refuse it. Inside the dat's own run a save is a checkpoint, written `open`, and asks for the seal, which the run performs when the function returns. A save anywhere else, a folder filled by hand or a run's results saved after it returned, seals at once and adds the dependency `$MANUAL: manual`. At the seal the dependency map keeps its roots only ([roots](#^roots)). `verify()`, and a load with `verify`, recompute the hash the same way: a changed data file, recipe or result fails it; a reformatted YAML file, a renamed dat or anything under `run/` does not.



## The run sub-dat
Every run replaces `run/` inside the dat with a fresh sub-dat, a minimal `_spec_.yaml` and a `_result_.yaml` holding the execution. It is written before the function starts and again after; it carries no `dat.sha256` and reads `dat.standing: sealed` once finished.

| Key in `run/_result_.yaml` | Written |
| --- | --- |
| `dat.run_at`, `dat.host`, `dat.pid` | before the function starts |
| `dat.code` | before; `{branch, commit, dirty}`, absent outside a checkout |
| `dat.run_time` | when the function returns, `HH:MM:SS.mmm` |
| `dat.content` | after the seal: the `dat.sha256` the run sealed |

`run/work/` is the run's scratch and its working directory, so a file the function writes without naming a place lands outside the dat's hash. A run is not content: nothing may depend on it, and a run loaded inside a recording is recorded `unsealed`.



## Standing
Every save stamps `dat.standing`, how far the dat can be relied on.

| Standing | Means |
| --- | --- |
| `rolling` | Saved again at will, never frozen; runs again, replacing `run/` |
| `open` | A checkpoint, or a seal over an open input: may still change |
| `sealed` | Frozen |
| `referenceable` | Frozen, from clean committed code and referenceable inputs |

A seal earns the least standing of its inputs, an input `rolling` counting as `sealed`, an artifact and `$MANUAL` as `referenceable`, an entry recorded `unsealed` as `open`; it is capped at `sealed` when the run's `dat.code` is dirty or absent. An input that was open keeps the dat `open` for good: its saves write and never freeze. In a spec `dat.standing` is a demand: `rolling` declares a dat that never freezes, and `referenceable` makes anything less an error, raised by the load of an input that is not referenceable, by the run before dirty or uncommitted code starts, and by a seal that would earn less. `standing(name)` reads it from the files without building anything.



## The manager is the world
A `DatManager` is a world: its dat folders, its artifact folder and index, and its `ns`. Everything the manager does goes through that `ns` and no other, and a dat remembers the manager that loaded it, so an instance's saves, loads and index writes stay in its world. `Dat.manager` is the default world: importing `dvc_dat` touches no file, the first read builds it with `load_dat_config()`, `Dat.create` and `Dat.load` go to it, and `Dat.ns` forwards to its `ns`. Replacing it is an assignment; mounts belong to the namespace they were made on, so a replacement that should keep them is built with `ns=Dat.ns`, which also makes it the default. A long-lived service that works away from where it launched assigns `Dat.manager` explicitly.



## Dependency capture
Inputs are captured, not declared. Inside `recording(dat)`, which a run opens around the function, every `load`, `load_path` and `save_artifact` lands in the dat's `dat.dependencies`, name to hash: a dat by its name and `dat.sha256`, or `unsealed` while it is open; an artifact by its name, or its URN when it has none, and its `sha256`. A nested run records its own inputs, and the outer run records the inner dat as one entry, by its final hash. An input that reached the run around the manager is recorded with `record_dependency`. The recording stack is a `contextvars` variable, so two runs on two threads or tasks never mix their maps. A run that loaded nothing records `{}`.



## Artifacts and the index
An artifact is a file or folder stored write-once in the artifact folder, under a name or under its URN only. A file lands at `<art_folder>/<name>/<basename>`, a folder's contents at `<art_folder>/<name>/` (`sha256/<hex>/` with no name), with the sidecar `_art_.yaml` beside them holding `type`, `names`, `payload`, `sha256`, `size` and `saved_at`. A file hashes as its bytes, a folder as the sorted `relpath\0sha256` lines of its files. A name is held once, with no overwrite and no increment, and never inside another artifact's folder; the same bytes saved under a second name gain that name and are not copied, and the same hash with a different size or type is `ValueError`. The type is what a load hands the payload's path to; with none the load returns the `Path`.

Dats and artifacts share one namespace and one index, `_index_.json`: every artifact name, every artifact URN, and each saved dat's current `dat.sha256`, to `{art: <folder>}` or `{dat: <name>}`. A name held by one is refused to the other, and a name found in both is `ValueError` on load. The index is written under a file lock through a temporary file and a rename, so it is never torn; a named artifact is found by its folder even when the index lacks it, and `reindex()` rebuilds the index from the folders. A dat loaded by URN must still hash to it, else `ValueError`.



## Configuration
`.datconfig.yaml` is found walking up from the working directory or `start`; an empty file is a complete config, and its folder is the project's import root, put first on `sys.path`. `.datconfig.override.yaml`, found the same way, wins over it, and the environment wins over both. An unknown key is `ValueError` naming the file and the known keys.

| Key | Means | Default |
| --- | --- | --- |
| `dat_folders` | One folder or a list; the first takes new dats | `data` |
| `art_folder` | The artifact folder, never nested with a dat folder | `art` |
| `index` | The index file | `_index_.json` in `art_folder` |
| `verify` | Re-hash every load | `false` |
| `manager` | The `DatManager` subclass to build, dotted | `DatManager` |
| `run` | The command `just run` hands its arguments to | none |
| `ledger` | The one ledger of a one-ledger project: a folder, or a Postgres DSN; read by `Ledger()` | none |
| `ledgers` | Named ledgers, `name: location`, and `default: name`, the active one; read by `ledgers` and `L` ([DAT Ledger § Many ledgers](ledger/DAT%20Ledger.md#Many%20ledgers)). Not with `ledger` | none |
| `mounts` | Prefix-to-folder mounts the ledger asserts as rows; read by `Ledger()` | none |
| `namespace` | `ledger`: the project's names are its active ledger's `db/mount` rows (`LedgerNamespace`, `Dat.ns.mount` refused). Implied by `ledger:`; a `ledgers:` section alone keeps the plain namespace ([DAT Ledger § Many ledgers](ledger/DAT%20Ledger.md#Many%20ledgers)) | `ledger` with `ledger:`, else plain |

`DAT_FOLDERS` replaces `dat_folders` with one folder (the value is not split) and `DAT_ART_FOLDER` replaces `art_folder`. `DAT_LEDGER` picks the active ledger: an entry of `ledgers:` by name, or a location. `ledgers: {default: <name>}` belongs in `.datconfig.override.yaml`, which a project keeps out of git, since whose ledger is active differs per checkout. `run` is read by the `run` recipe of `dvc_dat.just` only; see [Command Line](../cli.md). A `manager:` subclass may accept more keys by listing them in its `CONFIG_KEYS`.




# BRIEF
- Hand-written against `dvc_dat/core.py` and `dvc_dat/do.py` at 2.18.0; the code is the authority, and every name and signature here was read from it. The figure is hand-written SVG; edit it beside this page.
- [dat.md](dat.md) is the terse per-file list of the same surface and stays as it is; keep the two in step when the surface changes. `dvc_dat.ledger.Dat` is this class since 2.28.0 (DAT 1038); its value side is documented under [DAT Ledger](ledger/DAT%20Ledger.md).
- Block IDs: `Dat.ns` is `^dat-ns` and `DatManager.ns` `^datmanager-ns`, one page holding both; a prefix with the package name would carry an underscore, which breaks an Obsidian block link.
