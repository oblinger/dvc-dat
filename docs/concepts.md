# Core Concepts

A **dat** is a folder whose `_spec_.yaml` is a complete, argumentless recipe for
itself. `_result_.yaml` holds only what running it produced.

`dvc_dat` has one namespace and one runner, both reached through `do`:

```python
from dvc_dat import Dat, do, load

# a dotted name -> a Python object; the first call finds and
# applies the nearest .dataconfig.yaml
template = do.load("catalog.experiment")

# fork the template, run the fork
result = do("catalog.experiment", epochs=200)

# a path -> the dat on disk
dat = load("runs/2026-09/exp")
```

## Two kinds of name

**Dotted names** (`catalog.experiment`, `os.path.join`) name source code:
templates, functions, constants. `do.load` resolves them — first against the
mount table from `.dataconfig.yaml`, then by import: the longest importable
prefix of the name is imported and the rest is `getattr`-ed. So any importable
object has a name whether or not it was mounted, and `do.name_of(obj)` gives the
name that loads back to it.

**Slash paths** (`runs/experiment1`) name dat folders. They are relative to
`local_prefix` (default `data/`) or absolute. `load(name)` opens one.

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

For in-place iteration — profiling, report tuning, a `dev` dat you squash every
run — give the spec a fixed `dat.name` and `target_exists: overwrite`. The
running code then has to cope with output files that already exist.

## Nothing is found by the shape of its path

A dat's location carries no meaning the library relies on. Metadata lives in the
spec and in the results, and a consumer finds dats by querying their contents,
never by parsing a path.

## `do` is a singleton, and it configures itself on first use

`import dvc_dat` touches no filesystem: it hands you a `do` that can already
resolve importable names, with `do.config is None` and no `Dat.manager` built.
The **first** call that needs a config — a `do(...)`, a `do.load(...)`, a
`Dat.load` / `Dat.create`, any touch of `Dat.manager` — reads the nearest
`.dataconfig.yaml` walking up from the working directory, builds `Dat.manager`
from it, puts the config's folder first on `sys.path`, and imports the
config's `main` module if it names one. Nothing in an ordinary program calls
`configure`:

```python
from dvc_dat import do

# finds .dataconfig.yaml on the way
do("mypkg.train.baseline", lr=0.5)
```

`do.configure(source)` stays for the cases where the default is wrong — a
config somewhere other than above the working directory, or one you built in
code:

```python
# a folder, a config file, or a DataConfig
do.configure(project_root)
```

Mounts land on the same object either way, so a name imported before the
config was installed keeps resolving. The `dat` command-line tool needs no
special handling (see [Command Line](cli.md)); a long-lived service that
starts in one directory and works in another should call `do.configure()`
explicitly rather than depend on where the process happened to launch.

## Templates: `dat.base`

`dat.base` names a spec to inherit from — or a **list** of them, merged left to
right with later entries winning, so a dat can inherit from a DAG of specs.
Resolution is recursive and happens before the spec is written, so `dat.base`
never appears in a stored spec: what is on disk is the whole recipe.

## References: the `{}` grammar

Any string in a spec may carry `{…}` references, resolved when the spec is read
back through `get_spec()` (and when a path template is expanded).

```python
from dvc_dat import expand, expand_spec

# 'runs/2026-09/exp'
expand("runs/{YYYY}-{MM}/exp")

# the object do.load('svp.CONFIG') returns
expand("{svp.CONFIG}")
```

- an **undotted** name is a built-in (`YYYY YY MM DD HH mm SS now cwd unique`)
  or a key of the `vars` dict you pass; anything else is a `KeyError`
- a **dotted** name resolves through `do.load` at run time
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

## Configuration: `.dataconfig.yaml`

```yaml
# where dats are stored
local_prefix: data

# further folders searched when loading by name
extra_local_prefixes: []

# imported when the config installs; do.mount(...) calls live there
main: mypkg.datconf

# the interpreter the bootstrap copy of `dat` runs (see cli.md)
python: .venv
```

Those four keys are the whole file, and an empty file is a complete config.
An unrecognized key is an error naming the file, the key and the known keys —
a typo is never silently ignored. The config's folder is the project's import
root: it goes first on `sys.path` when the config installs, so `main` and
every other module of the project resolve from any working directory,
installed or not.

The file is found by walking up from the working directory, or from the path
given to `do.configure(...)` / `DataConfig.new(cwd=...)`. A
`.dataconfig.override.yaml` beside it wins over it, and a `DAT_<KEY>`
environment variable (`DAT_LOCAL_PREFIX`) wins over both.

See [Mounts](mount-commands.md) for what `main` can mount.

## See Also

- [Spec Format](spec-format.md) — `_spec_.yaml` and `_result_.yaml` reference
- [Mounts](mount-commands.md) — names that are not imports
- [Command Line](cli.md) — the `dat` verbs and the bootstrap copy
- [Overview](overview.md) — API reference
