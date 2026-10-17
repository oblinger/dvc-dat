"""The ETL-demo kinds (doc/DAT Demos/demo_kinds/etl.py): gamey -> binning -> trial -> metrics, each sealed over the one below."""

import statistics
import sys
from pathlib import Path

import pytest

from dvc_dat import Dat, DatManager

sys.path.insert(0, str(Path(__file__).parent.parent / "doc" / "DAT Demos"))
from demo_kinds.etl import Binning, Gamey, Metrics, Trial  # noqa: E402


@pytest.fixture
def store(tmp_path):
    before = Dat.manager
    Dat.manager = DatManager(dat_folders=[str(tmp_path / "dats")], art_folder=str(tmp_path / "art"))
    yield Dat.manager
    Dat.manager = before


def deps(dat):
    """The inputs a seal recorded, less ``$MANUAL`` (dvc-dat's mark for a dat sealed by hand, not by a run;
    it survives the trim to roots only where no input carries it)."""
    return set(Dat.get(dat.get_results(), "dat.dependencies")) - {"$MANUAL"}


@pytest.fixture
def chain(store):
    for g in ("G1", "G2", "G3"):
        Gamey.make(f"gamey/{g}", n=200, seed=int(g[1:]))
    b = Binning.make("binning/b", ["gamey/G1", "gamey/G2"], bins=8, trim=0.05)
    r = Trial.make("trial/r", "gamey/G3", "binning/b")
    m = Metrics.make("metrics/m", "trial/r")
    return b, r, m


def test_gamey_is_reproducible_by_seed(store):
    a = Gamey.make("gamey/a", n=50, seed=7)
    b = Gamey.make("gamey/b", n=50, seed=7)
    c = Gamey.make("gamey/c", n=50, seed=8)
    assert a.values() == b.values() != c.values()
    assert len(a.values()) == 50 and all(0 <= v <= 999 for v in a.values())
    assert store.load("gamey/a").values() == a.values()


def test_binning_edges_are_monotone_and_trimmed(chain, store):
    b, _, _ = chain
    edges = store.load("binning/b").edges()
    assert len(edges) == 9 and edges == sorted(edges) and edges[0] < edges[-1]
    pooled = sorted(store.load("gamey/G1").values() + store.load("gamey/G2").values())
    k = int(len(pooled) * 0.05)
    assert (edges[0], edges[-1]) == (pooled[k], pooled[-k - 1])
    assert b.kwargs() == {"games": ["gamey/G1", "gamey/G2"], "bins": 8, "trim": 0.05}


def test_a_trial_places_every_value_and_crowns_three_bins(chain, store):
    _, r, _ = chain
    table = r.table("placements")
    assert table["value"].to_list() == store.load("gamey/G3").values()
    assert all(0 <= b < 8 for b in table["bin"].to_list())
    assert all(0.0 <= x < 1.0 for x in table["residual"].to_list())
    podium = store.load("trial/r").get_results()["podium"]
    assert len(set(podium)) == 3
    counts = [table["bin"].to_list().count(b) for b in podium]
    assert counts == sorted(counts, reverse=True)


def test_metrics_mean_is_the_mean_of_the_values(chain, store):
    _, _, m = chain
    res = store.load("metrics/m").get_results()
    values = store.load("gamey/G3").values()
    assert res["mean"] == pytest.approx(statistics.fmean(values))
    assert (res["min"], res["max"]) == (min(values), max(values))
    assert 0.0 <= res["residual"]["min"] <= res["residual"]["mean"] < 1.0
    assert res["residual"]["spread"] > 0


def test_each_stage_depends_on_exactly_its_inputs(chain, store):
    b, r, m = chain
    assert deps(b) == {"gamey/G1", "gamey/G2"}
    assert deps(r) == {"gamey/G3", "binning/b"}   # not the binning's games
    assert deps(m) == {"trial/r"}


def test_a_game_inside_the_binning_is_reached_through_it(chain, store):
    # the seal keeps the roots: G1 is already below the binning, so a trial of G1 lists the binning alone
    assert deps(Trial.make("trial/g1", "gamey/G1", "binning/b")) == {"binning/b"}
