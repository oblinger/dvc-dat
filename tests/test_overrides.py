"""The command line's overrides (1519 R5): `KEY=VALUE` on every install, Hydra's override grammar with
dvc-dat[hydra] (`+`, `++`, `~`, choices, sweeps, `-m`), each sweep point one spec, one dat."""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dvc_dat import DatManager
from dvc_dat.do import apply_overrides, needs_hydra, parse_overrides

ROOT = Path(__file__).resolve().parent.parent


def test_which_words_need_hydras_grammar():
    for word in ("+horizon=3", "++x=1", "~note", "-m", "--multirun"):
        assert needs_hydra(word), word
    for word in ("game=G1,G4", "r=range(1,3)"):
        assert needs_hydra(word, multirun=True) and not needs_hydra(word), word    # a sweep only under -m
    for word in ("game=G1", "tags=[1,2]", 'cfg={"a":1,"b":2}', "pattern=\\d{3}", "m=${ns:asset.ocr}", "q='a,b'"):
        assert not needs_hydra(word, multirun=True), word


def test_base_overrides_are_todays_key_value():
    (point,) = parse_overrides(["game=G1", "n=7", "tags=[1,2]", "dat.title=T", "m=${ns:a.b}"])
    assert [(o.path, o.value) for o in point] == [
        (["dat", "kwargs", "game"], "G1"), (["dat", "kwargs", "n"], 7), (["dat", "kwargs", "tags"], [1, 2]),
        (["dat", "title"], "T"), (["dat", "kwargs", "m"], "${ns:a.b}")]


def test_apply_sets_adds_and_deletes():
    spec = {"dat": {"kwargs": {"game": "G0"}}, "p": {"x": 1}}
    (point,) = parse_overrides(["game=G1", "p.y=2", "dat.title=T"])
    assert apply_overrides(spec, point) == {"dat": {"kwargs": {"game": "G1"}, "title": "T"}, "p": {"x": 1, "y": 2}}
    assert spec == {"dat": {"kwargs": {"game": "G0"}}, "p": {"x": 1}}                 # the input is not touched
    with pytest.raises(ValueError, match="not a mapping"):
        apply_overrides(spec, parse_overrides(["p.x.z=1"])[0])


def test_without_hydra_its_grammar_is_refused_by_name():
    code = textwrap.dedent("""
        import sys
        sys.modules["hydra"] = None
        from dvc_dat.do import parse_overrides
        for words, m in ((["+horizon=3"], False), (["game=G1,G4"], True), (["~note"], False)):
            try:
                parse_overrides(words, multirun=m)
            except ValueError as e:
                print("refused:", e)
        print("base:", [o.value for o in parse_overrides(["game=G1", "tags=[1,2]", "modules=a,b"])[0]])
    """)
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.count("needs Hydra's override grammar; install dvc-dat[hydra]") == 3
    assert "base: ['G1', [1, 2], 'a,b']" in out.stdout


@pytest.fixture
def hydra():
    pytest.importorskip("hydra")
    pytest.importorskip("omegaconf")


def test_hydras_grammar_adds_force_adds_and_deletes(hydra):
    spec = {"dat": {"kwargs": {"game": "G0", "note": "n"}}}
    (point,) = parse_overrides(["+horizon=3000", "++game=G1", "~note", "q='a b'", "d=2026-01-01", "m=${ns:x}"])
    assert apply_overrides(spec, point)["dat"]["kwargs"] == {"game": "G1", "horizon": 3000, "q": "a b",
                                                              "d": "2026-01-01", "m": "${ns:x}"}
    with pytest.raises(ValueError, match="already set"):
        apply_overrides(spec, parse_overrides(["+game=G2"])[0])
    with pytest.raises(ValueError, match="no key"):
        apply_overrides(spec, parse_overrides(["~nope"])[0])


def test_a_sweep_needs_m_and_is_the_product_in_hydras_order(hydra):
    (point,) = parse_overrides(["+x=1", "modules=a,b"])           # Hydra's parser, no -m: the comma is text
    assert [o.value for o in point] == [1, "a,b"]
    points = parse_overrides(["game=G1,G4", "dat.base=a,b", "n=range(1,3)"], multirun=True)
    assert [[o.value for o in p] for p in points] == [
        ["G1", "a", 1], ["G1", "a", 2], ["G1", "b", 1], ["G1", "b", 2],
        ["G4", "a", 1], ["G4", "a", 2], ["G4", "b", 1], ["G4", "b", 2]]


def test_a_sweep_runs_one_dat_per_point(hydra, tmp_path, capsys):
    from dvc_dat import Dat, core
    from dvc_dat.do import _cmd_do

    before = core._default_manager
    Dat.manager = DatManager(dat_folders=[str(tmp_path)])
    try:
        Dat.manager.ns.mount(value=lambda dat, **k: f"{dat.get_path_name()} {k}", at="ovr_echo")
        Dat.manager.ns.mount(value={"dat": {"do": "ovr_echo", "name": "runs/${dat.kwargs.game}/${unique:}"}},
                             at="ovr_tmpl")
        Dat.manager.ns.mount(value={"x": "from-ns"}, at="ovr_asset")
        assert _cmd_do(["ovr_tmpl", "-m", "game=G1,G4", "+m=${ns:ovr_asset.x}"]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines == ["runs/G1/1 {'game': 'G1', 'm': 'from-ns'}", "runs/G4/1 {'game': 'G4', 'm': 'from-ns'}"]
    finally:
        core._default_manager = before
