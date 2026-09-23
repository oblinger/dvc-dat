# Core Concepts

A **dat** is a folder whose `_spec_.yaml` is a complete, argumentless recipe for
itself. `_result_.yaml` holds only what running it produced.

`dvc_dat` has one namespace and one runner, both reached through `do`:

```python
from dvc_dat import Dat, do

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
arguments goes into `_result_.yaml`, and no dat on disk is ever rewritten by a
run. Re-running an existing dat is `do(dat)` with no arguments; handing that
same dat arguments forks a new one and leaves the original byte-identical.

**A created dat's spec never changes.** There is no method that rewrites
`_spec_.yaml`. To try a variation, make a new dat from an edited copy of the
spec. `merge_dicts` is the same zipper merge `dat.base` uses:

```python
from dvc_dat import Dat, do, merge_dicts

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
from dvc_dat import do

# finds .datconfig.yaml on the way
do("mypkg.train.baseline", lr=0.5)
```

To replace the default world, assign it. Mounts belong to the namespace
they were made on, so a replacement that should keep them adopts the
default `do`, which also makes it the default:

```python
from dvc_dat import Dat, DatManager, do

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

## Templates: `dat.base`

`dat.base` names a spec to inherit from — or a **list** of them, merged left to
right with later entries winning, so a dat can inherit from a DAG of specs.
Resolution is recursive and happens before the spec is written, so `dat.base`
never appears in a stored spec: what is on disk is the whole recipe.

## References: the `{}` grammar

Any string in a spec may carry `{…}` references. `Dat.create` expands them
once, with the same `now` and `unique` the folder got, and writes the result:
`get_spec()` returns the stored values, and nothing is expanded on read.

```python
from dvc_dat import expand, expand_spec

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

# the command a copy of bin/dat hands its arguments to (see cli.md):
# your program's main: imports what it mounts, calls dat.cli_main()
run: .venv/bin/python -m mypkg.main
```

Those two keys are the whole file, and an empty file is a complete config.
An unrecognized key is an error naming the file, the key and the known keys —
a typo is never silently ignored. The config's folder is the project's import
root: `load_dat_config` puts it first on `sys.path`, so the project's own
modules resolve from any working directory, installed or not.

The file is found by walking up from the working directory, or from the path
given to `DatManager.load_dat_config(start)`. A `.datconfig.override.yaml`
wins over it, and `DAT_FOLDERS` in the environment wins over both. `run` is
read by the `bin/dat` bootstrap only (`DAT_RUN` overrides it there). The
bootstrap hands its child the config it found as `DAT_CLI_CONFIG`, which
`cli_main()` alone reads.

See [Mounts](mount-commands.md) for what a program can mount.

## See Also

- [Spec Format](spec-format.md) — `_spec_.yaml` and `_result_.yaml` reference
- [Mounts](mount-commands.md) — names that are not imports
- [Command Line](cli.md) — the `dat` verbs and the bootstrap copy
- [Overview](overview.md) — API reference
