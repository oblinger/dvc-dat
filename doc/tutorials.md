# Tutorials
Ten notebooks, each run end to end with its outputs kept. Read them in this order, or run them: `just walkthrough` (the API walkthrough), `just demo` (the rest); VS Code opens the repo folder and takes its `.venv` kernel.

| Notebook | What it runs | Read it when |
| --- | --- | --- |
| [API walkthrough](DAT%20Demos/api-walkthrough.ipynb) | dats, the namespace, values, the ledger: the one API sheet | first |
| [CLI walkthrough](DAT%20Demos/cli-walkthrough.ipynb) | `just run` and the ledger verbs, each beside the call it makes | you work from a shell |
| [A project end to end](DAT%20Demos/demo-walkthrough.ipynb) | mounts, `dat.base`, run and fork, load, the command-line main | starting a project |
| [Dats and dependencies](DAT%20Demos/demo-dats.ipynb) | seal, hash, dependencies two deep | before depending on a dat |
| [An ETL chain](DAT%20Demos/demo-etl.ipynb) | a chain over a game set; what each change recomputes | building a pipeline |
| [Rerunning](DAT%20Demos/demo-rerunning.ipynb) | today's code over past revisions, a sweep of them, a value's own commit again | reproducing a past execution |
| Ledger: [triples](DAT%20Demos/ledger-triples.ipynb) · [values](DAT%20Demos/ledger-values.ipynb) · [dats](DAT%20Demos/ledger-dats.ipynb) · [just](DAT%20Demos/ledger-just.ipynb) | the ledger from quads to the human's verbs, four notebooks | reaching for history, memoization, provenance |

A task: [How-to](how-to.md). The model: [Architecture](DAT%20Architecture.md). A name: [API Reference](api/index.md).
