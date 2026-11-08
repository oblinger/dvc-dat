:>> [DAT](DAT%20Track/DAT.md) → [DAT spec-format](ha://p/DAT%20spec-format) 
# Spec File Format
The `_spec_.yaml` and `_result_.yaml` file formats.

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
  name: runs/${now:%Y-%m}/exp${unique:}
  do: scripts.run_experiment
  args: [1, 2, 3]
  kwargs: {verbose: true}
  defaults: {tag: base}
  preds: {tag: "${dat.defaults.tag}"}
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
| `defaults` | Plain values a template reads by their node, `${dat.defaults.tag}` (SVP 1508); kwargs over defaults is `${oc.select:dat.kwargs.tag,${dat.defaults.tag}}`. |
| `preds` | Pred names to templates (SVP 1508), resolved at create like every string; each must come out a string, number or bool. They are the dat's own preds, sealed onto its value on a ledger. |
| `target_exists` | What to do when the folder is already there. |

`kind`, `name`, `do` and `target_exists` are strings. A value that arrives as
something else is an error — which is how a value YAML read as a flow mapping
(one starting `{`) is caught.

### `target_exists`

| Value | Behavior |
|-------|----------|
| `error` | Raise (default) |
| `use` | Return the dat that is already there, without running it |
| `overwrite` | Delete the folder and recreate it |
| `increment` | Count up (`_2`, `_3`, …) until the path is free |

A template with `${unique:}` in its `dat.name` increments whether or not
`increment` is set. `overwrite` is refused on `${cwd:}`, and deletes only inside a dat folder or the art folder: an absolute name (or a `..`) outside them with `overwrite` is `ValueError`, raised before anything is removed.

## Running a dat

The function `dat.do` names is called as:

```python
fn(dat, *spec.dat.args, **spec.dat.kwargs)
```

Its return value is the value of the `Dat.manager.run(...)` call. A spec with no `dat.do`
creates the dat and returns it.

`Dat.manager.run(template, *args, **kwargs)` **forks**: keyword arguments update
`dat.kwargs` key by key and positional arguments replace `dat.args`, the
updated spec is written as the new dat's `_spec_.yaml`, and the new dat then
runs with no call-site arguments. So the arguments of every run are on disk, in
the spec of the dat that run produced.
A call-site argument is literal data: each `${` in it is escaped before the
merge, so the resolve at create leaves it exactly as passed (on the base
install one holding `${` is refused, naming `dvc-dat[expand]`).
`Dat.create(template, **kwargs)` merges its keywords the same way and runs nothing.
A template reads a keyword by its node: `${dat.kwargs.game}` anywhere in the
spec, `dat.name` and `dat.preds` included.

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

## References: the `${…}` grammar

Any string value in a **template** may carry `${…}` references, OmegaConf's
grammar: `${batch}` a node of the spec, `${ns:a.b}` a namespace name,
`${now:%Y}`, `${unique:}`, `${cwd:}` the built-ins, `\${` a literal `${`.
They are resolved **once, when the dat is created** — after `dat.base` is
merged, with the same moment and count the folder got — and the resolved spec
is what `_spec_.yaml` holds. A spec on disk is a record: `get_spec()` is the
file and `${now:}` was the moment it was made. The one exception is
`dat.name`, which keeps the path template as given, never the path it
resolved to; the folder the dat landed in is its name (`get_path_name()`). A
`dat.name` in the `{…}` grammar retired in 3.0 is refused, naming the new
spelling; the base install resolves `${unique:}` alone.

The grammar itself — the tiers, the built-ins, names and calls through the
namespace, `${unique:}`, the errors — is one page: [Expansion](expand.md).

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
or `false`. `Dat.ns.expand_spec(spec)` returns the merged spec with every `{}`
filled, which is what `create` stores (bar `dat.name`).

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

ns, merge_dicts = Dat.ns, Dat.merge_dicts

spec = merge_dicts(ns.load("configs.bb.base"), {"gameset": "G7"})
Dat.create(spec=spec)
```

A created dat's spec carries its path template as `dat.name` (a constant
path is its own template), so a variation of an existing dat `d` asks to
land beside it — without `increment` the create raises
`FileExistsError`:

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
put in `dat.get_results()`, plus what it used. When, where, how long and
which code are the run's, not the dat's: they are in the run sub-dat (see
below). `dependencies` maps every dat and artifact the run loaded
through its manager to its hash: an artifact's `sha256`, a dat's
`dat.sha256`, or `unsealed` for a dat still open. A dat's key is its name
under its dat folder (its absolute path outside every folder); an artifact's
is its name or, with none, its URN. A run that loaded nothing records `{}`. A dat sealed outside its own run records
`$MANUAL: manual`. At the seal an entry that another entry already depends on is
dropped.

`_result_.yaml` is written only by `dat.save()`: `create` writes no results
file, and a run leaves its record in memory until the dat is saved. Every
save stamps `dat.standing` — `rolling`, `open`, `sealed` or
`referenceable`, what that save earned (see [Standing](concepts.md#standing-how-far-a-dat-can-be-relied-on)).
In the spec, `dat.standing` is a demand, `rolling` or `referenceable`.
`dat.sha256` is the hash of the content saved, stamped by every save: the
sha256 of sorted `relpath\0sha256` lines over every file in the folder but
its subdats: `run/` and any other folder inside it whose spec names `dat.kind`. `_spec_.yaml` is hashed as its sorted-key YAML dump with
`dat.name` left out (the name is the dat's address, not its content), and
`_result_.yaml` as its sorted-key dump with `dat.sha256` set to `excluded`,
so the hash can live inside the file it covers. `dat.hash: functional` marks
a file hashed this way, the only rule; a hash a 2.x save stamped does not
verify. `dat.verify()`
recomputes it the same way and is `True` while the content is exactly as it
was last saved — a changed data file, recipe or result makes it `False`;
reformatting the YAML, renaming the dat or anything under a subdat does not. A results file with no `dat.standing` (never saved, or written
before 2.14, whose 2.13 keys are not read) is open, rolling when its spec
demands `dat.standing: rolling`, until saved.

```yaml
dat:
  dependencies:
    games/G1: "sha256:4b1e…"
    games/G1/video: "sha256:9f3c…"
  standing: referenceable
  hash: functional
  sha256: "sha256:7c0a…"
accuracy: 0.95
```

Arguments are **not** recorded here. They are in the spec.

## The `run/` folder

Every run makes `run/` inside the dat, a dat of its own with a minimal
`_spec_.yaml` and a `_result_.yaml` holding the execution — when, how long,
where, and which code: the branch, commit and dirty flag (tracked files) of
the git checkout holding the source of the function `dat.do` names. A path
the repo's `.gitattributes` marks `dat-noncode` (`doc/** dat-noncode`) is not
code: a change there leaves the flag clear. Code
outside a checkout records no `code`; a detached HEAD records `branch:
null`. `content` is the `dat.sha256` the run sealed, written after the
seal. `run/work/` is the run's scratch and its working directory. A run that
has finished reads `standing: sealed`; it carries no `sha256` of its own.
A dat runs once (a rolling one again, replacing `run/`), so there is one.

```yaml
dat:
  run_at: "2026-10-06 11:02:41"
  host: gpu-7
  pid: 41218
  code:
    branch: main
    commit: 9d8df8f1c2a6e0b7d5f4e3a2b1c0d9e8f7a6b5c4
    dirty: false
  run_time: "00:04:12.380"
  standing: sealed
  content: "sha256:7c0a…"
```

## See Also

- [Core Concepts](concepts.md) — how dats fit together
- [Mount Commands](mount-commands.md) — where templates live
