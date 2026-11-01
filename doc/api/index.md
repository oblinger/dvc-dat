# API Reference
The reference generated from `dvc_dat`'s source: every public class and function, with its signature and docstring.

These pages are built from the code, so they always say what the installed version does. The hand-written guides say why and show the calls together: [Overview](../overview.md) (what the package exports), [Concepts](../concepts.md), [Spec Format](../spec-format.md), [Command Line](../cli.md).

| Page | What it covers |
|------|----------------|
| [Dat, DatManager, DatContainer](core.md) | `dvc_dat.core`: the dat folder, the manager that creates, loads and runs dats, and the `{}` grammar (`expand`, `expand_spec`, `merge_dicts`) |
| [Namespace](do.md) | `dvc_dat.do`: `ns`, dotted names to objects, mounts, and `cli_main`, the command line |
| [Ledger](ledger.md) | `dvc_dat.ledger`: `Ledger`, `Rev`, `Transaction`, `Value`, `ledger_fn`, the active ledger `L` and `ledgers`, the release helpers, the errors |
| [Commands](just.md) | `dvc_dat.just`: `@command`, the declared commands that become `just <name>` recipes |
| [Dat tools](dat_tools.md) | `dvc_dat.dat_tools`, mounted as `dt`: listing dats and reporting over them |

**How it is built.** `just docs` runs `mkdocs build` with the [mkdocstrings](https://mkdocstrings.github.io/) plugin, which imports nothing: it reads the source statically (griffe) and renders each `::: dvc_dat.<name>` directive in these pages. `just docs-serve` serves the site with live reload. Names starting with an underscore are left out.
