---
description: "the Python API + CLI a consumer codes against"
---
:>> [DAT](ha://DAT) → [DAT Archive](ha://DAT%20Archive) → [DAT Interface](ha://p/DAT%20Interface) 
# DAT Interface
`dvc_dat` 2.7.0 — what a consumer may rely on; a change to any row is a major version.

| Surface | Contract | Spec |
| --- | --- | --- |
| Imports | `Dat` `DatContainer` `DatManager` `Do` `do` `cli_main` `expand` `expand_spec` `merge_dicts`, `__version__`; nothing else | [[DAT Class API]] |
| `do(target, …)` | callable → plain call; template → fork, create, run; `Dat` → re-run bare, fork with arguments | [[DAT Class API#Running]] |
| Dats | `Dat.create` · `Dat.load` · the instance methods · `Dat.get` / `set` · `validate_spec` · `DatContainer`; `dat.kind` a dotted class path | [[DAT Class API#Dat Interface]] |
| Manager | `DatManager(*, dat_folders, art_folder, do)` · `load_dat_config` · `create` `load` `exists` `execute` `expand` `expand_spec` · `save` `register_artifact` `recording` `record_dependency`; `do` its one attribute; `Dat.manager` the assignable default | [[DAT Manager API]] |
| Artifacts | `art:<kind>/<rest>` names; write-once, `<art_folder>/<kind>/<rest>/` with `_art_.yaml` (`kind` `name` `payload` `sha256` `saved_at`) | [[DAT Manager API#Artifacts on disk]] |
| `_spec_.yaml` · `_result_.yaml` | the `dat.*` keys, the rest yours; expanded once at create, never rewritten · results + `dat.run_at` / `run_time` / `code` / `dependencies`, no arguments | [[DAT Class API]] |
| `.datconfig.yaml` | `dat_folders`, `art_folder` (beside, never nested), `run`; unknown key an error; read by `DatManager.load_dat_config`, first use builds `Dat.manager` | [[DAT Class API]] |
| Names | `do.load`: a mount, else a Python import; `do.name_of`; `do.mount`; `do.keys` | [[DAT Do API]] |
| Shell | `dat TARGET [ARG …] [KEY=VALUE …]`, `--set K=V` `--json K=JSON` (each repeatable) `--dry-run` `--usage`, `--list` `--info` `--version` (flags; no reserved words); exit 0 / 1 / 2; `bin/dat` execs `run:` | [[DAT CLI]] |
| `dt` | `dvc_dat.dat_tools`, mounted in every manager's `do`: `Cube` `from_dat` `to_excel` `dat_report` `dt.list` | repo `docs/overview.md` |

Every signature, default and example is on [[DAT API]] and its four pages.

Not contract: any `_name` (a manager's folders are private). From 2.2: the removed-names table in https://github.com/oblinger/dvc-dat/blob/main/CHANGELOG.md § 2.3.0; from 2.0 / 2.1: § 2.2.0.

## Code vs docs

Repo `docs/*.md` against `main` at `v2.4.0`: none known; they were rewritten in the same PRs as the code (#20, #21).

The vault API pages match the code: the manager's public surface on `v2.4.0` is exactly the [[DAT Manager API]] table (checked 2026-09-23).

# BRIEF

- 2026-09-21 — written by the DAT agent with [[DAT Architecture]] for [[DAT Backlog#^T001|T001]] as the full 1.1.0 contract (every public name, the alg2-legacy tags, nine code-vs-docs rows), from `c2840fa`. That text is in `git show HEAD:` / md_history; the alg2 names and every 1.1.0 row are gone from the code, so [[DAT001 - The SVP semantics change what dvc-dat must mean differently, designed|T001]] and [[DAT007 - dvc-dat 2.0 argumentless specs that fork, one dat.do, one expander, alg2 pruned|F007]] link a `#alg2-legacy` heading that no longer exists — historical, left.
- 2026-09-22 — rewritten for 3.0.0 from `main` at `87cae11` (175 tests) as the one-screen contract: the detail moved to [[DAT API]], [[DAT Class API]], [[DAT Do API]], [[DAT CLI]] in 2.0 and is not repeated here. Code vs docs re-derived by reading `docs/*.md` and `README.md` against the code; the value-mount and function-reference rows were confirmed by running them. Each row is a docs fix in the repo (not made — this pass edits no code repo); if the value-mount one is meant to work, it is a code change in `Do._load_mounted`, a minor version.
- 2026-09-23 — brought to 2.4.0 after #20 and #21 merged ([[DAT Backlog#^F019|F019]]): `DataConfig` and `configure` rows gone, Manager and Artifacts rows added.
