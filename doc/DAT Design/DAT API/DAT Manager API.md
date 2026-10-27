---
description: "`DatManager`: the one object — folders, artifacts, recording, its `do`"
---
:>> [DAT](../../DAT%20Track/DAT.md) → [DAT Design](../DAT%20Design.md) → [DAT API](DAT%20API.md) → [DAT Manager API](ha://p/DAT%20Manager%20API) 
# DAT Manager API
A `DatManager` is one world: its dat folders, its artifact folder, its `do`, and the record of every run made there.

```python
from dvc_dat import Dat, DatManager

m = DatManager.load_dat_config()      # walks up for .datconfig.yaml
m = DatManager(dat_folders=["/work"])  # a world, nothing read
Dat.manager = m                       # now the default world

# the URN, 'sha256:9f3c…'; nothing registered first
m.save_artifact("/tmp/G1.mp4", type=VideoClip,
                name="games/G1/video")

def run(dat):
    # both loads land in dat.dependencies
    clip = dat.manager.load_artifact("games/G1/video")  # a VideoClip
    prev = dat.manager.load("runs/a")         # a Dat, as its kind
    ...

m.do("configs.bb.pure_ai")       # made, executed, recorded

class Store(DatManager):          # a store wraps every run
    def execute(self, dat):
        with self.index_run(dat):
            return super().execute(dat)

# replace the default world, keeping its mounts
Dat.manager = Store(dat_folders=["/work"], do=Dat.do)
```

## DatManager Interface
A world of dats and artifacts: a list of dat folders (all searched by name, the first written to), one artifact folder, a cache, and a `Do` bound to it. Every load and every run go through it, so a run's dependencies are whatever it loaded. `Dat.manager` is the default world, built from `.datconfig.yaml` on first use and replaced by assignment; others coexist. A subclass overrides `execute` to wrap every run.

| DatManager                                 |                                                      |
| ------------------------------------------ | ---------------------------------------------------- |
| [do](#^do)                               | This world's namespace and runner; its one attribute |
| [DatManager](#^init)                     | A world on a list of dat folders; reads nothing      |
| [load_dat_config](#^load-dat-config)     | A new manager from the nearest `.datconfig.yaml`     |
| [create](#^create)                       | Make a dat, as the class its `dat.kind` names        |
| [load](#^load)                           | A dat or an artifact, by name or `sha256:` URN       |
| [load_path](#^load-path)                 | Where `load` finds it, as a `Path`; builds nothing   |
| [standing](#^standing)                   | Rolling, open, sealed or referenceable, or None      |
| [save_artifact](#^save-artifact)         | Store a file or folder as an artifact; its URN       |
| [load_artifact](#^load-artifact)         | An artifact by name or URN; a dat's name refused     |
| [reindex](#^reindex)                     | Rebuild the index from the folders                   |
| [recording](#^recording)                 | Every load inside lands in `dat.dependencies`        |
| [record_dependency](#^record-dependency) | Add a dependency by hand while recording             |
| [execute](#^execute)                     | Run a dat; record its time, code and loads, unsaved  |
| [roots](#^roots)                         | A dependency map trimmed to its roots, as at a seal  |
| [code_of](#^code-of)                     | A function's branch, commit and dirty flag           |
| [exists](#^exists)                       | Is a dat or an artifact under this name or URN?      |
| [expand](#^expand)                       | The `{}` expander, through this `do`                 |
| [expand_spec](#^expand-spec)             | Merge `dat.base`, then `expand` every string         |

**do**`: Do`
    This world's namespace and runner; the only public attribute. `m.do.mount(...)` names things in it, `m.do(target, ...)` runs them here. ^do

**DatManager**`(*, dat_folders: list[str], art_folder: str | None = None, index: str | None = None, do: Do | None = None, verify: bool = False)`
    A world on a list of folders, searched in order and written at its head; keyword-only, and the list is required — a string or an empty list is `TypeError` / `ValueError`. Nothing is read from disk. `art_folder` is where artifacts live; with none, this world holds no artifacts and `save` raises `RuntimeError`. `index` is the store's index file, default `_index_.json` in the artifact folder, else in the first dat folder. It never nests with a dat folder, either way round — that is `ValueError`, since an artifact name and a dat name would collide. `do` adopts an existing namespace with its mounts; adopting the default world's makes this the default world. ^init

**load_dat_config**`(start: str | Path | None = None, *, do: Do | None = None) -> DatManager`
    Classmethod. A new manager from the `.datconfig.yaml` found walking up from `start` (default the working directory): the file, then `.datconfig.override.yaml`, then `DAT_*` env; relative folders resolve against the file's folder, which goes first on `sys.path`. No file found means the defaults under `start`. An unknown key is `ValueError`. `do` as in the constructor. ^load-dat-config

**create**`(spec: dict | str | None = None, *, path: str | None = None) -> Dat`
    Make a dat on disk and return it loaded, as the class its `dat.kind` names. A dotted `spec` is loaded through `do`; `dat.base` is merged; `path` is a template under the first dat folder, default `dat.name`, else `anonymous/Dat{unique}`. `FileExistsError` when the folder exists and `dat.target_exists` is `error`. ^create

**load**`(name: str | Path, *, cache_after_load: bool = True, verify: bool | None = None) -> Any`
    What a name or a `sha256:` URN names: a dat, as its `dat.kind` class, or an artifact, handed to the `type` recorded at its save (its payload's `Path` with none). A dat is tried absolute, then mounted in `do`, then in each dat folder in order; a name both a dat and an artifact hold is `ValueError`; an `art:` name written before 2.14 loads with the prefix stripped. Inside a `recording`, the entry lands in that dat's map. `KeyError` when nothing is found. `verify` (default the manager's, set by `verify=` or `verify:` in `.datconfig.yaml`) re-hashes what is handed back — the folder against `dat.sha256`, an artifact's payload against its `_art_.yaml` — and raises `ValueError` naming the name and both hashes on a mismatch; `load_path` takes it too. ^load

**load_path**`(name: str | Path) -> Path`
    Where `load(name)` finds its object — a dat's folder, or an artifact's payload — with nothing built: no type is called. For heavy objects and for tools that read the file themselves. Recorded on the running dat exactly as `load` records it. ^load-path

**save_artifact**`(source: str | Path, *, type: str | Callable | None = None, name: str | None = None, link: bool = False) -> str`
    Store a file or folder as an artifact and return its URN, `"sha256:<hex>"`. `type` is what `load` hands the payload's path to: a class or callable, recorded as its dotted name, or that name as a string — anything `do.load` resolves; one that cannot be imported is mounted, `do.mount(value=fn, at="video.clip")`, and named `type="video.clip"`. Nothing is registered. `name` is any relative path, held once, never overwritten; with none the artifact answers to its URN only. Bytes already stored get the new name as a second key and are not copied; an equal hash with a different size is `ValueError`. A name a dat holds is `FileExistsError`. `link` hard-links the payload instead of copying it (same filesystem). `Dat.save_artifact` forwards here. ^save-artifact

**load_artifact**`(name: str | Path, *, verify: bool | None = None) -> Any`
    The artifact under a name, an `art:` name or a URN, handed to its recorded type — its `Path` with none; recorded and verified as `load` does. A dat's name is `KeyError`; `load` takes either. `Dat.load_artifact` forwards here. ^load-artifact

**reindex**`() -> int`
    Rebuild the index from the folders — every artifact's names and URN from its sidecar, every saved dat's URN from its results — and return the number of keys. ^reindex

**recording**`(dat: Dat) -> ContextManager[None]`
    Every `load` inside the block lands in `dat.dependencies`. `execute` runs its function inside one; blocks nest, and an inner dat is one entry of the outer. ^recording

**record_dependency**`(name: str, sha256: str | None = None) -> None`
    An entry by hand, for what a run used without a `load`. Raises when nothing is recording. ^record-dependency

**execute**`(dat: Dat) -> Any`
    Run `dat.do` with the spec's args and kwargs inside `recording(dat)`, with a fresh `run/work/` as the working directory; record `dat.dependencies` in its results and `dat.run_at`, `dat.host`, `dat.pid`, `dat.code`, then `dat.run_time` and (after the seal) `dat.content` in the `run/` sub-dat, saving nothing — a `dat.save()` inside the function writes a checkpoint and seals it when the function returns; a sealed dat is `RuntimeError` (a rolling one runs again); a spec saying `dat.standing: referenceable` raises at the first load of an input that is not, and up front on dirty code or code outside a checkout; return the function's value (`dat` itself when the spec has no `dat.do`). Whatever the function raises propagates, with nothing recorded. Override to wrap every run. ^execute

**standing**`(name: str | Path | Dat) -> str | None`
    `rolling`, `open`, `sealed` or `referenceable`, read from `_spec_.yaml` and `_result_.yaml` without building anything; `None` when nothing is stored under the name or URN. An artifact is `referenceable`. A file written before 2.14 reads by the 2.13 rule: sealed with `dat.run_time` or `$MANUAL` and no `unsealed` entry, referenceable when stamped so, rolling when its spec says `dat.rolling: true`. ^standing

**roots**`(dependencies: dict) -> dict`
    The map less every entry some other entry's dat already lists among its own dependencies — the trim every seal applies. ^roots

**code_of**`(fn) -> dict | None`
    Static. `{branch, commit, dirty}` of the git checkout holding `fn`'s source, as a run records it in `dat.code`; `None` outside a checkout. ^code-of

**exists**`(name: str | Path) -> bool`
    A dat or an artifact is stored under `name` or the URN, resolved as `load` resolves it. ^exists

**expand**`(text: str, vars: dict | None = None) -> Any`
    The `{}` expander: built-ins, then `vars`, then a dotted name through this `do` — called when it is a function or method, and `{a.b(1, k=2)}` calls it with literal arguments; a class or callable object is not called without parentheses. A string that is one reference returns the object itself. ^expand

**expand_spec**`(spec: Any, vars: dict | None = None) -> Any`
    A copy of `spec` merged over its `dat.base` chain (a name, a spec, or a list of them, later entries winning, bases named through this `do`), recursively, with `dat.base` dropped, then with every string value expanded as `expand` does; keys are left alone. A spec that is not a dict has no bases and is only expanded. `create` stores what this returns, except `dat.name`. ^expand-spec




# DatManager Semantics

## The default world
`Dat.manager` is a plain class attribute: `None` until first use, when `DatManager.load_dat_config()` fills it; assign to it to replace the default world. `Dat.do` forwards to `Dat.manager.do`, whichever manager that is, so `do.mount` and `do(...)` always act on the default world. Mounts made before an assignment stay with the manager they were made on; to keep them, adopt the namespace: `Dat.manager = Store(dat_folders=[...], do=Dat.do)`. `cli_main(config=path)` does exactly that with `load_dat_config(path, do=Dat.do)`. A subclass's `Run.manager` is the same object; a dat built by hand with no manager falls back to it.

## The config file
`.datconfig.yaml`, overridden by `.datconfig.override.yaml`, then by `DAT_FOLDERS` / `DAT_ART_FOLDER`. A `manager:` key names the `DatManager` subclass `load_dat_config` builds (so the default world's class); the keys in that class's `CONFIG_KEYS` may appear too and reach its constructor, any other unknown key is an error. `load_dat_config` is its only reader in the library; `run` is read by `bin/dat` only (`DAT_RUN` overrides it there). An empty file is a complete config: it marks the project root.

```yaml
dat_folders: data/        # or a list; the first is written to
art_folder: art/          # beside data/, never inside (default)
index: art/_index_.json   # optional; the default
manager: mylab.store.Store  # optional: the class to build
run: .venv/bin/python -m mylab.main
```

## What a run records
`execute` records the dependency map in the dat's results, and the seal writes it to `_result_.yaml`, keeping the roots only. A dat entry carries its `dat.sha256`, the content hash its seal stamped (3.0: the folder but its `run/` sub-dat, and the spec but its `dat.name`) — `unsealed` for a dat still open, which keeps the run open; a save outside the run adds `$MANUAL: manual`; an artifact entry carries the sha256 from its `_art_.yaml`. The key is the dat's own name (`dat.get_path_name()`, relative to the dat folder holding it); a dat outside every dat folder records as its absolute path. A run with no loads records `{}`. The execution itself — clock, host, pid, code, and the hash it sealed — is the `run/` sub-dat's results, written as it goes; `run/work/` is the working directory while the code runs.

```yaml
# _result_.yaml
dat:
  dependencies:
    games/G1: "sha256:4b1e…"
    games/G1/video: "sha256:9f3c…"
  standing: referenceable
  hash: functional
  sha256: "sha256:7c0a…"
```

```yaml
# run/_result_.yaml
dat:
  run_at: '2026-09-23 10:02:11'
  host: gpu-7
  pid: 41218
  code: {branch: main, commit: 2268a74…, dirty: false}
  run_time: '00:00:04.120'
  standing: sealed
  content: "sha256:7c0a…"
```

A nested `do()` inside a run records its own loads, and the outer run records the inner dat as one entry, by its final hash. A load that reaches around the manager is not a dependency unless the run says so with `record_dependency`. `dat.code` is the checkout holding the source of the function `dat.do` names; outside a git checkout nothing is recorded. Anything that gathers a dat's inputs before its run captures into it the same way `execute` does:

```python
with m.recording(dat):
    cfg = m.load_artifact("assets/lock")   # recorded
```

## Artifacts on disk
`save_artifact(source, type=VideoClip, name="games/G1/video")` copies `source` to `<art_folder>/games/G1/video/` (`sha256/<hex>/` with no name) and writes `_art_.yaml` beside it: `type` (a dotted name or `null`), `names` (every name the bytes answer to), `payload` (a file's basename, or `.` for a folder), `sha256` (a file as its bytes, a folder as the sha256 of its sorted `relpath\0sha256` lines), `size`, `saved_at`. A 2.13 sidecar's `kind` and `art:` `name` still read; it has no type, so it loads as its `Path`.

## The index
One file, `_index_.json` in the artifact folder (`index:` in `.datconfig.yaml` or `DatManager(index=)` moves it), keys every artifact name and every `sha256:` URN — an artifact's, and each saved dat's current hash — to `{art: <folder>}` or `{dat: <name>}`: one namespace, reachable by either key. Every write takes a lock beside it and lands through a temporary file and a rename, so the index is never torn; a dat saved again drops its old URN, and `delete` / `move` keep it true. A named artifact's folder is found without it, so a store written before 2.14 loads by name as it stands; `reindex()` gives it its URNs. A subclass that keeps the index elsewhere — a database behind a remote store — overrides `_read_index` and `_index_update`.

## The class of a dat
The sidecar decides the class; the manager takes none.

- **Written** — `create` writes `dat.kind` as `module.qualname`: the spec's own `dat.kind`, else the class `Cls.create` was called on, else `dvc_dat.core.Dat`.
- **Read** — a dotted `dat.kind` is imported as pickle does; a class that cannot be imported is `ImportError`, one that is not a `Dat` is `TypeError`. A bare kind (pre-2.3) is looked up among loaded subclasses, else `Dat`.
- **Validated by that class** — `validate_spec` runs on the class `dat.kind` names, on create and on load.
- **Typed trampolines** — `Cls.load(name) -> Cls` raises `TypeError` unless the result is a `Cls`; `Cls.create` checks before anything is written.

# Changes

## 2.3 – 2.15

| Before (2.2) | After |
| --- | --- |
| `DatManager(config)`, `DataConfig.new(cwd=…)` | `DatManager(dat_folders=[…])`, `DatManager.load_dat_config(start)` |
| `manager.config`, `dat_folder`, `dat_folders`, `cwd` | gone; folders are private |
| `do.configure(source)`, `do.config` | assign `Dat.manager` |
| `.dataconfig.yaml` | `.datconfig.yaml`, plus `art_folder` |
| `manager.create(Dat, spec=…, path=…)` / `load(Dat, name, cwd=…)` | `create(spec=None, *, path=None)` / `load(name)`, class from `dat.kind` |
| `Do._run_dat(dat)`, private | `execute(dat)`, every run; records `dat.code` (2.3) and `dat.dependencies` (2.4) |
| — | 2.4: `save`, `register_artifact`, `recording`, `record_dependency`, `art:` names |
| — | 2.11: `load_path(name)`; `manager:` in `.datconfig.yaml` |
| `execute` saves the results | 2.12: it saves nothing; the dat's own `save()` seals |
| — | 2.13: `status`, `roots`, `code_of`, `verify`, `save(link=)`, `execute(referenceable=)` |
| `save(src, type, name)` | 2.15: `save_artifact(src, *, type=, name=)`, `load_artifact`, both on `Dat` too |
| `save(src, name)`, `register_artifact`, `status`, `execute(referenceable=)` | 2.14: `save(src, type=, name=)`, `standing`, `reindex`, `index=`; names or URNs everywhere |
| 2.4: `art/` under the first dat folder by default | 2.5: `art/` beside the config file; nesting is `ValueError`; a hand-built manager has none unless given |

# BRIEF
- 2026-09-23 — rewritten to the agreed 2.3 + 2.4 surface from the proposal module doc (now [DAT Manager API](DAT%20Manager%20API.md)) ([DAT 103](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^103); [DAT 1014](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^1014) part 1, [DAT 102](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^102) part 2), in Dan's module-doc member format (bold name + signature, 4-space-indented description). The 2.3 branch history (§ Changed from the branch, Q1–Q3 calls, § On main) was dropped: Q1 survives as the `dat.code` sentence, Q2–Q3 as § The class of a dat.
- 2026-09-23 — method block IDs bare on Dan's word; this format has none per member.
- 2026-09-22 — first written by DAT on Dan's ask for a page defining the manager, from `origin/manager-owns-do` at `3d8e1a0`.
