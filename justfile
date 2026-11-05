# dvc-dat's verbs: thin wrappers over `uv run`.

# `run` and `mounts`, the recipes every project imports
import 'dvc_dat/dvc_dat.just'

# the test suite
test *ARGS:
    uv run python -m pytest -q {{ARGS}}

# values sealed with v.seal() and never saved, kept or not: the listing, or `purge [older=14d]`
sealed *ARGS:
    uv run python -m dvc_dat.ledger.kept {{ARGS}}

# the demo notebooks (doc/DAT Demos): each .ipynb is paired by jupytext with a
# py:percent script beside it (edit either); sync the pairs, then execute each
# notebook in place with its outputs kept. tests/test_demo_notebooks.py runs
# them and checks the pairing on every `just test`.
demo:
    uv run jupytext --sync "doc/DAT Demos"/demo-*.ipynb "doc/DAT Demos"/demo-*.py
    for nb in "doc/DAT Demos"/demo-*.ipynb; do JUPYTER_PATH={{justfile_directory()}}/.venv/share/jupyter uv run jupyter nbconvert --execute --to notebook --inplace "$nb"; done

# the API walkthrough: its notebook generated from api-walkthrough.py, with cell ids that a re-run leaves
# alone, then executed in place with its outputs kept. Edit the .py, never the .ipynb.
walkthrough:
    uv run python "doc/DAT Demos/build_notebook.py" api-walkthrough
    JUPYTER_PATH={{justfile_directory()}}/.venv/share/jupyter uv run jupyter nbconvert --execute --to notebook --inplace "doc/DAT Demos/api-walkthrough.ipynb"

# the documentation site (doc/ -> site/), with the generated API reference (doc/api/)
docs:
    uv run --group docs mkdocs build

# the documentation site, served with live reload
docs-serve:
    uv run --group docs mkdocs serve
