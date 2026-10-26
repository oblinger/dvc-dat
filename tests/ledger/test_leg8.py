"""Leg 8: seal=False runs regardless and leaves no path folder; a Dat's _spec_ is checked on load."""

import pytest
import yaml

from dvc_dat.ledger import Dat, NotEvaluated
from ledger_kinds import CALLS


def test_a_draft_runs_on_a_dirty_or_stale_checkout(coded, envbox):
    with coded.transaction(by="t", lock=10) as t:
        t["game/G1"] = {"home": "G4"}
    envbox.code(dirty=True)
    assert coded.at().run("ledger_kinds.scratchy", game="G1", seal=False).obj == {"game": "G1"}
    with pytest.raises(NotEvaluated):
        coded.at().run("ledger_kinds.scratchy", game="G1")
    envbox.code(commit="other99")
    v = coded.at().run("ledger_kinds.scratchy", game="G1", seal=False)
    assert not v.sealed and "fn" in v.dependencies


def test_the_work_folder_goes_after_the_call_in_both_modes(coded):
    coded.at().run("ledger_kinds.scratchy", game="G1", seal=False)
    assert not CALLS["work"].exists()
    coded.at().run("ledger_kinds.scratchy", game="G2")
    assert not CALLS["work"].exists()
    d = coded.at().run("ledger_kinds.folder", game="G1", seal=False)    # an unsealed Dat is its folder
    assert (d.path / "a.txt").read_text() == "G1"


def test_a_dat_spec_kind_is_checked_against_the_row(L, tmp_path):
    saved = yaml.safe_dump({"dat": {"standing": "sealed"}})     # a dat seals as a value once saved
    good = tmp_path / "good"
    good.mkdir()
    (good / "_spec_.yaml").write_text(yaml.safe_dump({"dat": {"kind": "dvc_dat.core.Dat"}}))
    (good / "_result_.yaml").write_text(saved)
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "_spec_.yaml").write_text(yaml.safe_dump({"dat": {"kind": "elsewhere.Other"}}))
    (bad / "_result_.yaml").write_text(saved)
    with L.transaction(by="t") as t:
        sg = Dat(good).seal(t)
        sb = Dat(bad).seal(t)
    assert (L.at().load(sg).path / "_spec_.yaml").is_file()
    with pytest.raises(TypeError, match="elsewhere.Other"):
        L.at().load(sb)
