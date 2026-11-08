"""SVP 1508, on the `${…}` grammar (1519 R3): the keywords of `run` and `create` merge into `dat.kwargs` as data, a
template names the node it reads (`${dat.kwargs.game}`), `dat.defaults` is a plain node (`${dat.defaults.x}`;
kwargs over defaults is `oc.select`); `dat.preds` is a map of pred names to templates, resolved at create and
carried as the dat's own preds."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("omegaconf")

from dvc_dat import Dat, DatManager  # noqa: E402

FP = {"dat": {"name": "fp/${dat.kwargs.pipe}/${dat.kwargs.card}/${dat.kwargs.game}"
                      "${oc.select:dat.kwargs.posture,${dat.defaults.posture}}",
              "defaults": {"posture": ""},
              "preds": {"card": "${dat.kwargs.card}", "game": "${dat.kwargs.game}",
                        "made": "${dat.kwargs.pipe}-${dat.kwargs.card}"}}}


@pytest.fixture
def m(tmp_path):
    manager = DatManager(dat_folders=[str(tmp_path / "dats")])
    manager.ns.mount(at="echo", value=lambda dat, **k: {"name": dat.get_path_name(), "kwargs": k})
    return manager


def on_disk(dat):
    return yaml.safe_load(Path(dat.get_path(), "_spec_.yaml").read_text())


def test_create_keywords_fill_the_name_and_the_preds(m):
    dat = m.create(FP, pipe="1-3-5", card="h100", game="G1")
    assert dat.get_path_name() == "fp/1-3-5/h100/G1"
    spec = on_disk(dat)["dat"]
    assert spec["name"] == FP["dat"]["name"]                                   # the template is stored
    assert spec["kwargs"] == {"pipe": "1-3-5", "card": "h100", "game": "G1"}
    assert spec["preds"] == {"card": "h100", "game": "G1", "made": "1-3-5-h100"}
    assert dict(dat.preds) == {"pipe": "1-3-5", "card": "h100", "game": "G1", "made": "1-3-5-h100"}
    assert dat.run is None                                                     # create runs nothing


def test_a_keyword_overrides_a_default_through_oc_select(m):
    dat = m.create(FP, pipe="1-3-5", card="h100", game="G1", posture="-highlights")
    assert dat.get_path_name() == "fp/1-3-5/h100/G1-highlights"


def test_the_specs_own_kwargs_are_nodes_and_a_keyword_wins(m):
    spec = {"dat": {"name": "out/${dat.kwargs.x}-${dat.kwargs.y}", "kwargs": {"x": 1, "y": 2}}}
    assert m.create(spec, y=3).get_path_name() == "out/1-3"


def test_a_spec_kwarg_is_the_value_the_run_receives(m):
    spec = {"dat": {"name": "out/${dat.kwargs.when}", "kwargs": {"when": "${now:%Y}"}}}
    dat = m.create(spec)
    assert dat.get_path_name() == f"out/{on_disk(dat)['dat']['kwargs']['when']}"
    assert on_disk(dat)["dat"]["kwargs"]["when"].isdigit()


def test_a_keyword_is_data_in_the_kwargs_and_fills_a_name_as_given(m):
    dat = m.create({"dat": {"name": "out/${dat.kwargs.tag}", "preds": {"tag": "${dat.kwargs.tag}"}}},
                   tag="a${b}")
    assert dat.get_path_name() == "out/a${b}"
    assert on_disk(dat)["dat"]["kwargs"] == {"tag": "a${b}"} and dat.preds["tag"] == "a${b}"


def test_run_fills_the_same_way_and_runs(m):
    out = m.run({"dat": {"do": "echo", "name": "runs/${dat.kwargs.game}"}}, game="G4")
    assert out == {"name": "runs/G4", "kwargs": {"game": "G4"}}


def test_the_rest_of_the_spec_reads_the_defaults(m):
    dat = m.create({"dat": {"defaults": {"game": "G1"}}, "title": "fingerprint of ${dat.defaults.game}"}, path="t")
    assert on_disk(dat)["title"] == "fingerprint of G1"


def test_a_missing_node_is_one_clear_error(m):
    from omegaconf.errors import InterpolationKeyError

    with pytest.raises(InterpolationKeyError, match="nope"):
        m.create({"dat": {"name": "out/${dat.kwargs.nope}"}})


def test_bad_preds_are_refused(m):
    with pytest.raises(TypeError, match="dat.preds"):
        m.create({"dat": {"preds": ["x"]}}, path="b")
    with pytest.raises(ValueError, match="db/"):
        m.create({"dat": {"preds": {"db/fn": "x"}}}, path="c")
    with pytest.raises(TypeError, match="dat.preds"):
        m.create({"dat": {"preds": {"cfg": "${dat.kwargs.cfg}"}, "kwargs": {"cfg": {"a": 1}}}}, path="d")


def test_dat_create_takes_keywords_in_the_default_world(m):
    from dvc_dat import core

    before = core._default_manager
    Dat.manager = m
    try:
        dat = Dat.create(FP, pipe="0-1-0", card="l4", game="G5")
        assert dat.get_path_name() == "fp/0-1-0/l4/G5" and dat.preds["card"] == "l4"
    finally:
        core._default_manager = before
        if before is not None:
            Dat.manager = before
