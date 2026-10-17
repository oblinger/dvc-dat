"""The dats-demo kinds (doc/demo/demo_kinds/compute.py): Numbers seals a list; Compute evaluates over dats and records what it loaded."""

import sys
from pathlib import Path

import pytest

from dvc_dat import Dat, DatManager

sys.path.insert(0, str(Path(__file__).parent.parent / "doc" / "demo"))
from demo_kinds.compute import Compute, Numbers, evaluate  # noqa: E402


@pytest.fixture
def store(tmp_path):
    before = Dat.manager
    Dat.manager = DatManager(dat_folders=[str(tmp_path / "dats")], art_folder=str(tmp_path / "art"))
    yield Dat.manager
    Dat.manager = before


def test_numbers_seals_its_list(store):
    a = Numbers.make("demo/a", [1, 2, 3])
    assert a.values() == [1, 2, 3]
    assert store.load("demo/a").values() == [1, 2, 3]
    assert a.get_results()["dat"]["sha256"]


def test_compute_records_its_loads_two_deep(store):
    Numbers.make("demo/a", [1, 2, 3])
    Numbers.make("demo/b", [10, 20, 30])
    c = Compute.make("demo/c", ["+", "demo/a", "demo/b"])
    assert c.values() == [11, 22, 33]
    deps = Dat.get(c.get_results(), "dat.dependencies")
    assert set(deps) == {"demo/a", "demo/b"}
    d = Compute.make("demo/d", ["*", "demo/c", ["+", "demo/a", "demo/a"]])
    assert d.values() == [22, 88, 198]
    # the seal keeps the roots: demo/a is reached through demo/c, so it is not repeated
    assert set(Dat.get(d.get_results(), "dat.dependencies")) == {"demo/c"}
    through_c = Dat.get(store.load("demo/c").get_results(), "dat.dependencies")
    assert set(through_c) == {"demo/a", "demo/b"}


def test_a_sealed_dat_refuses_a_write(store):
    a = Numbers.make("demo/a", [1, 2])
    with pytest.raises(RuntimeError):
        a.write_channel("values", [])


def test_evaluate_refuses_a_bad_expression(store):
    Numbers.make("demo/a", [1, 2])
    Numbers.make("demo/b", [1, 2, 3])
    with pytest.raises(ValueError):
        evaluate(["-", "demo/a"])
    with pytest.raises(ValueError):
        evaluate(["+", "demo/a", "demo/b"])
