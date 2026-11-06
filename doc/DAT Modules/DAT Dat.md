---
description: "`Dat`, `DatManager`, `DatContainer`, `Namespace`: the folder that is its own recipe, and the world that makes, loads, runs and seals it. Source: `dvc_dat/core.py`, `dvc_dat/do.py`."
---
:>> [DAT](../DAT%20Track/DAT.md) → [DAT Dat](ha://p/DAT%20Dat) 
# DAT Dat
A dat is a folder whose `_spec_.yaml` is a complete, argumentless recipe for itself and whose `_result_.yaml` holds what running it produced, sealed under a content hash.

![DAT Dat](DAT%20Dat.svg) 

api:: [`dvc_dat.core`](../api/core.md) and [`dvc_dat.do`](../api/do.md) — the classes and functions, rendered from the docstrings

**Classes:** [Dat](#Dat%20Interface) · [DatManager](#DatManager%20Interface) · [DatContainer](#DatContainer%20Interface) · [Namespace](#Namespace%20Interface) · [module functions](#dvc_dat%20Interface) 

*The spec is the record* is the topic that governs the Namespace node (arguments fork a new spec; they never ride beside one); the other topics annotate the nodes they govern.

This page covers the dat half of `dvc_dat`: `Dat`, `DatManager` and `DatContainer` in `dvc_dat/core.py`, `Namespace` in `dvc_dat/do.py`, and the package's exports; the figure above is the heart. The history half, the ledger, has its own module doc, [DAT Ledger](ledger/DAT%20Ledger.md); the spec file is [Spec Format](../spec-format.md) and the command line [Command Line](../cli.md).



## Dat Interface
A folder of data described by its `_spec_.yaml`, held in memory as the spec as written, the mutable results, and the path. A dat is made by `Dat.create` or `DatManager.create` and read by `Dat.load` or `DatManager.load`; `Dat(path, spec, result)` is the constructor those call, and `Dat(path)` alone is the dat already in that folder, its spec and results read from there (`{}` each when absent). A dat is also a ledger value, one class (DAT 1038): `Dat` subclasses `dvc_dat.ledger.Value` and carries the folder codec, so `seal`, `preds`, `subject`, `sealed` and `hash` are on every dat; its bytes are the folder's manifest, its preds default to the spec's scalar `dat.kwargs` and the results' scalar top-level entries, and a dat seals as a value once saved ([DAT Ledger § Dat Interface](ledger/DAT%20Ledger.md#Dat%20Interface)). Subclasses are the dat's kinds: `dat.kind` in the spec names one, and a subclass overrides `validate_spec` to check its own fields. The class-level members act on the default world, `Dat.manager`; an instance acts on the manager that loaded it.

<!-- methods: dvc_dat.core.Dat -->

## DatManager Interface
A world of dats: the dat folders searched by name (the first is where new dats are made), the artifact folder beside them, the index of names and URNs, and an `ns` namespace that names things; `run` runs dats, specs and callables. Every dotted spec, `dat.base`, `{}` expansion, path lookup and run goes through the manager's `ns`, so every load inside a run passes through the manager and is recorded. Any number of managers coexist; `Dat.manager` is the default one. `run` is fixed; a subclass that overrides the private `_execute` and calls `super()` wraps every run in its world.

<!-- methods: dvc_dat.core.DatManager -->

## DatContainer Interface
A `Dat` whose folder holds other dats: every folder below it carrying a spec file, found lazily and loaded through the container's own world. A child's `run/` sub-dat is not a child. Made and loaded like any dat, with `dat.kind` naming `DatContainer` or a subclass.

<!-- methods: dvc_dat.core.DatContainer -->

## Namespace Interface
A namespace of dotted names, bound to the `DatManager` whose world it names; not callable (running is `manager.run`). Every manager builds its own, reached as `manager.ns`; `Dat.ns` forwards to `Dat.manager.ns`. `Namespace(manager=None)` is the constructor: a bare `Namespace()` mounts, loads and names with no world, and its `manager` is `RuntimeError` until a manager built with `ns=` adopts it. A dotted name is a mounted name first, else exactly what `import` means in this environment, `getattr` below that.

<!-- methods: dvc_dat.do.Namespace -->

## dvc_dat Interface
`from dvc_dat import Dat, DatContainer, DatManager, Namespace, L, ledgers` is the package's `__all__`; importing it reads no file. `dvc_dat.do` is the submodule, not the namespace: the default world's namespace is `Dat.ns`, or `dvc_dat.do.ns`. The module function `merge_dicts` is importable from `dvc_dat.core`; the `{}` grammar is a namespace's, `ns.expand`, `ns.expand_spec`, `ns.quote_spec` ([Expansion](../expand.md)). The ledger is its own subpackage, `dvc_dat.ledger`.

| dvc_dat | |
| --- | --- |
| [Dat](../api/core.md#dvc_dat.core.Dat) | The folder that is its own recipe |
| [DatContainer](../api/core.md#dvc_dat.core.DatContainer) | A dat holding dats |
| [DatManager](../api/core.md#dvc_dat.core.DatManager) | A world of dats |
| [Namespace](../api/do.md#dvc_dat.do.Namespace) | A namespace bound to a world |
| [L](../api/ledger.md#dvc_dat.ledger.named) | The active ledger |
| [ledgers](../api/ledger.md#dvc_dat.ledger.named.Ledgers) | The project's ledgers by name |
| `__version__` | The package version |

# Dat Semantics

## The spec is the record
A dat's `_spec_.yaml` is the whole recipe, written once at create and never rewritten. `dat.base` is merged in and dropped, every `{}` reference is expanded with the same `now` and `unique` the folder got, and `dat.name` holds the path template, never the path it expanded to (F447 Q36), so the file on disk is a record of the recipe and the folder is the dat's name. Arguments never ride beside it: `Dat.manager.run(template, *args, **kwargs)` writes them into a new spec (`dat.args` replaced, `dat.kwargs` updated key by key), creates that dat, and runs it with none, so the arguments of every run are in the spec of the dat it produced; `Dat.create(template, **kwargs)` writes them the same way and runs nothing. A dat runs once, when it is made; `Dat.manager.run(d.get_spec(), **kwargs)` runs its recipe again as a new dat. There is no method that edits a spec, and a variation is `merge_dicts(d.get_spec(), {...})` passed to `create`.

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
Every `save` writes `_result_.yaml` and stamps `dat.sha256`, the hash of the dat's content: the sha256 of sorted `relpath\0sha256` lines over every file in the folder except `run/`, with `_spec_.yaml` counted as its sorted-key YAML dump less `dat.name`, and `_result_.yaml` as its sorted-key dump with `dat.sha256` set to `excluded`, so the hash sits inside the file it covers. `dat.hash: functional` in the results names this rule, the only one; a hash a 2.x save stamped does not verify. The name and the run are not content, so two runs of one recipe at two places hash the same when the code is functional, and a dat that hashes differently from its twin wrote something undeclared.

The save that counts seals the dat, after which `save` and a run refuse it. Inside the dat's own run a save is a checkpoint, written `open`, and asks for the seal, which the run performs when the function returns. A save anywhere else, a folder filled by hand or a run's results saved after it returned, seals at once and adds the dependency `$MANUAL: manual`. At the seal the dependency map keeps its roots only ([roots](../api/core.md#dvc_dat.core.DatManager.roots)). `verify()`, and a load with `verify`, recompute the hash the same way: a changed data file, recipe or result fails it; a reformatted YAML file, a renamed dat or anything under `run/` does not.



## The run sub-dat
Every run replaces `run/` inside the dat with a fresh sub-dat, a minimal `_spec_.yaml` and a `_result_.yaml` holding the execution. It is written before the function starts and again after; it carries no `dat.sha256` and reads `dat.standing: sealed` once finished.

| Key in `run/_result_.yaml` | Written |
| --- | --- |
| `dat.run_at`, `dat.host`, `dat.pid` | before the function starts |
| `dat.code` | before; `{branch, commit, dirty}`, absent outside a checkout |
| `dat.run_rev` | before, on a ledger: `<ledger>@<rev>`, the revision it ran against (`dat.at` is that `Rev`) |
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




## Invariants
- The spec on disk is a record: every `{}` is expanded once at create, except `dat.name`, which keeps the path template (never the path it expanded to), and call-site arguments go into a new spec.
- A sealed (or referenceable) dat is never rewritten: `save` and `run` refuse it.
- `dat.sha256` hashes the folder without `run/`; a run is not content.
- Standing is the least of the inputs', capped at `sealed` by dirty code or code outside a checkout.
- Dats and artifacts share one namespace and one index.

# BRIEF
- Hand-written against `dvc_dat/core.py` and `dvc_dat/do.py` at 2.18.0; the code is the authority, and every name and signature here was read from it. The figure is hand-written SVG; edit it beside this page.
- Each member's contract is its docstring; the tables here are generated from them (246). `dvc_dat.ledger.Dat` is this class since 2.28.0 (DAT 1038); its value side is documented under [DAT Ledger](ledger/DAT%20Ledger.md).
