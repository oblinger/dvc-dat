# Core Concepts

A **dat** is a folder whose `_spec_.yaml` is a complete, argumentless recipe for
itself. `_result_.yaml` holds only what running it produced.

`dvc_dat` has one namespace and one runner, both reached through `do`:

```python
from dvc_dat import Dat

do = Dat.do   # the shortcut; follows Dat.manager

# a dotted name -> a Python object; the first call builds
# Dat.manager from the nearest .datconfig.yaml
template = do.load("catalog.experiment")

# fork the template, run the fork
result = do("catalog.experiment", epochs=200)

# a path -> the dat on disk
dat = Dat.load("runs/2026-09/exp")
```

## Two kinds of name

**Dotted names** (`catalog.experiment`, `os.path.join`) name source code:
templates, functions, constants. `do.load` resolves them — first against the
names the program mounted with `do.mount(...)` (in code; `.datconfig.yaml`
holds no mounts), then by import: the longest importable
prefix of the name is imported and the rest is `getattr`-ed. So any importable
object has a name whether or not it was mounted, and `do.name_of(obj)` gives the
name that loads back to it.

**Slash paths** (`runs/experiment1`) name dat folders. They are relative to
the dat folder (`dat_folders`, default `data/`) or absolute. `Dat.load(name)`
opens one.

## Arguments fork a spec; they never ride beside it

`do(template, *args, **kwargs)` does not pass the arguments to a function. It
writes them into a *new* spec — keyword arguments update `dat.kwargs` key by
key, positional arguments replace `dat.args` — creates the dat that spec
describes, and then runs that dat with no call-site arguments at all:

```python
do("catalog.experiment", 3, epochs=200)

# the new dat's _spec_.yaml carries
#   dat: {args: [3], kwargs: {epochs: 200}}
# and the run is
#   experiment(dat, 3, epochs=200)
```

The consequence is the point: **the spec is the record.** Nothing about the
arguments goes into `_result_.yaml`, and no sealed dat is ever rewritten by a
run. Handing a dat arguments forks a new one and leaves the original
byte-identical; `do(dat)` with none re-runs it in place while it is open.

## The seal

A run saves nothing by itself. Every `dat.save()` writes `_result_.yaml` and
stamps `dat.sha256`, the hash of the whole folder as it stands; the save that
counts **seals** the dat, after which a second `save()` and any later run of it
are refused. Inside the dat's own run a save is a checkpoint — a crash leaves
something readable — and asks for the seal, which comes when the run returns,
with the whole record. A save anywhere else — a data folder filled by hand, or
a run's results saved after it returned — seals at once and adds the
dependency `$MANUAL`: well defined, but what it was made from is not fully
recorded. At the seal the dependency map keeps its roots only: an entry that
another entry already depends on is dropped.

## Standing

Every save stamps **`dat.standing`**, how far the dat can be relied on:

| Standing | Means |
|----------|-------|
| `rolling` | saved again at will, never frozen — a game whose annotations get corrected |
| `open` | a checkpoint, or a run that read an open dat: may still change |
| `sealed` | frozen |
| `referenceable` | frozen, made by clean committed code from referenceable inputs only |

The seal earns the least standing of its inputs — a rolling input counts as
sealed, an artifact and a hand seal's `$MANUAL` as referenceable — capped at
`sealed` when a run's code was dirty or outside a git checkout. An input that
was open is recorded `unsealed` and keeps the run open for good: its `save()`
writes, never seals. `Dat.standing(name)` reads it from the files without
building anything; `None` means nothing is stored under the name.

In a spec, `dat.standing` is a demand. `rolling` declares a dat that never
freezes (the spec never changes, so neither does the declaration).
`referenceable` makes anything less an error: a load of an input that is not
referenceable raises there, dirty code raises before the run starts, and a
seal that would earn less raises instead of writing. With no `dat.standing`
the dat takes what it earns. Outside a run anything loads.

**The verifying load.** `load(name, verify=True)` (or `verify: true` in
`.datconfig.yaml`, or `DatManager(..., verify=True)`) re-hashes what it hands
back and raises when the bytes are not the ones sealed — for storage that can
corrupt or transfer a folder.

**A created dat's spec never changes.** There is no method that rewrites
`_spec_.yaml`. To try a variation, make a new dat from an edited copy of the
spec. `merge_dicts` is the same zipper merge `dat.base` uses:

```python
from dvc_dat import Dat

do, merge_dicts = Dat.do, Dat.merge_dicts

# d's dat.name is the folder it landed in; increment lands beside it
spec = merge_dicts(d.get_spec(),
                   {"dat": {"target_exists": "increment"},
                    "run_template": {"lr": 0.01}})
Dat.create(spec=spec)
```

Edit the dict *before* instantiating whenever you can: `do.load` a template,
change it, then `Dat.create` it. There is no `fork` method; a consumer that
wants one defines it over `merge_dicts`.

For in-place iteration — profiling, report tuning, a `dev` dat you squash every
run — give the spec a fixed `dat.name` and `target_exists: overwrite`. The
running code then has to cope with output files that already exist.

## Nothing is found by the shape of its path

A dat's location carries no meaning the library relies on. Metadata lives in the
spec and in the results, and a consumer finds dats by querying their contents,
never by parsing a path.

## The manager is the world; `Dat.manager` is the default one

A **world** is a `DatManager`: a list of dat folders and the namespace that
names things in them. A manager owns its `do` — a `Do` bound to it, carrying
its mounts, its `load` and its runner — and everything the manager does (a
dotted spec, `dat.base`, `{}` expansion, resolving a name to a folder, every
run) goes through that `do` and no other. `do` is the manager's only public
attribute; its folders are its own business.

```python
from dvc_dat import Dat, DatManager

# a world on a list of folders; nothing is read from disk
m = DatManager(dat_folders=["/work/dats"])
m.do.mount(folder="catalog", at="catalog", relative_to=root)
m.do("catalog.experiment", lr=0.5)   # created and run inside m
m.load("runs/experiment1")           # searched in m's folders
m.expand_spec(spec)                  # {} through m's namespace
```

The constructor is keyword-only and `dat_folders` is a required list: all are
searched by name, in order, and the first is where new dats are made. A
string is a `TypeError`.

`DatManager.load_dat_config(start=None)` is the other way to build one: it
walks up from `start` (default the working directory) to the nearest
`.datconfig.yaml`, resolves its folders against the file's folder, puts that
folder first on `sys.path`, and returns a new manager.

**`Dat.manager` is the process's default world** — a plain class attribute.
`import dvc_dat` touches no filesystem; the first read of `Dat.manager` (a
`do(...)`, a `Dat.load`, any use at all) fills it with
`DatManager.load_dat_config()`. `Dat.create` / `Dat.load` trampoline to it,
every subclass shares it (`Run.manager is Dat.manager`), and the
module-level `do` forwards to `Dat.manager.do`, whichever manager that is.
Nothing in an ordinary program configures anything:

```python
from dvc_dat import Dat

do = Dat.do

# finds .datconfig.yaml on the way
do("mypkg.train.baseline", lr=0.5)
```

To replace the default world, assign it. Mounts belong to the namespace
they were made on, so a replacement that should keep them adopts the
default `do`, which also makes it the default:

```python
from dvc_dat import Dat, DatManager

do = Dat.do

Dat.manager = DatManager.load_dat_config(project_root, do=do)
Dat.manager = Store(dat_folders=["/work"], do=do)   # a subclass
```

A manager takes no class: `m.create(spec)` and `m.load(name)` build the class
the spec's `dat.kind` names. `Run.load(name)` and `Run.create(...)` are the
typed forms on the default world — the result is a `Run`, or a `TypeError`.

Every run in a world goes through `m.execute(dat)`: `m.do(...)`, and each
`do(...)` a running function makes, land there. A subclass of `DatManager`
that overrides `execute` and calls `super().execute(dat)` wraps every run.

A bare `Do()` is a namespace with no world: it mounts and loads, and a
manager built with `do=` adopts it; running anything in it before then is a
`RuntimeError`.

The `dat` command-line tool needs no special handling (see
[Command Line](cli.md)); a long-lived service that starts in one directory
and works in another should assign `Dat.manager` explicitly rather than
depend on where the process happened to launch.

## Artifacts

An **artifact** is a file or folder stored in the manager's artifact folder —
hashed, write-once, with a `_art_.yaml` sidecar beside it (`type`, `names`,
`payload`, `sha256`, `size`, `saved_at`). A file is hashed as its bytes, a
folder as the sorted `relpath\0sha256` lines of its files.

```python
# returns the URN, "sha256:9f3c..."
urn = m.save("/tmp/G1.mp4", VideoClip, "games/G1/video")
clip = m.load("games/G1/video")    # VideoClip(path)
clip = m.load(urn)                 # the same artifact, by its URN
# no type, no name: it loads as a Path, by its URN only
m.save("/tmp/lock.json")
```

`save(source, type=None, name=None, *, link=False)` returns the artifact's
URN, `sha256:<hex>`. **The type** is what `load` hands the payload's path
to: a class or callable, recorded by its dotted name, or that name as a
string — anything `do.load` resolves. A factory that cannot be imported (a
lambda, a closure) is mounted once, `m.do.mount(value=fn, at="video.clip")`,
and named `type="video.clip"`. With no type, `load` returns the `Path`.
Nothing is registered. **The name** is any relative path, and carries no
type; changing what a thing is never means renaming it. A name is held once
— an existing one is `FileExistsError`, with no overwrite and no increment.
With no name the artifact answers to its URN only.

A file lands at `<art_folder>/<name>/<basename>`, a folder's contents at
`<art_folder>/<name>/` (`sha256/<hex>/` with no name). **Bytes already stored
are not stored again**: saving them under a new name adds that name as a
second key and copies nothing; the same hash with a different byte size is
refused. `load_path(name)` returns the payload's path — or a dat's folder —
and builds nothing, recorded like a `load`.

**One namespace, one index.** Dats and artifacts share one namespace: a name
held by one is refused to the other, and a name found in both is a
`ValueError`. `load`, `load_path`, `exists` and `standing` take a name or a
URN. The store keeps one index file, `_index_.json` in the artifact folder
(`index:` in `.datconfig.yaml` moves it), keyed by every artifact name and
every `sha256:` URN — an artifact's, and each saved dat's current hash. It is
written through a lock and a rename, so it is never torn; `m.reindex()`
rebuilds it from the folders. A named artifact's folder is found without it,
so a store written before 2.14 loads by name as it stands, and `art:` names
written then still load, the prefix stripped.

The artifact folder is `art_folder:` in `.datconfig.yaml`, else `art/`
beside the config file — a sibling of `data/`. The artifact folder and the
dat folders never nest (that is a `ValueError`). A `DatManager` built by hand
with no `art_folder` holds no artifacts: `save` raises `RuntimeError`, and
its index lives in the first dat folder.

## Dependencies by capture

Every load goes through a manager, so a run's inputs are whatever it
loaded. `execute` runs the function inside `m.recording(dat)`, and every
`load` (and `save`) inside that block lands in `dat.dependencies` in
`_result_.yaml`, name to hash. A dat's hash is its `dat.sha256`, the
content hash its seal stamps over the whole folder — `unsealed` for a dat
still open — and `dat.verify()` tells you whether an input is still exactly
what the run saw. A nested `do()` records its own loads, and
the outer run records the inner dat as one entry, by its final hash. A load that reaches
around the manager is not a dependency unless the run says so:

```python
m.record_dependency("https://example.com/weights", "sha256:...")

# the same capture outside a run -- a builder gathering a dat's inputs
with m.recording(dat):
    cfg = m.load("assets/lock")          # recorded in dat
```

Recording is per thread and per task (a `contextvars` stack), so two runs
at once never mix their maps.

## Templates: `dat.base`

`dat.base` names a spec to inherit from — or a **list** of them, merged left to
right with later entries winning, so a dat can inherit from a DAG of specs.
Lists of named entries (`stages: [{name: detect, …}, …]`) merge by `name`,
so a child names only the entries it changes, adds or removes
(`{name: X, remove: true}`); see [Spec Format](spec-format.md).
Resolution is recursive and happens before the spec is written, so `dat.base`
never appears in a stored spec: what is on disk is the whole recipe.

## References: the `{}` grammar

Any string in a spec may carry `{…}` references. `Dat.create` expands them
once, with the same `now` and `unique` the folder got, and writes the result:
`get_spec()` returns the stored values, and nothing is expanded on read.

```python
from dvc_dat import Dat

expand = Dat.manager.expand

# 'runs/2026-09/exp'
expand("runs/{YYYY}-{MM}/exp")

# the object do.load('svp.CONFIG') returns
expand("{svp.CONFIG}")
```

- an **undotted** name is a built-in (`YYYY YY MM DD HH mm SS now cwd unique`)
  or a key of the `vars` dict you pass; anything else is a `KeyError`
- a **dotted** name resolves through `do.load`, at create
- `{{` and `}}` are the literal braces
- a string that is *exactly* one reference returns the referenced **object**;
  otherwise references are substituted as text

In YAML, a value that *begins* with `{` must be quoted — `name: "{svp.CONFIG}"`
— or YAML reads it as a flow mapping and the spec arrives with a dict where a
string belongs. `validate_spec` names that case.

## Validation

`Dat.validate_spec(cls, spec) -> spec` is a classmethod hook called by both
`create` and `load`, on the class the spec names. The default checks the shape
every dat relies on. A subclass overrides it to check its own:

```python
class Experiment(Dat):
    @classmethod
    def validate_spec(cls, spec):
        spec = super().validate_spec(spec)
        Model(**spec)   # your schema library, your dependency
        return spec
```

The library itself validates with no schema library at all.

## Configuration: `.datconfig.yaml`

```yaml
# where dats live: one folder, or a list -- the first is where new dats
# are created, all are searched when a dat is loaded by name
dat_folders: data

# where artifacts live, beside the dat folder, never inside it
# (default: art)
art_folder: art

# the store's index of names and sha256: URNs
# (default: _index_.json in the artifact folder)
index: art/_index_.json

# re-hash every load against its stored sha256 (default: false)
verify: false

# optional: the DatManager subclass to build, dotted; its own
# CONFIG_KEYS are allowed here and reach its constructor
manager: mylab.store.Store

# the command a copy of bin/dat hands its arguments to (see cli.md):
# your program's main: imports what it mounts, calls Dat.cli_main()
run: .venv/bin/python -m mypkg.main
```

Those six keys are the whole file, plus any key the named `manager` class lists
in its `CONFIG_KEYS`; an empty file is a complete config.
An unrecognized key is an error naming the file, the key and the known keys —
a typo is never silently ignored. The config's folder is the project's import
root: `load_dat_config` puts it first on `sys.path`, so the project's own
modules resolve from any working directory, installed or not.

The file is found by walking up from the working directory, or from the path
given to `DatManager.load_dat_config(start)`. A `.datconfig.override.yaml`
wins over it, and `DAT_FOLDERS` / `DAT_ART_FOLDER` in the environment win
over both. `run` is
read by the `bin/dat` bootstrap only (`DAT_RUN` overrides it there). The
bootstrap hands its child the config it found as `DAT_CLI_CONFIG`, which
`cli_main()` alone reads.

See [Mounts](mount-commands.md) for what a program can mount.

## See Also

- [Spec Format](spec-format.md) — `_spec_.yaml` and `_result_.yaml` reference
- [Mounts](mount-commands.md) — names that are not imports
- [Command Line](cli.md) — the `dat` verbs and the bootstrap copy
- [Overview](overview.md) — API reference
