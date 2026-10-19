---
description: "three subsystems and where they meet"
---
:>> [DAT](ha://DAT) → [DAT Design](ha://DAT%20Design) → [DAT Architecture](ha://p/DAT%20Architecture) 
# DAT Architecture
A folder is a dat once it carries `_spec_.yaml`; a dotted name is a Python object once `do` resolves it; `DatManager.create` is where the two meet — it asks `do` for `dat.base` and every `{a.b}`, then writes the spec once.

![[DAT Architecture.svg|2400]] 

One object: `Dat.manager`, a `DatManager` (`core.py`) that owns its folders and its `Do` (`do.py`); `Dat.do` forwards to `Dat.manager.do`. Import builds nothing; the first read of `Dat.manager` — any `do(…)`, `do.load`, `Dat.load` / `Dat.create` — runs `DatManager.load_dat_config()`: nearest `.datconfig.yaml` → a manager with `dt` / `dt.list` mounted, config folder first on `sys.path`. Assigning `Dat.manager` replaces the world. Contract: [[DAT API]].

| Table of Contents |  |
|---|---|
| **[[#Subsystems]]** |  |
| **[[#Overview]]** |  |
| **[[#Module grouping]]** |  |
| **[[#Process model]]** |  |
| **[[#Data flow]]** |  |
| **[[#Design decisions]]** |  |
| **[[#Open Questions]]** |  |
| **[[#See also]]** |  |

## Subsystems

| SUBSYSTEMS | Description |
| --- | --- |
| [DAT-Storage] | `Dat` · `DatContainer` · `DatManager` · `expand` / `expand_spec` / `merge_dicts` — folders with `_spec_.yaml` + `_result_.yaml`, placement, `dat.kind` dispatch, the `{}` grammar, the run (`execute`), artifacts and dependency capture |
| [DAT-Do] | `Do`: mounted names, then plain import; `dat.base`; the fork rule; `Dat.do` the forwarder to the default world's |
| [DAT-CLI] | `cli_main` behind the `dat` console script, `python -m dvc_dat` and a program's own main; the `bin/dat` bootstrap; `dat_tools` mounted as `dt` |

## Overview

`dvc_dat` 2.16.0: five Python modules (≈2 960 lines) plus the 72-line `sh` bootstrap `bin/dat`, 316 tests, public on GitHub, one live consumer ([[SVP]]). Three kinds of name: a **dotted name** (`catalog.experiment`) is a `do.mount` name, else the longest importable prefix plus `getattr`; a **slash path** (`runs/exp1`) is a dat folder — absolute, a mounted `<name>/_spec_`, or under one of the manager's dat folders; an **artifact name** (`games/G1/video`) is an artifact under the manager's artifact folder, in the same namespace as the dats, and a **URN** (`sha256:<hex>`) reaches either through the store's one index. A dat's `_spec_.yaml` is its complete, argumentless recipe, expanded once at create and never rewritten; `_result_.yaml` is the only mutable file, and a run writes `dat.dependencies` into it; the run itself (clock, host, code, scratch) is the sub-dat `run/`, outside the dat's hash (3.0). Call-site arguments never ride beside a spec: `do(template, *args, **kwargs)` writes them into a new spec (`args` replace `dat.args`, `kwargs` merge into `dat.kwargs`), creates that dat and runs it bare.

## Module grouping

| Module | Subsystem | Holds |
| --- | --- | --- |
| `dvc_dat/core.py` (1748) | Storage | `merge_dicts`; config reading (`_find_file_up`, `_read_config`); the `dat.*` and standing constants and the `_recording` context var; hashing, `_code_of`, `_standing_of`; `expand`, `expand_spec`; `DatManager` (471–1376), with the index (`_read_index`, `_index_update`, `reindex`); `_DatMeta` (`Dat.manager`), `Dat`, `DatContainer`; `_dotted_get` / `_dotted_set` |
| `dvc_dat/do.py` 1–481 | Do | `Do`: `__call__`, `load`, `name_of`, `keys`, `mount`, `manager`; `_refuse_import_clash`; the folder indexer; file and module loaders; `_DefaultDo` and `do` |
| `dvc_dat/do.py` 483–742 | CLI | `USAGE`, `cli_main`, `_do_argv`, `_parse_argv`; the flags `--list` · `--info` · `--version` |
| `dvc_dat/dat_tools.py` (370) | CLI | `Cube`, `from_dat`, `to_excel`, `dat_report`, `cmd_list`; imports `pandas` and `numpy` at the top |
| `dvc_dat/__main__.py` (7) | CLI | `python -m dvc_dat` → `cli_main()` |
| `dvc_dat/__init__.py` | — | `__version__ = "2.16.0"`; exports `Dat DatContainer DatManager Do` — the rest hangs off `Dat` (`Dat.do`, `Dat.cli_main`, `Dat.merge_dicts`) |
| `bin/dat` (72, `sh`) | CLI | nearest `.datconfig.yaml` (exit 3 if none) → first of `$DAT_RUN`, `run:`, `.venv/bin/python -m dvc_dat`, `python3 -m dvc_dat`; exports `DAT_CLI_CONFIG`, prepends the config folder to `PYTHONPATH`, `exec`s |

`pyproject` `[project.scripts]`: `dat = "dvc_dat.do:cli_main"`. Runtime deps `pandas`, `pyyaml`; `xlsxwriter` is the `excel` extra. Subsystem boundary ≠ file boundary: `do.py` holds Do and CLI (D1).

## Process model

Single process, no daemon; recording is per thread and per task. `do = _DefaultDo()` is built at import and holds nothing; `core._default_manager` is `None`. The first read of `Dat.manager` (through `_DatMeta`) runs `DatManager.load_dat_config()`: walk up from `Path.cwd()` for `.datconfig.yaml` and `.datconfig.override.yaml`, precedence file < override < `DAT_FOLDERS` / `DAT_ART_FOLDER`; with no file, `data/` under the working directory. Assigning `Dat.manager` — by hand, or `cli_main(config=…)` / `DAT_CLI_CONFIG`, which build with `do=dvc_dat.do` and so keep the program's mounts — replaces the world and re-binds its `do` to it. Caches: `Do._base_objects` (a mounted base loads once), `DatManager._dat_cache` (a `WeakValueDictionary` by absolute path). Recording: `_recording`, a `ContextVar` holding a stack of `(manager, dat)`; `execute` pushes, every `load` / `save` writes into the top dat's `dat.dependencies`, the pop records the dat into the one below. From a shell, `bin/dat` adds one `exec`: the `run:` command reaches `cli_main()`, which builds the default world from `DAT_CLI_CONFIG`; the console script `dat` is `cli_main` itself — no `run:`, no project mounts.

## Data flow

| Flow | Path through the code |
| --- | --- |
| run a template | `do(name, *a, **kw)` → `Dat.manager.do` → `load` → `_fork_spec` → `_dat_from_template` → `_resolve_base` → `use` and present: `manager.load`, no run; else `manager.create` → `manager.execute`: inside `recording(dat)`, `fn(dat, *dat.args, **dat.kwargs)` with `run/work/` as cwd; `dependencies` into results, `run_at` / `run_time` / `host` / `pid` / `code` / `content` into the `run/` sub-dat, `save()` |
| re-run · fork a Dat | `do(dat)` → `execute` in place · `do(dat, **kw)` → copy of `get_spec()`, `target_exists` `error` → `increment`, then as above; lands at `<name>_2` |
| call | `do(callable_or_name, *a, **kw)` → `fn(*a, **kw)`; no dat, no manager needed |
| create | `Dat.create(path, spec)` → `Dat.manager.create`: dotted `spec` → `do.load`; `_resolve_base`; `_class_of(dat.kind)` → `validate_spec`; `_place` (template, `target_exists`, `{unique}` count-up) → `expand_spec` with the same `now` / `unique` → `dat.name` := landed name → `_spec_.yaml` → `_load` |
| load | `manager.load(name)` → `_locate`: a URN → the index; an artifact name → the index, else its folder → `_load_artifact` (sidecar → `do.load(type)(path)`, or the `Path`); both → `ValueError`; else `_resolve_path` (absolute → mounted `<name>/_spec_` → each dat folder) → `_spec_.yaml`, else `.json` → `_class_of(dat.kind)` → `validate_spec` → `_result_.yaml` → cache; recorded when a dat is recording |
| save an artifact | `Dat.save_artifact` → `manager.save_artifact(src, type=, name=)` → `_type_name` (dotted, checked to load back) → hash the source → under `_index_update`: name free? → URN held: `_add_name`, nothing copied; else copy → `_art_.yaml` → index both keys → recorded |
| resolve a name | `do.load` → mounted value by exact name → mounted base (module attr, dict key path, longest folder-path prefix) → `_load_static`: longest importable prefix + `getattr` → raw `ImportError` / `AttributeError` / `KeyError` unless `default` |
| mount | `do.mount` → `_refuse_import_clash` (real paths) → `_reg_module` / `_reg_value`; a folder indexes by relative path under `at` |
| CLI | `dat T a k=v --set x=y` → `cli_main` → `_do_argv` → `_parse_argv` (YAML scalars) → `do.load(T)`: dict → `merge_dicts(_resolve_base(T), overrides)` → `do(spec, …)`; callable → `do(T, …)`; else print. Exit 0 / 1 / 2 |
| report | `dat_report(spec)` → `Cube(dats, point_fns)` → `Dat.load` per folder → `DataFrame` → `to_excel` |

## Design decisions

| # | Decision (observed in code) |
| --- | --- |
| D1 | `do.py` imports `core` at the top; `core` reaches `do.py` by function-local imports (`Do` in the constructor, the default `do` for module-level `{a.b}`). A manager's own steps go through `self.do`, never the global |
| D2 | Two namespaces: dotted = code, templates and artifact types; slash = dats and artifacts, one namespace, plus the `sha256:` URN of each. A dotted name reaches a dat folder only through a mounted `<name>/_spec_` |
| D3 | The spec on disk is a record: `dat.base` merged then dropped, every `{}` expanded once at create with the folder's own `now` / `unique`, `dat.name` set to the landed name; nothing expands on read, nothing rewrites `_spec_.yaml` |
| D4 | Fork rule: call-site arguments always make a new spec; `_result_.yaml` holds what the function stored plus `dependencies`, never arguments; the run's `run_at` / `run_time` / `code` live in the `run/` sub-dat (3.0) |
| D5 | A dotted name is a mount, else a plain Python import (`import_module` returns what `sys.modules` holds). `mount` raises `ValueError` on a top-level name importable from outside the mounted source, compared as real paths |
| D6 | Import reads no filesystem; first use builds `Dat.manager`; the config folder is the import root (`sys.path[0]`) |
| D7 | `.datconfig.yaml` is six keys, `dat_folders`, `art_folder`, `index`, `manager`, `verify`, `run`; an unknown key is an error. Mounts are `do.mount(...)` calls in the program; the library never reads `run` — only `bin/dat` does |
| D8 | `dat.kind` is a dotted `module.qualname`, imported as pickle does; a bare pre-2.3 name falls back to the `Dat.__subclasses__()` walk. Validation is the `validate_spec` classmethod; no schema library |
| D9 | One object: the manager owns folders, cache, the index and its `Do`; `do` is its only public attribute. `Dat.manager` is a plain assignable class attribute (a `_DatMeta` property); `Dat.do` forwards to it; a bare `Do()` is a namespace that runs no dat |
| D10 | Dependencies by capture: a run's inputs are what it loaded through its manager (`recording`); artifacts are write-once, content-hashed and deduped, with no superclass — the type is a dotted name `do.load` resolves, called with the path; nothing is registered (2.14) |
| D11 | The artifact folder and the dat folders never nest (`ValueError`); a name is refused to a dat when an artifact holds it and the other way round; `load_dat_config` puts `art/` beside the config file, a hand-built manager has none unless given (2.5) |
| D12 | Every dat has a content hash: `save()` stamps `dat.sha256` over the whole folder, `_result_.yaml` counted with that field set to `excluded`; `verify()` recomputes it. A dependency is never `null` (2.9) |
| D13 | One field of standing, `dat.standing` (`rolling < open < sealed < referenceable` as a ladder), stamped by every save; a seal earns the least of its inputs, capped by its code; in a spec it is a demand (2.14) |
| D14 | One index file per store, keyed by name and URN, locked and replaced by rename; the folders stay the truth for a named artifact and `reindex` rebuilds the rest (2.14) |

## Open Questions

None open; parked: [[DAT P0001]] (required keys in a template).

## See also

- [[DAT API]] — the consumer contract and its four pages
- [[DAT Backlog#^T013|T013]] — the 2.2 cut (PRs #16–#18); [[DAT Backlog#^F019|F019]] — the 2.3 / 2.4 refactor (PRs #20, #21)
- [[SVP146 - DAT in SVP, the simple do, vendored|SVP F146]] — the consumer's ask
- https://github.com/oblinger/dvc-dat/blob/main/CHANGELOG.md — § 2.3.0 holds the removed-names table from 2.2, § 2.2.0 the one from 2.0 / 2.1
- `docs/*.md` in the repo — the public contract; kept in step with the code in the same PRs

# BRIEF

- 2026-09-23 — rebuilt for 2.4.0 from `main` at `c2dbdc6` (229 tests) after #20 and #21 merged ([[DAT Backlog#^F019|F019]]): one object instead of two singletons, `.datconfig.yaml`, artifacts and dependency capture; D9/D10 new, D1/D2/D6/D7/D8 restated; the figure's labels updated in place (layout unchanged).

- 2026-09-22 — renumbered: the 3.0.0 / 3.0.1 release is `v2.2.0` (PR #18), same code; the 3.x tags are withdrawn (Dan: a major twice in two hours makes no sense).
- 2026-09-21 — written by the DAT agent for [[DAT Backlog#^T001|T001]]'s architecture round, on Dan's ask of the same day (*"a top-level architecture, and a subpage off of that, DAT Interface"*). Ground truth was the code at `~/ob/proj/dvc-dat` commit `c2840fa` (1.1.0, 73 tests green), read in full.
- No module docs exist for this anchor, so the `architect` skill's staleness precondition (`module_docs_audited:`), its module-doc analysis step and the `Arch`-row reconciliation are skipped; the figure and tables are built from source. The Q.md post-condition is skipped too (no backlog row changed). No PRD exists yet — [[DAS Design Folder Facet]] requires one once `DAT Design/` exists.
- Subsystems are single-bracket placeholders (no subsystem docs); this stays the single-file form until one subsystem grows more than a table's worth of discussion.
- Figure: hand-written SVG beside this page (`DAT Architecture.svg`), per [[DAS Architecture Facet]] § Architecture diagram requirements; edit the XML directly.
- 2026-09-22 — rebuilt for 3.0.0 from `main` at `87cae11` (`dvc-dat 3.0.0 (#16)`, 175 tests green), every module plus `bin/dat`, `pyproject.toml` and CHANGELOG § 2.0.0–3.0.0 read in full; the figure redrawn to match. Everything 1.1.0 (`MethodManager`, `SimpleMethodManager`, `DoManager`, `DoProxy`, `do_fn.py`, `dat.py`, `mount_commands`, `do_argv`, the sync folder, pydantic specs, the alg2 tags) is gone from code and from this page; the old text is in `git show HEAD:` and md_history. `/architect update`'s `Versions/` snapshot, `/architect new` greenfield draft and `## Changes since` were not made: the rebuild is from code, not an integration of new ideas, and the caller fixed the section shape. The previous Open Questions (T001 Q1–Q5) were all decided in 2.0 ([[DAT Backlog#^F007|F007]] § Decisions).
