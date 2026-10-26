---
description: "the namespace under `Dat.do`: your program's main, mounts, spec surgery — the advanced half"
---
:>> [DAT](../../DAT%20Track/DAT.md) → [DAT Design](../DAT%20Design.md) → [DAT API](DAT%20API.md) → [DAT Do API](ha://p/DAT%20Do%20API) 
# DAT Do API
The advanced half of `Dat.do`: what a dotted name resolves to, how to make one mean something other than a Python import, and what that costs — the plain surface is [DAT API](DAT%20API.md).

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

Dat.do.mount(module="mymodule.train", at="train")   # an alias

if __name__ == "__main__":
    if os.environ.get("DAT_CLI_CONFIG"):   # launched by `dat`
        sys.exit(Dat.cli_main())           # the shell, here
    ...                                    # otherwise, your own main
```

```python
from dvc_dat import Dat, DatManager

do = Dat.do
do("train.baseline")    # 'train' resolves through the mount table
do.load("train.run")        # the function itself, unrun
do.name_of(run)             # 'mymodule.train.run'
Dat.manager = DatManager.load_dat_config(path, do=do)
```

Without the mount table the same name fails, and says so:

```
ImportError: do.load: no importable prefix of 'train.baseline'
```

```
$ dat --list train

Base names matching: 'train*'
  train                     -->  <module>
```

## Do Interface
One world's namespace and runner. `manager.do` is built with its manager or adopted by one, and points back; `Dat.do` forwards to `Dat.manager.do`, so it always acts on the default world, whichever manager that is. Nothing reads a config here — that is `DatManager.load_dat_config` ([DAT Manager API](DAT%20Manager%20API.md)).

| Do | |
| --- | --- |
| [manager](#^manager) | The world this namespace belongs to |
| [__call__](#^call) | Run in this world; arguments fork |
| [load](#^load) | The object a dotted name resolves to |
| [resolve](#^resolve) | A spec merged over its `dat.base` chain |
| [name_of](#^name-of) | The dotted name `load` takes back to `obj` |
| [mount](#^mount) | Add one mount: folder, file, module or value |
| [keys](#^keys) | Every mounted base name |

**manager**`: DatManager`
    The world this namespace belongs to; one `do` per manager, one manager per `do`. On `Dat.do` it is `Dat.manager`. A bare `Do()` has none and is a plain namespace of Python objects: `mount`, `load`, `name_of`, `keys` and calling a plain function all work with no manager and no default world built. Running a dat (a spec or a `Dat`) is the one thing that needs a world — `Do(manager=m)`, or a manager built with `do=` adopts it — and raises `RuntimeError` without one. ^manager

**__call__**`(target: str | dict | Dat | Callable, *args, **kwargs) -> Any`
    Fork, create or load through `manager`, then `manager.execute(dat)`. A `do(...)` inside the running function reaches `execute` again on the same manager, so runs nest and record as a stack. Nothing is remembered: a template makes a fresh folder every call. Its ledger form is `rev.do(target, **kwargs)` (DAT 1038): the same targets (a template spec, its name, or a run function's dotted name, which is the spec `{dat: {do: <name>}}`), the kwargs updating `dat.kwargs` as here, and the dat made, run and sealed as a value once, then found by its question, the spec expanded with `dat.name` left out ([DAT Ledger § do](../../DAT%20Modules/ledger/DAT%20Ledger.md#Rev%20Interface)). ^call

**load**`(name: str, *, default: Any = …, kind: str | None = None) -> Any`
    The object `name` resolves to: mount table first, then the static floor. `ImportError` / `AttributeError` / `KeyError` propagate raw unless `default` is given. A mounted `.py` / `.yaml` / `.json` file comes back as loaded. ^load

**resolve**`(spec: dict | str) -> dict`
    A spec, or the name of one, merged over its `dat.base` (a name, a spec or a list, later entries winning), recursively, with `dat.base` dropped — what `create` stores. ^resolve

**name_of**`(obj: Any) -> str`
    The dotted name `load` takes back to a module, class or function. `ValueError` for anything it cannot name. ^name-of

**mount**`(*, folder | file | module | value, at: str = "", relative_to: str = ".") -> None`
    Add one mount, exactly one of the four sources; your program makes the calls. See § Mount forms. ^mount

**keys**`() -> Iterable[str]`
    Every mounted base name (a `value` mount is not one). `dat --list` prints them. ^keys




# Do Semantics

## When you need this page

Rarely, and the test is one line: **is every `dat.do` in your specs an importable Python name?** If it is — a function in a package your environment already has — nothing here applies, `.datconfig.yaml` needs nothing but `dat_folders`, and [DAT API](DAT%20API.md) is the whole contract.

You are here because something in the namespace is *not* a Python import: a folder of loose do-scripts addressed by file name, a short alias for a long path, or a value pinned in the config.

## What a dotted name resolves to

Two layers, checked in order.

**The mount table**, if one is installed — names your program put there with `do.mount(...)`, by folder, file, module or value. Nothing in YAML mounts anything, and nothing is imported on your behalf: the namespace is whatever the running program imported ([DAT 1008](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^1008) Q2, [DAT 1009](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^1009)). For the shell, `run:` names your own main — a module that makes the mounts and ends with `sys.exit(Dat.cli_main())` — so `dat …` runs inside it; with no `run:` the bootstrap runs the library's own main, where a dotted name is a Python name and nothing else.

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
| `do.mount(folder=pth, at=NAME)` | every loadable under `pth`, by path: `NAME.models.baseline`; a dat folder as `NAME.run._spec_` |
| `do.mount(file=pth, at=NAME)` | one `.py` / `.yaml` / `.json` file |
| `do.mount(module=name_or_path, at=NAME)` | a module — by import name or module object it is an alias; by path it is loaded outside `sys.path` |
| `do.mount(value=V, at=NAME)` | a literal value; `NAME.key` reaches into a mapping; a string starting `yaml` is parsed |

`at` is the name the mount answers to; a folder mounted without it puts its top-level files and folders at the namespace root. A mounted name never shadows an importable one: `mount` raises `ValueError` when a top-level name it would add is a module Python can import from elsewhere. A module or package mounted at its own name is not a clash. Pick another `at` and both keep a name.

# Changes

## 2.3 – 2.8

| Before (2.2) | After |
| --- | --- |
| `do.configure(source)` | `Dat.manager = DatManager.load_dat_config(source, do=Dat.do)` |
| `do.config` | gone; a namespace holds no config |
| `do`, the one `Do`, owning the config | `Dat.do` forwards to `Dat.manager.do` (2.8; was `dvc_dat.do`); every manager has its own |
| a bare `Do()` gets a world on first use | a bare `Do()` is a plain namespace; running a dat needs `Do(manager=m)` |

# BRIEF
- 2026-09-23 — rewritten to the 2.3 surface ([DAT 103](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^103), [DAT 1014](../../DAT%20Track/DAT%20Backlog/DAT%20Backlog.md#^1014)): § The names became the `Do` module doc in Dan's member format; `do.configure` and `do.config` are gone — a different world is an assignment to `Dat.manager`; `.dataconfig.yaml` → `.datconfig.yaml`; the TOC table dropped (the class table replaces it).
