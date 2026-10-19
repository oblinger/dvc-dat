"""``load``-marked tests run only when asked: ``pytest -m load``."""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "load: the multiprocess ledger load harness (run with -m load)")


def pytest_collection_modifyitems(config, items):
    if "load" in (config.option.markexpr or ""):
        return
    skip = pytest.mark.skip(reason="load harness: run with -m load")
    for item in items:
        if "load" in item.keywords:
            item.add_marker(skip)
