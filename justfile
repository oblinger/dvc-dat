# dvc-dat's verbs: thin wrappers over `uv run`.

# `run` and `mounts`, the recipes every project imports
import 'dvc_dat/dvc_dat.just'

# the test suite
test *ARGS:
    uv run python -m pytest -q {{ARGS}}

# the suite once per install tier (1519 R4): base (pyyaml alone), expand (omegaconf), every extra
test-tiers *ARGS:
    uv run --exact python -m pytest -q {{ARGS}}
    uv run --exact --extra expand python -m pytest -q {{ARGS}}
    uv run --exact --all-extras python -m pytest -q {{ARGS}}

# what CI runs: the three tiers, then the demo notebooks
ci *ARGS:
    just test-tiers {{ARGS}}
    just demo

# values sealed with v.seal() and never saved, kept or not: the listing, or `purge [older=14d]`
sealed *ARGS:
    uv run python -m dvc_dat.ledger.kept {{ARGS}}

# the demo notebooks (doc/DAT Demos): each notebook generated from its py:percent script by build_notebook.py,
# with cell ids a re-run leaves alone, then executed in place with its outputs kept. Edit the .py, never the
# .ipynb. tests/test_demo_notebooks.py runs them and checks the pairing on every `just test`.
demo:
    for stem in cli-walkthrough demo-dats demo-etl demo-rerunning demo-walkthrough ledger-triples ledger-values ledger-dats ledger-just; do uv run python "doc/DAT Demos/build_notebook.py" $stem && JUPYTER_PATH={{justfile_directory()}}/.venv/share/jupyter uv run jupyter nbconvert --execute --to notebook --inplace "doc/DAT Demos/$stem.ipynb" || exit 1; done

# the API walkthrough: its notebook generated from api-walkthrough.py, with cell ids that a re-run leaves
# alone, then executed in place with its outputs kept. Edit the .py, never the .ipynb.
walkthrough:
    uv run python "doc/DAT Demos/build_notebook.py" api-walkthrough
    JUPYTER_PATH={{justfile_directory()}}/.venv/share/jupyter uv run jupyter nbconvert --execute --to notebook --inplace "doc/DAT Demos/api-walkthrough.ipynb"

# the documentation site (doc/ -> site/), with the generated API reference (doc/api/) and cli.md's usage block;
# `just docs check` leaves the tracked files alone and fails on a stale block, a strict-build warning or a site test
docs *mode:
    uv run --group docs python doc/sync_cli_usage.py {{ if mode == "check" { "--check" } else { "" } }}
    uv run --group docs mkdocs build --strict
    {{ if mode == "check" { "uv run --group docs python -m pytest -q tests/test_docs_site.py" } else { "" } }}

# the documentation site, served with live reload
docs-serve:
    uv run --group docs mkdocs serve
