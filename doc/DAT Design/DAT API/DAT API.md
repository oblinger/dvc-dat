---
description: "2.16: the contract of dvc-dat — one example, then the class, the manager, the CLI and the namespace"
---

| -[DAT API](DAT%20API.md)-             | : 2.16: the contract of dvc-dat — one example, then the class, the manager, the CLI and the namespace<br>→ [DAT](../../DAT%20Track/DAT.md) → [DAT Design](../DAT%20Design.md) → [DAT API](ha://p/DAT%20API) |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Class API](DAT%20Class%20API.md)     | `from dvc_dat import Dat`: the `Dat` class, `Dat.ns`, the spec file, the config                                                                                                                             |
| [CLI](DAT%20CLI.md)                   | `dat TARGET …` from a shell, and the bootstrap copy                                                                                                                                                         |
| [Namespace API](DAT%20Namespace%20API.md)           | the namespace under `Dat.ns`: your program's main, mounts, spec surgery — the advanced half                                                                                                                 |
| [Manager API](DAT%20Manager%20API.md) | `DatManager`: the one object — folders, artifacts, `run`, recording, its `ns`                                                                                                                                    |
| ...                                   |                                                                                                                                                                                                             |

# DAT API
The 2.16 contract of `dvc_dat`, shown once as a whole project.

### `.datconfig.yaml`
```yaml
# At the project root -- all keys are optional
dat_folders: data           # where dats live (default: data/)
art_folder: art             # artifacts, beside data/ (default)
# run: uv run dat           # what a copy of bin/dat execs -- your
#                           # own main, if it mounts names (Namespace API)
```

### `mymodule/train.py`
```python
# The function a dat runs, and a template spec naming it
def run(dat, epochs=1, lr=0.1):
    games = dat.manager.load("games/G1")       # another dat
    clip = Dat.load_artifact("games/G1/video") # an artifact
    # ... train on games and clip ...
    dat.get_results()["accuracy"] = 1 - lr / epochs
    dat.save()                        # seals it when the run returns
    return dat.get_results()["accuracy"]


baseline = {
    "dat": {"name": "runs/{YYYY}-{MM}/baseline{unique}",
            "do": "mymodule.train.run",
            "kwargs": {"epochs": 10, "lr": 0.1}},
    "notes": "started {now}",
    "modules": [],
    "learn_params": {
        "alpha": 0.5  # this specified
        ...,
}
```

### From Python
```python
from dvc_dat import Dat

m = Dat.manager              # the default world
Dat.save_artifact("clips/G1.mp4", name="games/G1/video")

Dat.manager.run("mymodule.train.baseline")          # -> data/runs/2026-09/baseline/
Dat.manager.run("mymodule.train.baseline", lr=0.5)  # a fork -> .../baseline_2/

d = Dat.load("runs/2026-09/baseline_2")
d.get_results()["accuracy"]   # 0.95
Dat.standing(d)               # 'referenceable': runs no more
Dat.manager.run(d, lr=0.01)   # forks a new dat; baseline_2 untouched
Dat.load_artifact("games/G1/video")  # a Path, or its type's
```

### From a shell
```bash
$ dat mymodule.train.baseline           # run, print the value
0.99

$ dat mymodule.train.baseline lr=0.25   # a fork; JSON, else the text
0.975

# a copy of bin/dat on PATH: any subdirectory, no environment active
$ cd analysis/scratch && dat mymodule.train.baseline lr=0.4
0.96
```

### `data/runs/2026-09/baseline_2/_spec_.yaml`
```yaml
# Written by the fork, expanded once; never rewritten
dat:
  name: runs/{YYYY}-{MM}/baseline{unique}   # the template, as given
  do: mymodule.train.run
  kwargs:
    epochs: 10
    lr: 0.5
  kind: dvc_dat.core.Dat
notes: started 26-09-22_12-30-20
```

### `data/runs/2026-09/baseline_2/_result_.yaml`
```yaml
# Written once, by the save that seals the dat
accuracy: 0.95
dat:
  dependencies:               # every dat and artifact it loaded
    games/G1: sha256:4b1e…    # a dat, as it stood when loaded
    games/G1/video: sha256:9f3c…  # an artifact, as saved
  standing: referenceable     # what the seal earned
  sha256: sha256:7c0a…        # this dat's own, stamped by save
```

- **The spec on disk is the record.** Every `{…}` in the template was expanded once, when the fork created the folder — `notes` is the moment it was made, `lr: 0.5` is what ran; `name` alone keeps its template, and the folder it filled to (`runs/2026-09/baseline_2`) is the dat's name. Nothing is expanded again, and nothing is re-supplied to reproduce it.
- **`_result_.yaml` carries no arguments** — only what the function stored, plus when it ran, how long, which code, what it loaded, and its own content hash ([DAT Manager API](DAT%20Manager%20API.md) § What a run records).
- **A run saves nothing; `save()` seals, once.** `run` ends with `dat.save()`, which seals the dat when the run returns; a save anywhere else adds the dependency `$MANUAL` ([DAT Class API](DAT%20Class%20API.md) § save).
- **Arguments never ride beside a spec.** `Dat.manager.run(d)` re-runs a dat only while it is open; `Dat.manager.run(d, lr=0.01)` forks — the copy lands beside its parent as `baseline_2_2` — and the dat on disk is never rewritten.
- **A dat is a ledger value.** `Dat` is a `dvc_dat.ledger.Value`, one class (DAT 1038): `seal`, `preds` and `subject` are on every dat, and `dat.kind` names the kind of its ledger row too. `d.seal(t, name="runs/baseline_2")` keeps the saved folder on a ledger, its preds `epochs`, `lr`, `accuracy` read from the spec's kwargs and the results; `L.at().run("mymodule.train.baseline", lr=0.5)` is the fork above, made once and then found, one `run` for a dat and a ledger function alike (DAT 1046), a mounted run function running in the sandbox worker ([DAT Ledger](../../DAT%20Modules/ledger/DAT%20Ledger.md#Running)).




# DAT Semantics

## Conceptual model

A **dat** is a folder holding `_spec_.yaml`, a complete argumentless recipe for itself, and `_result_.yaml`, what running it produced. **`Dat.manager.run`** is the one run and **`Dat.ns`** the one namespace: a dotted name means what `import` means in this environment, `getattr` below that, with `ns.mount(...)` calls in your program layered on top ([DAT Namespace API](DAT%20Namespace%20API.md)). **Arguments never ride beside a spec** — they fork a new one. Every spec string may carry `{…}` references, expanded once when the dat is created. And **a path is an address, not a record**: `dat.name` may organise a folder tree however you like, but nothing reads meaning back out of it — a dat loads by name and by nothing else, and everything *about* a dat is in its spec. Finding the right dat by what its spec says is the ledger's: a dat sealed there is a value found by its preds, its spec's kwargs and its results ([DAT 1007](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^1007), DAT 1038).


# Changes

## Migration from 1.x

`Dat.run()` → `Dat.manager.run(a_dat)`; `Dat.manager.do` → `Dat.do`; `DoManager`/`SimpleMethodManager` → the one `do`, configured for you on first use ([DAT Do API](DAT%20Do%20API.md)); spec key `dat.path` → `dat.name`; `dat.spec.dat.kind` → `d.get_spec()["dat"]["kind"]`; pydantic specs → a `validate_spec` override; `dat.base` may now be a list; call-site arguments no longer append to `dat.args` — they replace them, and they fork; config `mount_commands:` → `do.mount(...)` calls in your own program, and `run: python -m mypkg.main` for the shell ([DAT Do API](DAT%20Do%20API.md)); config `local_prefix` + `extra_local_prefixes` → `dat_folders`; config `python:` → `run:`; `bin/X` → `bin/dat`; `dat do TARGET` → `dat TARGET`; `--set KEY VALUE` / `--sets` → `--set KEY=VALUE`, repeated; `get_spec(raw=True)` → gone, the file holds the expanded values ([DAT 1009](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^1009)). From 2.x: the table in https://github.com/oblinger/dvc-dat/blob/main/CHANGELOG.md § 2.2.0.

**From 2.37:** `Dat.do` → `Dat.ns`, `manager.do` → `manager.ns`, `Do` → `Namespace`, `do.keys()` → `ns.mounts()`, `DatManager(do=)` → `ns=`; on a ledger `rev.resolve(name)` → `rev.ns.load(name)`, `LedgerDo` → `LedgerNamespace`, and `t.ns.mount(at, root=, repo=)` writes a mount ([DAT Namespace API](DAT%20Namespace%20API.md), DAT 1051).

**From 2.35:** `Dat.do(x, …)` → `Dat.manager.run(x, …)`; `manager.execute(dat)` → `manager.run(dat)`; `Dat.do` is the namespace only, and `dat.run` is still the run record (DAT 1049).

**From 2.13:** `Dat.status(name)` → `Dat.standing(name)`; `dat.rolling: true` → `dat.standing: rolling`; `execute(dat, referenceable=True)` → `dat.standing: referenceable` in the spec; `save(src, "art:k/r")` → `Dat.save_artifact(src, type=f, name="k/r")` (2.15; `m.save_artifact` on a manager); `register_artifact(k, f)` → `type=f` at save, mounted when it cannot be imported; `load("art:k/r")` → `Dat.load_artifact("k/r")` ([DAT Manager API](DAT%20Manager%20API.md) § save_artifact).

**From 2.7:** `from dvc_dat import do` → `do = Dat.do`; `dvc_dat.cli_main` / `merge_dicts` → `Dat.cli_main` / `Dat.merge_dicts`; `dvc_dat.expand` → `Dat.manager.expand` — the package exports `Dat`, `DatContainer`, `DatManager`, `Do`.

**From 2.2:** `DataConfig.new(cwd=…)` → `DatManager.load_dat_config(start)`; `do.configure(…)` / `do.config` → assign `Dat.manager`; `.dataconfig.yaml` → `.datconfig.yaml`; `DatManager(config)` → `DatManager(dat_folders=[…])`; `Dat.load(name, cwd=…)` → `Dat.load(name)`; new in 2.4: artifacts (`save`, `register_artifact`, `art:` names) and `dat.dependencies` ([DAT Manager API](DAT%20Manager%20API.md)).
