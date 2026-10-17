# dvc-dat's verbs: thin wrappers over `uv run`.

# the test suite
test *ARGS:
    uv run python -m pytest -q {{ARGS}}

# the demo notebooks (doc/demo): each .ipynb is paired by jupytext with a
# py:percent script beside it (edit either); sync the pairs, then execute each
# notebook in place with its outputs kept. tests/test_demo_notebooks.py runs
# them and checks the pairing on every `just test`.
demo:
    uv run jupytext --sync doc/demo/demo-*.ipynb doc/demo/demo-*.py
    for nb in doc/demo/demo-*.ipynb; do JUPYTER_PATH={{justfile_directory()}}/.venv/share/jupyter uv run jupyter nbconvert --execute --to notebook --inplace "$nb"; done

# the documentation site (doc/ -> site/)
docs:
    uv run --with mkdocs-material mkdocs build
