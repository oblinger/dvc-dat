---
description: "`from dvc_dat import Dat`: the `Dat` class, `Dat.do`, the spec file, the config"
---
:>> [DAT](../../DAT%20Track/DAT.md) → [DAT Design](../DAT%20Design.md) → [DAT API](DAT%20API.md) → [DAT Class API](ha://p/DAT%20Class%20API) 
# DAT Class API
The `Dat` class — what a run makes, and everything you can do with one.

```python
from dvc_dat import Dat

do = Dat.do   # the shortcut; follows Dat.manager
do("mymodule.train.baseline")       # 0.99 -- runs/2026-09/baseline
do("mymodule.train.baseline", lr=0.5)       # 0.95 -- a fork, run
d = Dat.load("runs/2026-09/baseline_2")     # the dat it made

d.get_path()           # '/.../data/runs/2026-09/baseline_2'
d.get_path_name()      # 'runs/2026-09/baseline_2'
d.get_spec()           # {'dat': {'name': 'runs/2026-09/baseline_2',..},
                       #  'notes': 'started 26-09-22_12-30-20'}
d.get_results()        # {'accuracy': 0.95, 'dat': {'dependencies': ..., ...}}
d.run.get_results()    # {'dat': {'run_at': ..., 'code': ..., ...}}  the run sub-dat

Dat.get(d, "dat.kwargs.lr")              # 0.5
Dat.get(d, "dat.kwargs.momentum", 0.9)   # 0.9 -- the default
r = d.get_results()
Dat.set(r, "metrics.f1", 0.91)           # makes 'metrics' on the way
Dat.set(r, "metrics.recall", 0.92)
d.save()                                 # by hand: seals, adds $MANUAL

c = d.copy("runs/2026-09/baseline_copy")     # same spec, new folder
m = c.move("runs/2026-09/baseline_moved")
m.delete()                                   # True

Dat.create(path="scratch/notes",             # no dat.do: a folder
           spec={"dat": {"kind": "Dat"}, "notes": "and a spec"})

box = Dat.create(path="experiments",
                 spec={"dat": {"kind": "DatContainer"}})
Dat.create(path="experiments/a", spec={"dat": {"kind": "Dat"}})
[x.get_path_name() for x in Dat.load("experiments").get_dats()]

class Run(Dat):                              # a kind with its own rules
    @classmethod
    def validate_spec(cls, spec):
        spec = super().validate_spec(spec)
        assert 0 < spec["dat"]["kwargs"]["lr"] < 1, "lr out of range"
        return spec

Run.create(path="scratch/run1",
           spec={"dat": {"kind": "Run", "kwargs": {"lr": 0.3}}})
type(Dat.load("scratch/run1"))               # Run -- by its dat.kind
Run.create(path="scratch/bad",
           spec={"dat": {"kind": "Run", "kwargs": {"lr": 5}}})
# AssertionError: lr out of range -- and no folder was made
```

Dats, specs, and the one call that runs them. The world they live in is [DAT Manager API](DAT%20Manager%20API.md); the namespace behind a dotted name is [DAT Do API](DAT%20Do%20API.md); nothing on this page needs either.



## Dat Interface
A folder holding `_spec_.yaml` — a complete, argumentless recipe, expanded once at create and never rewritten — and `_result_.yaml`, what running it produced. The class is chosen by the spec's `dat.kind`; subclass `Dat` to give a kind its own rules. `Dat(path)` is the dat already in a folder, its spec and results read from there, writing nothing; `create` makes one, `load` finds one by name.

Every dat is also a ledger value (DAT 1038): `Dat` subclasses `dvc_dat.ledger.Value`, so `seal`, `preds`, `subject`, `sealed` and `hash` are on every dat, and `dvc_dat.ledger.Dat` is this class. A saved dat seals with `dat.seal(t, name=...)`, its folder's files going to the ledger's art store and its `db/value` row naming `dat.kind`; `preds` default to the spec's scalar `dat.kwargs` and the results' scalar top-level entries; `L.at().do(spec)` is `Dat.do(spec)` remembered. The ledger side is [DAT Ledger § Dat Interface](../../DAT%20Modules/ledger/DAT%20Ledger.md#Dat%20Interface). Two words: a dat's *standing* (`sealed` by `save()`) is the dat world's; `dat.sealed` (a moment, or `None`) is the ledger's.

| Dat | |
| --- | --- |
| [manager](#^manager) | The default world on the class; its own on a dat |
| [do](#^do) | The default world's runner and namespace |
| [create](#^create) | Make a dat in the default world, typed to `cls` |
| [load](#^load) | Read a dat, typed to the class it is called on |
| [validate_spec](#^validate-spec) | The validation hook, on create and on load |
| [get_spec](#^get-spec) | The spec as written |
| [get_results](#^get-results) | The mutable results |
| [save](#^save) | Write results, hash, standing; the one that counts seals |
| [standing](#^standing) | Rolling, open, sealed or referenceable, from the files |
| [save_artifact](#^save-artifact) | Store a file or folder as an artifact, in the default world |
| [load_artifact](#^load-artifact) | An artifact by name or URN, built by its type |
| [verify](#^verify) | Is the folder still exactly as last saved? |
| [get_path](#^get-path) | The absolute folder |
| [get_path_name](#^get-path-name) | The folder relative to its dat folder |
| [delete](#^delete) | Remove the folder |
| [copy](#^copy) | The same spec in a new folder |
| [move](#^move) | Rename the folder |
| [get](#^get) | Dotted-key read into a dict tree or a spec |
| [set](#^set) | Dotted-key write, making mappings on the way |
| [merge_dicts](#^merge-dicts) | The merge `dat.base` uses |
| [cli_main](#^cli-main) | The `dat` command line, for your own main |
| seal, preds, subject, hash | A dat is a ledger `Value` ([DAT Ledger](../../DAT%20Modules/ledger/DAT%20Ledger.md#Value%20Interface)) |

**manager**`: DatManager`
    A plain class attribute: `None` until first use, when the getter builds the default world with `DatManager.load_dat_config()`. Assign a manager to replace the default world (`Dat.manager = Store(dat_folders=[...], do=Dat.do)` keeps the mounts). Every subclass sees the same object. `dat.manager` on an instance is the manager that loaded it, else this one — a run's function loads through `dat.manager`. ^manager

**do**`: Do`
    The default world's runner and namespace: a forwarder to `Dat.manager.do`, whichever manager that is when it is called. `Dat.do("x", lr=0.5)` runs; `Dat.do.mount(...)` and `Dat.do.load(...)` name things. `do = Dat.do` binds a shortcut that follows a later reassignment of `Dat.manager`. With no arguments a spec runs as written; with arguments it **forks** — `args` replace `dat.args`, `kwargs` update `dat.kwargs` key by key — and the forked spec creates the dat that runs ([Running](#Running)). ^do

**create**`(path: str | None = None, spec: dict | str | None = None) -> Dat`
    Classmethod. `Dat.manager.create(spec, path=path)`, typed: a `dat.kind` naming a class outside `cls` is `TypeError`, checked before any folder is made; with no `dat.kind`, the class it is called on is written. `spec` is a dict or a dotted name; `path` is a template under the first dat folder, default `dat.name`, else `anonymous/Dat{unique}`, with `dat.target_exists` settling a collision. ^create

**load**`(name_or_path: str | Path, *, cache_after_load: bool = True) -> Dat`
    Classmethod. `Dat.manager.load(name_or_path)`, as the class its `dat.kind` names; `TypeError` unless the result is an instance of `cls`. Tried absolute, then a mounted dat name, then each dat folder in order. Inside a run, recorded in its `dat.dependencies`. ^load

**validate_spec**`(spec: dict) -> dict`
    Classmethod, called on the class `dat.kind` names, on create and on load. Override it in a subclass; pydantic inside it is your choice and your dependency. Default: a mapping carrying a `dat` mapping, with `dat.kind` / `name` / `do` / `target_exists` strings. ^validate-spec

**get_spec**`() -> dict`
    The spec — the file as written, every `{}` in it expanded once when the dat was created. ^get-spec

**get_results**`() -> dict`
    The mutable results dict; `save` writes it. ^get-results

**save**`() -> None`
    Write `_result_.yaml`, stamping `dat.sha256` — the hash of every file in the folder but the `run/` sub-dat, `_spec_.yaml` counted as its sorted-key dump with `dat.name` left out and `_result_.yaml` as its sorted-key dump with `dat.sha256` set to `excluded` — and `dat.hash: functional`, the rule (a file without it hashes by the 2.x whole-folder rule). Every save also stamps `dat.standing`, what it earned. Inside the dat's own run it is a checkpoint (`open`) and asks for the seal, which comes when the run returns; anywhere else it seals at once and adds the dependency `$MANUAL: manual` — made or finished by hand, its dependencies incomplete. After the seal a second save is `RuntimeError`, and so is running the dat again. The seal trims the dependency map to its roots and earns the least standing of its inputs — a rolling one counts as sealed, an artifact and `$MANUAL` as referenceable — capped at `sealed` by a run's code that is dirty or outside a checkout; an input recorded `unsealed` keeps it `open` for good. A spec saying `dat.standing: rolling` saves and runs at will and never freezes; one saying `referenceable` makes a load of a lesser input, dirty code, or a seal that earns less a `RuntimeError`. Neither `create` nor a run saves. ^save

**standing**`(name: str | Path | Dat) -> str | None` (static)
    `Dat.manager.standing(name)`: `rolling` (saved at will, never frozen), `open` (may still change), `sealed` (frozen) or `referenceable` (frozen, from clean code and referenceable inputs), read from the files without building anything; `None` when nothing is stored under the name. An artifact is `referenceable`. ^standing

**save_artifact**`(source: str | Path, *, type: str | Callable | None = None, name: str | None = None, link: bool = False) -> str` (static)
    `Dat.manager.save_artifact(...)`: store a file or folder as an artifact and return its `sha256:` URN — [DAT Manager API](DAT%20Manager%20API.md) § save_artifact. Not `dat.save()`, which seals a dat. ^save-artifact

**load_artifact**`(name: str | Path, *, verify: bool | None = None) -> Any` (static)
    `Dat.manager.load_artifact(name)`: the artifact under a name or URN, handed to its recorded type — its `Path` with none. `Dat.load` stays a dat's: an artifact name there is `TypeError`. ^load-artifact

**verify**`() -> bool`
    Recompute the hash the same way and compare it with the stored `dat.sha256`: `True` while the content is exactly as last saved — a changed data file, recipe or result makes it `False`; reformatting the YAML, renaming the dat or anything under `run/` does not. A dat saved before 2.9 has no stored hash and returns `False`. ^verify

**get_path**`() -> str`
    The absolute folder. ^get-path

**get_path_name**`() -> str`
    The folder relative to the dat folder holding it — the dat's name; the absolute path when it lies outside every dat folder. ^get-path-name

**delete**`(*, must_exist: bool = True) -> bool`
    Remove the folder; `True` when removed. ^delete

**copy**`(new_path: str | Path, *, run: bool = True) -> Dat`
    The same spec in a new folder, loaded, same class; `run=False` leaves `run/` behind, which changes nothing about the copy's hash. ^copy

**run** → `Dat | None` (property)
    The run that made this dat: the sub-dat `run/`, whose results hold `dat.run_at`, `dat.run_time`, `dat.host`, `dat.pid`, `dat.code` and `dat.content` (the `dat.sha256` it sealed), and whose `work/` is the run's scratch. `None` for a dat filled by hand or written before 3.0. Not content: outside the hash, and nothing may depend on it. ^run

**move**`(new_path: str | Path) -> Dat`
    Rename the folder; returns the dat at its new path. ^move

**get**`(source: Dat | dict, keys: str | list[str], default: Any = …) -> Any`
    Staticmethod. Dotted-key read into a dict tree or a dat's spec: `Dat.get(d, "dat.kwargs.lr")`; `KeyError` without a default. ^get

**set**`(source: dict, keys: str | list[str], value: Any) -> None`
    Staticmethod. Dotted-key write, making mappings on the way: `Dat.set(r, "metrics.f1", 0.91)`. ^set

**merge_dicts**`(*dicts: dict, inplace: bool = False) -> dict`
    Staticmethod. Nested mappings key by key, later wins. Two lists of mappings that all carry a `name` merge by name: a later entry merges into its namesake, a new name appends, `{name: X, remove: true}` deletes. Anything else, any other list included, is replaced whole. A variation of a dat `d`: `Dat.create(spec=Dat.merge_dicts(d.get_spec(), {"dat": {"target_exists": "increment"}, …}))` — without `increment` it lands on `d`'s own `dat.name` and raises `FileExistsError`. ^merge-dicts

**cli_main**`(argv: list[str] | None = None, *, config: str | None = None) -> int`
    Staticmethod. The `dat` command line, for your own main: `run: python -m mypkg.main` in the config, and `sys.exit(Dat.cli_main())` when `DAT_CLI_CONFIG` is set. The bootstrap sets that one variable — the config file it found — for the program it launches; `cli_main` reads it and does `Dat.manager = DatManager.load_dat_config(config, do=Dat.do)`, so mounts your main made before the call survive. `argv` defaults to `sys.argv`; `config` hands the CLI a config from code; returns the exit status. ^cli-main



## DatContainer Interface
A dat whose folder holds dats.

| DatContainer | |
| --- | --- |
| [get_dat_paths](#^get-dat-paths) | Every dat folder under this one |
| [get_dats](#^get-dats) | Those dats, loaded in this container's world |

**get_dat_paths**`() -> list[str]`
    Every folder under this one holding a `_spec_` file, as names. ^get-dat-paths

**get_dats**`() -> list[Dat]`
    Those folders loaded, each as its `dat.kind` class, through this container's manager. ^get-dats



## dvc_dat Interface
`from dvc_dat import Dat, DatContainer, DatManager, Do` is the whole export; everything else hangs off those classes. `dvc_dat.__version__` is `"2.16.0"`.




# Dat Semantics

## Running

| `target` is … | With no `args`/`kwargs` | With `args`/`kwargs` |
| --- | --- | --- |
| a **callable** (or a name loading to one) | `target()` | `target(*args, **kwargs)` — a plain call, no dat |
| a **template spec** (dict, or a name loading to one) | create the dat, run it | fork, then the forked spec creates the dat, which runs |
| a **`Dat`** | re-run in place while open or rolling; refused once sealed | fork a new dat from its spec; the dat on disk is never rewritten |

`Dat.do` records nothing: a template makes a fresh folder every time. On a ledger, `rev.do(target, **kwargs)` takes the same targets (a template spec, its name, or a run function's dotted name) and remembers the answer: the dat made, run and sealed as a value once, then found ([DAT Ledger § do](../../DAT%20Modules/ledger/DAT%20Ledger.md#Rev%20Interface)).

A run is `Dat.manager.execute(dat)`: `fn(dat, *dat.args, **dat.kwargs)` with `fn` the object `dat.do` names, inside a recording, with `run/work/` as the working directory; `dat.dependencies` lands in the results beside whatever the function put in `dat.get_results()`, and reaches `_result_.yaml` when the dat is saved; `dat.run_at`, `dat.run_time`, `dat.host`, `dat.pid`, `dat.code` and `dat.content` are the run's, in the sub-dat `run/` (`dat.run`), outside the hash. **Nothing about arguments is recorded in the results — the spec is the record.** A template with no `dat.do` just creates the dat and returns it; `dat.target_exists: use` on an existing folder returns that dat without running. In-place iteration (profiling, a report you re-run): a fixed `dat.name` plus `dat.target_exists: overwrite`.



## Spec file — `_spec_.yaml`

A template, as a program or a `.yaml` under a mount writes it:

```yaml
dat:
  kind: Dat                    # the Dat subclass to load it as
  base: [mymodule.defaults]    # inherit from these; merged, dropped
  name: runs/{YYYY}-{MM}/base{unique}  # path under the dat folder
  do: mymodule.train.run       # the function that runs it
  args: []                     # its positional arguments
  kwargs: {epochs: 10, lr: 0.1}   # its keyword arguments
  target_exists: error         # error | use | overwrite | increment
notes: started {now}           # anything outside `dat` is yours
```

The file a dat holds is that template expanded once, at create — `name` is the folder it landed in, `{now}` the moment, `base` gone — and it is never rewritten.

| Key | Meaning |
| --- | --- |
| `dat.kind` | The `Dat` subclass, by dotted name (written `dvc_dat.core.Dat` by default); on a ledger, also the kind of the dat's `db/value` row |
| `dat.base` | What to inherit from: a name, a spec, or a list (later wins); removed once merged |
| `dat.name` | In a template: where to put the dat, under the dat folder, `{}` grammar (`runs/{YYYY}-{MM}/{unique}`). On disk: the folder it landed in |
| `dat.do` | Dotted name of the function to run |
| `dat.args` / `dat.kwargs` | Its positional and keyword arguments |
| `dat.target_exists` | `error` (default) · `use` · `overwrite` · `increment` |
| anything else | Yours; reach it with `dat.get_spec()` / `Dat.get(dat, "parameters.lr")` |

`_result_.yaml` holds `dat.dependencies`, `dat.standing`, `dat.hash`, `dat.sha256` and whatever the function stored; `run/_result_.yaml` holds `dat.run_at`, `dat.run_time`, `dat.host`, `dat.pid`, `dat.code`, `dat.content` ([DAT Manager API](DAT%20Manager%20API.md) § What a run records).



## Grammar — `{…}` in any template string

Expanded once, when the dat is created, with the same `now` and `unique` its folder got; the expanded values are what the file holds ([DAT 1009](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^1009) Q7).

| Form | Resolves to |
| --- | --- |
| `{YYYY} {YY} {MM} {DD} {HH} {mm} {SS} {now} {cwd} {unique}` | The built-ins (undotted names are reserved for them and for `vars`) |
| `{pkg.mod.NAME}` inside a longer string | `Dat.do.load("pkg.mod.NAME")`, which must be a string or a number — `"{cfg.root}/x"` concatenates |
| `"{pkg.CONFIG}"` as a whole value | The object itself, inlined as data — quote it in YAML, or the parser reads a mapping; a class or other object here is a `TypeError` at create |
| `{meta.commit}` naming a function or method | Called with no arguments; its value expands (2.16). A class or callable object is not called |
| `{meta.tag("v", n=2)}` | Called with those arguments — Python literals only, no `{` inside (2.16) |
| `{{` `}}` | Literal braces |
| `{anything_else}` | `KeyError` naming the reference and the built-ins — a stray brace never passes silently |



## Configuration — `.datconfig.yaml`

| Key | Meaning |
| --- | --- |
| `dat_folders` | Where dats live: one folder, or a list — the first is where new dats are created, all are searched by name (default `data/`, relative to the config file) |
| `art_folder` | Where artifacts live (default `art/` beside the config file); never inside a dat folder, nor one inside it — [DAT Manager API](DAT%20Manager%20API.md) § Artifacts on disk |
| `verify` | Optional, `true`: every load re-hashes and refuses a mismatch — [DAT Manager API](DAT%20Manager%20API.md) § load |
| `manager` | Optional: the `DatManager` subclass to build, dotted; its `CONFIG_KEYS` may appear as keys too — [DAT Manager API](DAT%20Manager%20API.md) § The config file |
| `run` | Optional. The command a copy of `bin/dat` hands its arguments to — `uv run dat`, or your program's own main when it mounts names ([DAT Do API](DAT%20Do%20API.md)); default `.venv/bin/python -m dvc_dat` beside the config, else `python3 -m dvc_dat` |

`DatManager.load_dat_config(start)` walks up from `start` (default the working directory); `.datconfig.override.yaml` wins over it; `DAT_FOLDERS` / `DAT_ART_FOLDER` in the environment win over both (`DAT_RUN` overrides `run`, in `bin/dat` only). The bootstrap hands its child the file it found as `DAT_CLI_CONFIG`, which `cli_main()` alone reads. An unknown key is an error.

**You never configure anything.** `import dvc_dat` reads no filesystem; the first use of `Dat.manager` — `Dat.do(…)`, `Dat.load(…)`, `Dat.create(…)` — builds the default world from the working directory, and the config folder goes first on `sys.path`, so the project's own modules resolve from any directory, installed or not. An empty `.datconfig.yaml` is a complete config: it marks the project root, `data/` is the dat folder, and dotted names mean what `import` means. A different world is one assignment: `Dat.manager = DatManager.load_dat_config(path, do=dat.do)` ([DAT Manager API](DAT%20Manager%20API.md) § The default world).




# Changes

## 2.3 – 2.15

| Before (2.2) | After |
| --- | --- |
| `Dat.manager`, a read-only class property | a plain class attribute: assign to replace the default world |
| — | `dat.manager` on an instance: the world that loaded it |
| `Dat.load(name, cwd=…)` | `Dat.load(name)`; `cwd` gone |
| `dat.kind: Run`, found by walking subclasses | `dat.kind: mylab.runs.Run`, imported; a bare name still reads |
| `Run.load(name)` raises `ValueError` on another kind | raises `TypeError` unless the dat is a `Run` |
| `DataConfig`, `.dataconfig.yaml` | `DatManager.load_dat_config`, `.datconfig.yaml` |
| `_result_.yaml`: `run_at`, `run_time` | also `code` (2.3) and `dependencies` (2.4) |
| every run saves; `save()` rewrites | 2.12: a run saves nothing; `save()` seals once; `$MANUAL`, `unsealed` |
| 2.12: `dat.sealed` | 2.13: `Dat.status(name)`; `dat.rolling`, `dat.referenceable`; every save stamps the hash |
| 2.13: `Dat.status`, `dat.rolling`, `dat.referenceable` | 2.14: `Dat.standing(name)`; one key, `dat.standing` |
| `_result_.yaml`: `run_at`, `run_time`, `code` | 3.0: in the `run/` sub-dat (`dat.run`); `dat.sha256` is the content hash, `run/` and the name left out, `dat.hash: functional` |
| `Dat.manager.save(...)` / `load(...)` for artifacts | 2.15: `Dat.save_artifact` / `Dat.load_artifact` |
| `cli_main(config=DataConfig)` | `cli_main(config=folder_or_file)` |
| `dvc_dat.do`, `cli_main`, `merge_dicts`, `expand` | `Dat.do`, `Dat.cli_main`, `Dat.merge_dicts`, `Dat.manager.expand` (2.8) |




# BRIEF
- 2026-09-23 — rewritten to the 2.3 + 2.4 surface ([DAT 103](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^103)) in Dan's module-doc member format: `Dat` and `DatContainer` as module docs, module functions as their own table; `DataConfig` removed; `Dat.load` lost `cwd`; `Dat.manager` a plain assignable class attribute; config renamed `.datconfig.yaml` with `art_folder`. The old § Dats on disk / One dat / Strings and configuration were folded into the member blocks; § Running, § Spec file, § Grammar, § Configuration kept as reference. Decided on [DAT 1008](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^1008), [DAT 1009](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^1009), [DAT 1014](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^1014), [DAT 102](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^102).
