---
description: "the namespace `ns` on `Dat`, a revision and a transaction: your program's main, mounts, the mount table — the advanced half"
---
:>> [DAT](../../DAT%20Track/DAT.md) → [DAT Design](../DAT%20Design.md) → [DAT API](DAT%20API.md) → [DAT Namespace API](ha://p/DAT%20Namespace%20API) 
# DAT Namespace API
The advanced half of `Dat.ns`: what a dotted name resolves to, how to make one mean something other than a Python import, and what that costs — the plain surface is [DAT API](DAT%20API.md). A ledger has the same object at a revision, `rev.ns`, and in a transaction, `t.ns` (§ On a ledger).

A project that wants `train.baseline` to be a name:

```yaml
dat_folders: data
run: .venv/bin/python -m mymodule.main   # the shell runs *your* main
```

```python
# mymodule/main.py -- your program's entry; the shell's too
import os
import sys
from dvc_dat import Dat

Dat.ns.mount(module="mymodule.train", at="train")   # an alias

if __name__ == "__main__":
    if os.environ.get("DAT_CLI_CONFIG"):   # launched by `dat`
        sys.exit(Dat.cli_main())           # the shell, here
    ...                                    # otherwise, your own main
```

```python
from dvc_dat import Dat, DatManager

ns = Dat.ns
Dat.manager.run("train.baseline")   # 'train': the mount table
ns.load("train.run")        # the function itself, unrun
ns.name_of(run)             # 'mymodule.train.run'
ns.mounts()                 # {'train': 'mymodule.train', ...}
Dat.manager = DatManager.load_dat_config(path, ns=ns)
```

Without the mount table the same name fails, and says so:

```
ImportError: ns.load: no importable prefix of 'train.baseline'
```

```
$ dat --list train

Base names matching: 'train*'
  train                     -->  <module>
```

## Namespace Interface
One world's namespace; it is not callable — running is `manager.run(target, ...)` ([DAT Manager API](DAT%20Manager%20API.md) § run), which loads names here. `manager.ns` is built with its manager or adopted by one, and points back; `Dat.ns` forwards to `Dat.manager.ns`, so it always acts on the default world, whichever manager that is. Nothing reads a config here — that is `DatManager.load_dat_config` ([DAT Manager API](DAT%20Manager%20API.md)). In a project whose `.datconfig.yaml` names a ledger, `Dat.manager.ns` is a `LedgerNamespace` at the head (§ On a ledger).

| Namespace | |
| --- | --- |
| [manager](#^manager) | The world this namespace belongs to |
| [load](#^load) | The object a dotted name resolves to |
| [name_of](#^name-of) | The dotted name `load` takes back to `obj` |
| [mount](#^mount) | Add one mount: folder, file, module or value |
| [mounts](#^mounts) | The mount table, `{prefix: location}` |

**manager**`: DatManager`
    The world this namespace belongs to; one `ns` per manager, one manager per `ns`. On `Dat.ns` it is `Dat.manager`. A bare `Namespace()` has none and is a plain namespace of Python objects: `mount`, `load`, `name_of` and `mounts` all work with no manager and no default world built; reading `manager` before `Namespace(manager=m)`, or a manager built with `ns=` adopting it, raises `RuntimeError`. ^manager

**load**`(name: str, *, default: Any = …, kind: str | None = None) -> Any`
    The object `name` resolves to: mount table first, then the static floor. `ImportError` / `AttributeError` / `KeyError` propagate raw unless `default` is given. A mounted `.py` / `.yaml` / `.json` file comes back as loaded. ^load

**name_of**`(obj: Any) -> str`
    The dotted name `load` takes back to a module, class or function. `ValueError` for anything it cannot name. ^name-of

**mount**`(*, folder | file | module | value, at: str = "", relative_to: str = ".") -> None`
    Add one mount, exactly one of the four sources; your program makes the calls. See § Mount forms. ^mount

**mounts**`() -> Dict[str, str]`
    The mount table: each mounted prefix and where it loads from — a file, a folder entry, or a module's import name. A `value` mount has no location and is not listed; `dat --list` prints every mounted name. ^mounts

## On a ledger
A `LedgerNamespace`: the same interface, its names the ledger's `db/mount` rows at one revision, longest prefix first; a name under no mount is imported. A mounted `.yaml`/`.json` comes back a dict, a mounted function its `Fn` (read off the file, never imported here), a mounted literal its value; a `@ledger_fn` it imports to comes back its `Fn`.

| Where | Is |
| --- | --- |
| `rev.ns` | the namespace at that revision |
| `t.ns` | the namespace at `t.previous_rev`; it also mounts |
| `Dat.manager.ns` | in a ledger project, the namespace at the head |

```python
f = L.at().ns.load("plane.measure.length")   # an Fn
L.at().ns.mounts()
# {'plane': {'root': 'plane', 'repo': 'geometry'}}
with L.transaction(by="human:dan") as t:
    t.ns.mount("plane", root="plane", repo="geometry")
    t.ns.mount("mymodule", root="mymodule")   # this project's repo
```

`mounts()` is the `db/mount` rows, `{prefix: {"root": ..., "repo": ...}}`. `t.ns.mount(at, *, root, repo=None)` writes the two rows `db/mount/<at> db/root` and `db/repo` through `t.update`, and needs no `lock=`; `repo` defaults to the project's own repository, the git checkout holding the `.datconfig.yaml` the manager loaded, named as discovery names repos, and with no such file is `ValueError`; `t.ns.load` reads `previous_rev`, so it does. `mount` anywhere else — `rev.ns`, `Dat.ns` in a ledger project — is `TypeError` naming `t.ns.mount`. Full ledger reference: [DAT Ledger](../../DAT%20Modules/ledger/DAT%20Ledger.md).




# Namespace Semantics

## When you need this page

Rarely, and the test is one line: **is every `dat.do` in your specs an importable Python name?** If it is — a function in a package your environment already has — nothing here applies, `.datconfig.yaml` needs nothing but `dat_folders`, and [DAT API](DAT%20API.md) is the whole contract.

You are here because something in the namespace is *not* a Python import: a folder of loose run scripts addressed by file name, a short alias for a long path, or a value pinned in the config.

## What a dotted name resolves to

Two layers, checked in order.

**The mount table**, if one is installed — names your program put there with `Dat.ns.mount(...)`, by folder, file, module or value. Nothing in YAML mounts anything, and nothing is imported on your behalf: the namespace is whatever the running program imported ([DAT 1008](../../DAT%20Track/DAT%20Backlog/1008%20-%20Should%20configure%28%29%20disappear,%20and%20should%20the%20static%20namespace%20be%20the.md) Q2, [DAT 1009](../../DAT%20Track/DAT%20Backlog/1009%20-%20The%20config's%20key%20names%20and%20the%20CLI's%20one%20verb,%20before%202.0%20is%20tagged.md)). For the shell, `run:` names your own main — a module that makes the mounts and ends with `sys.exit(Dat.cli_main())` — so `dat …` runs inside it; with no `run:` the bootstrap runs the library's own main, where a dotted name is a Python name and nothing else.

**The static floor**, always — the longest importable prefix of the name, imported, then `getattr` for the rest. `pkg.mod.CONST` imports `pkg.mod` and takes `CONST` off it. Nothing found raises the import's own `ImportError` or `AttributeError`, unless `default=` was given.

With no mount table the floor *is* the whole namespace, and a dotted name in a spec means exactly what it means in a Python file.

## What the dynamic layer costs

The worry is that names resolved by the library are not the modules the rest of the program is running. Mostly untrue: `importlib.import_module` returns whatever `sys.modules` already holds, so a name your program imported resolves to **that same module object** — same globals, same singletons. It diverges in three places, and only three.

**A file run as `__main__`.** `python scripts/train.py` makes that file `sys.modules["__main__"]`; a spec naming `scripts.train.run` imports it a *second* time under its real name, and you get two copies of every global in it. The rule that prevents it: anything a spec names lives in an importable module, never in a script you also run directly.

**A different `sys.path`.** The `dat` command is a separate process. The `run:` key and the `bin/dat` bootstrap exist to pin it to the same interpreter as your program, so the same name resolves to the same file — see [DAT CLI](DAT%20CLI.md).

**By-path mounts.** A mounted folder or file, or a module mounted by path, is loaded **by file path**, bypassing `sys.path` entirely, so a module reached that way can never be the one your program imported — even if the file is the same file. This is the one genuinely dynamic thing in the library, and the reason mounts are opt-in. A module mounted **by name** is the opposite: it resolves through `sys.modules`, so it is an alias for the object your program already holds, and costs nothing.

## Mount forms

Each is one call in your program; build paths from `__file__`, since `relative_to` defaults to the working directory.

| Call | Mounts |
| --- | --- |
| `ns.mount(folder=pth, at=NAME)` | every loadable under `pth`, by path: `NAME.models.baseline`; a dat folder as `NAME.run._spec_` |
| `ns.mount(file=pth, at=NAME)` | one `.py` / `.yaml` / `.json` file |
| `ns.mount(module=name_or_path, at=NAME)` | a module — by import name or module object it is an alias; by path it is loaded outside `sys.path` |
| `ns.mount(value=V, at=NAME)` | a literal value; `NAME.key` reaches into a mapping; a string starting `yaml` is parsed |

`at` is the name the mount answers to; a folder mounted without it puts its top-level files and folders at the namespace root. A mounted name never shadows an importable one: `mount` raises `ValueError` when a top-level name it would add is a module Python can import from elsewhere. A module or package mounted at its own name is not a clash. Pick another `at` and both keep a name.

# Changes

## 2.37 (DAT 1051)

| Before (2.36) | After |
| --- | --- |
| `Dat.do`, `manager.do`, class `Do` | `Dat.ns`, `manager.ns`, class `Namespace` |
| `DatManager(..., do=)`, `load_dat_config(..., do=)` | `ns=` |
| `do.keys()` | `ns.mounts()`, the mount table |
| `rev.resolve(name)` | `rev.ns.load(name)` |
| `LedgerDo` | `LedgerNamespace` |
| `t.update("db/mount/<p>", {"db/root": ..., "db/repo": ...})` | `t.ns.mount("<p>", root=...)`, `repo=` only for another repo (the `update` still works) |

## 2.3 – 2.8

| Before (2.2) | After |
| --- | --- |
| `do.configure(source)` | `Dat.manager = DatManager.load_dat_config(source, do=Dat.do)` |
| `do.config` | gone; a namespace holds no config |
| `do`, the one `Do`, owning the config | `Dat.do` forwards to `Dat.manager.do` (2.8; was `dvc_dat.do`); every manager has its own |
| a bare `Do()` gets a world on first use | a bare `Do()` is a plain namespace; running a dat needs `Do(manager=m)` |

# BRIEF
- 2026-10-27 — renamed from DAT Do API for `ns` ([DAT 1051](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^1051)): `Dat.do` → `Dat.ns`, `keys` → `mounts`, § On a ledger added for `rev.ns` and `t.ns`.
- 2026-09-23 — rewritten to the 2.3 surface ([DAT 103](../../DAT%20Track/DAT%20Backlog/103%20-%20API%20refactor/103%20-%20API%20refactor.md), [DAT 1014](../../DAT%20Track/DAT%20Backlog/103%20-%20API%20refactor/1014%20-%20Fold%20DataConfig%20into%20DatManager;%20settle%20the%20manager's%20public%20attributes.md)): § The names became the `Do` module doc in Dan's member format; `do.configure` and `do.config` are gone — a different world is an assignment to `Dat.manager`; `.dataconfig.yaml` → `.datconfig.yaml`; the TOC table dropped (the class table replaces it).
