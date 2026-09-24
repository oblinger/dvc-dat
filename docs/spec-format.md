# Spec File Format

Every dat folder holds a `_spec_.yaml` (a `_spec_.json` is read too). The spec
is the dat's complete, argumentless recipe: everything needed to run it is in
the file, and nothing is supplied at the call site.

## Minimal Spec

```yaml
dat:
  kind: dvc_dat.core.Dat
```

`dat.kind` names the Python class as a dotted `module.qualname`, the way
pickle does. It defaults to the class that created the dat, so the minimal spec
a template has to write is `{}`. Loading imports it: a class that cannot be
imported is an `ImportError`, one that is not a `Dat` is a `TypeError`. A bare
name (`Run`), as dats written before 2.3 carry, is still read: it is looked up
among the loaded subclasses of `Dat`, and reads as `Dat` when none matches. A
class defined in a script or notebook is written `__main__.Run`, which only
that process can import.

## The `dat` section

```yaml
dat:
  kind: dvc_dat.core.Dat
  base: catalog.base_template
  name: "runs/{YYYY}-{MM}/exp{unique}"
  do: scripts.run_experiment
  args: [1, 2, 3]
  kwargs: {verbose: true}
  target_exists: error
```

| Field | Description |
|-------|-------------|
| `kind` | Dotted class path. `dvc_dat.core.Dat` or a subclass. |
| `base` | A spec to inherit from — a dotted name, a spec, or a **list** of either. Resolved before the spec is written, so it never appears in a stored spec. |
| `name` | The path template for the dat's folder. Used when `Dat.create()` is given no `path`. |
| `do` | Dotted name of the function to run. |
| `args` | Positional arguments for it, after the dat itself. |
| `kwargs` | Keyword arguments for it. |
| `target_exists` | What to do when the folder is already there. |

`kind`, `name`, `do` and `target_exists` are strings. A value that arrives as
something else is an error — which is how an unquoted `{…}` reference in YAML
is caught (see **References** below).

### `target_exists`

| Value | Behavior |
|-------|----------|
| `error` | Raise (default) |
| `use` | Return the dat that is already there, without running it |
| `overwrite` | Delete the folder and recreate it |
| `increment` | Count up (`_2`, `_3`, …) until the path is free |

A template with `{unique}` in its `dat.name` increments whether or not
`increment` is set. `overwrite` is refused on `{cwd}`.

## Running a dat

The function `dat.do` names is called as:

```python
fn(dat, *spec.dat.args, **spec.dat.kwargs)
```

Its return value is the value of the `do(...)` call. A spec with no `dat.do`
creates the dat and returns it.

`do(template, *args, **kwargs)` **forks**: keyword arguments update
`dat.kwargs` key by key and positional arguments replace `dat.args`, the
updated spec is written as the new dat's `_spec_.yaml`, and the new dat then
runs with no call-site arguments. So the arguments of every run are on disk, in
the spec of the dat that run produced.

## Custom fields

Any key outside `dat:` is the dat's own data and is kept as written:

```yaml
dat:
  kind: dvc_dat.core.Dat
title: My Experiment
parameters:
  learning_rate: 0.01
  epochs: 100
```

```python
dat = Dat.load("runs/my_experiment")
dat.get_spec()["parameters"]["learning_rate"]   # 0.01
```

## References: the `{}` grammar

Any string value in a **template** may carry `{…}` references. They are
expanded **once, when the dat is created** — with the same `now` and `unique`
the folder got — and the expanded spec is what `_spec_.yaml` holds. A spec on
disk is a record, never a template: `get_spec()` is the file, `dat.name` is
the folder the dat actually landed in, and `{now}` is the moment it was made.
A reference inside a longer string must resolve to a string or a number; a
reference that is the whole value may be any data YAML can hold, and is
inlined. A reference to anything else — a function, a class — is a
`TypeError` at create, and no folder is made.

| Reference | Resolves to |
|-----------|-------------|
| `{YYYY}` `{YY}` | 4- and 2-digit year |
| `{MM}` `{DD}` | month, day |
| `{HH}` `{mm}` `{SS}` | hour, minute, second |
| `{now}` | timestamp `yy-mm-dd_HH-MM-SS` |
| `{cwd}` | the working directory, full path |
| `{unique}` | empty, then `_2`, `_3`, … |
| `{a.b.c}` | whatever `do.load("a.b.c")` returns |
| `{{` `}}` | a literal `{` and `}` |

An undotted name that is neither a built-in nor a key of the `vars` dict passed
to `expand()` is a `KeyError`. Called directly, `expand()` returns the
referenced object itself for a string that is *exactly* one reference, a
function included. At create the rule above holds: data is inlined, and a
function or class is refused.

**YAML quoting.** A value that *begins* with `{` must be quoted:

```yaml
dat:
  name: "{svp.RUN_DIR}/exp"
```

Unquoted, YAML reads `{svp.RUN_DIR}` as a flow mapping and the spec arrives
with a dict where a string belongs; `validate_spec` rejects it and says so.

`expand(text, vars=None)` and `expand_spec(spec, vars=None)` are public — use
them instead of writing a parser.

## Inheritance: `dat.base`

**Base** (`catalog/base.yaml`):

```yaml
dat:
  kind: dvc_dat.core.Dat
defaults:
  optimizer: adam
  epochs: 100
```

**Child** (`catalog/experiment.yaml`):

```yaml
dat:
  kind: dvc_dat.core.Dat
  base: catalog.base
defaults:
  epochs: 200
custom_param: true
```

**Stored spec:**

```yaml
dat:
  kind: dvc_dat.core.Dat
defaults:
  optimizer: adam
  epochs: 200
custom_param: true
```

`dat.base` is gone from the result — the stored spec stands on its own.
Resolution is recursive, and an override wins even when its value is `0`, `""`
or `false`.

A list inherits from several specs at once, merged left to right:

```yaml
dat:
  base: [catalog.base, catalog.gpu, catalog.nightly]
```

`catalog.nightly` wins where they disagree.

Nested mappings merge key by key. Two lists whose entries are all mappings
with a `name` merge by name: a later entry merges into the earlier one of
the same name, a new name is appended in order, and `{name: X, remove: true}`
deletes X — so a variant lists only the stages it touches. Any other value,
any other list included, is replaced whole by the later spec. The same merge is `merge_dicts(*dicts)`,
for a spec hydrated by hand:

```python
from dvc_dat import Dat

do, merge_dicts = Dat.do, Dat.merge_dicts

spec = merge_dicts(do.load("configs.bb.base"), {"gameset": "G7"})
Dat.create(spec=spec)
```

A created dat's spec carries the folder it landed in as `dat.name`, so a
variation of an existing dat `d` asks to land beside it — without
`increment` the create raises `FileExistsError`:

```python
from dvc_dat import Dat

merge_dicts = Dat.merge_dicts

spec = merge_dicts(d.get_spec(),
                   {"dat": {"target_exists": "increment"},
                    "gameset": "G7"})
Dat.create(spec=spec)
```

## Validation

`Dat.validate_spec(cls, spec) -> spec` runs on both `create` and `load`, on the
class `dat.kind` names. The default checks that the spec is a mapping, that
`dat` is a mapping, and that the string-typed `dat.*` fields are strings. A
subclass overrides it to add its own checks — with a schema library, with a
hand-written check, or with none at all.

## Result file

`_result_.yaml` holds only what running the dat produced: whatever the function
put in `dat.get_results()`, plus what the runner knows: when, how long, and
which code — the branch, commit and dirty flag (tracked files) of the git
checkout holding the source of the function `dat.do` names — and what it
used. Code outside a checkout records no `code`; a detached HEAD records
`branch: null`. `dependencies` maps every dat and artifact the run loaded
through its manager to its hash: an artifact's `sha256`, a dat's
`dat.sha256`, or `unsealed` for a dat still open. A dat's key is its name
under its dat folder (its absolute path outside every folder); a run that
loaded nothing records `{}`. A dat sealed outside its own run records
`$MANUAL: manual`. At the seal an entry that another entry already depends on is
dropped.

`_result_.yaml` is written only by `dat.save()`: `create` writes no results
file, and a run leaves its record in memory until the dat is saved. A dat is
sealed when the file carries `dat.run_time` (a run's own save, finished) or
`$MANUAL` (a hand save), and no `unsealed` entry; the seal adds
`dat.referenceable: true|false`. `dat.rolling: true` belongs in the spec, not
here. `dat.sha256` is the hash of the version saved, stamped by every save: the sha256 of sorted `relpath\0sha256` lines
over every file in the folder, `_result_.yaml` included. That one file is
hashed as its sorted-key YAML dump with `dat.sha256` set to `excluded`, so
the hash can live inside the file it covers. `dat.verify()` recomputes it the
same way and is `True` while the folder is exactly as it was last saved —
a changed data file, spec or result makes it `False`, reformatting the YAML
does not. A dat saved before 2.9 carries no hash; with no `dat.run_time` it is
open until saved, and without `dat.referenceable` it is not referenceable.

```yaml
dat:
  run_at: "2026-09-21 16:20:19"
  run_time: "00:00:00.011"
  code:
    branch: main
    commit: 9d8df8f1c2a6e0b7d5f4e3a2b1c0d9e8f7a6b5c4
    dirty: false
  dependencies:
    games/G1: "sha256:4b1e…"
    art:video/G1: "sha256:9f3c…"
  sha256: "sha256:7c0a…"
accuracy: 0.95
```

Arguments are **not** recorded here. They are in the spec.

## See Also

- [Core Concepts](concepts.md) — how dats fit together
- [Mount Commands](mount-commands.md) — where templates live
