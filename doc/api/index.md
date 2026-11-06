# API Reference
The reference generated from `dvc_dat`'s source: every public class and function, with its signature and docstring.

![The dat and the ledger](../DAT%20Architecture.svg)

Module page: [DAT Architecture](../DAT%20Architecture.md).

These pages are built from the code, so they always say what the installed version does. The hand-written guides say why and show the calls together: [Concepts](../concepts.md), [Spec Format](../spec-format.md), [Command Line](../cli.md).

## What the package exports

```python
from dvc_dat import Dat, DatContainer, DatManager, Namespace, L, ledgers

ns = Dat.ns     # the namespace shortcut; follows Dat.manager
```

| Name | What it is |
|------|------------|
| `Dat` | A dat folder: its spec, its results, its path |
| `DatContainer` | A dat whose folder holds other dats |
| `DatManager` | Creates, finds, loads and runs dats; `Dat.manager` is the default, assign to replace |
| `Namespace` | A namespace; every manager has one |
| `L` | The active ledger: `DAT_LEDGER`, else the config's `ledgers:` default or `ledger:` |
| `ledgers` | The project's ledgers by name: `ledgers.<name>`, `ledgers["do26"]` |

Everything else hangs off those four classes:

| Name | What it is |
|------|------------|
| `Dat.ns` | The default world's namespace, forwarding to `Dat.manager.ns`; not callable |
| `Dat.cli_main` | The command line (`just run`) for a program's own main |
| `Dat.merge_dicts` | The zipper merge `dat.base` uses |
| `ns.expand` / `expand_spec` / `quote_spec` | The `{}` grammar, a method of every namespace |

## The pages

| Page | What it covers |
|------|----------------|
| [Dat, DatManager, DatContainer](core.md) | `dvc_dat.core`: the dat folder, the manager that creates, loads and runs dats, and `merge_dicts`; the `{}` grammar is `Namespace.expand` |
| [Namespace](do.md) | `dvc_dat.do`: `ns`, dotted names to objects, mounts, and `cli_main`, the command line |
| [Ledger](ledger.md) | `dvc_dat.ledger`: `Ledger`, `Rev`, `Transaction`, `Value`, the decorators `dat.fn`, `dat.warm`, `dat.command`, pin and rerun, the active ledger `L` and `ledgers`, the release helpers, the errors |
| [Commands](just.md) | `dvc_dat.just`: `@dat.command`, the declared commands that become `just <name>` recipes |
| [Dat tools](dat_tools.md) | `dvc_dat.dat_tools`, mounted as `dt`: listing dats and reporting over them |

**How it is built.** `just docs` runs `mkdocs build` with the [mkdocstrings](https://mkdocstrings.github.io/) plugin, which imports nothing: it reads the source statically (griffe) and renders each `::: dvc_dat.<name>` directive in these pages. The plugin `dat-vault` (`dvc_dat.docs.vault`, on the `mkdocs.plugins` entry point) renders the Obsidian vault grammar these pages share with `doc/` and expands a module page's `<!-- methods: pkg.Class -->` into its table: a repo on `dvc_dat` loads it with `plugins: - dat-vault`, options `packages`, `api_dir`, `repo_blob`. `just docs-serve` serves the site with live reload. Names starting with an underscore are left out.
