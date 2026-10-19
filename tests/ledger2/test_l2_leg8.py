"""Leg 8: memo=False runs regardless and leaves no work folder; a Dat's _spec_ is checked on load."""

import pytest
import yaml

from dvc_dat.ledger2 import Dat, NotEvaluated
from l2kinds import CALLS


def test_memo_false_runs_on_a_dirty_or_stale_checkout(coded, envbox):
    with coded.transaction(by="t") as t:
        t["game/G1"] = {"home": "G4"}
    envbox.code(dirty=True)
    assert coded.at().eval("l2kinds.scratchy", game="G1", memo=False).obj == {"game": "G1"}
    with pytest.raises(NotEvaluated):
        coded.at().eval("l2kinds.scratchy", game="G1")
    envbox.code(commit="other99")
    v = coded.at().eval("l2kinds.scratchy", game="G1", memo=False)
    assert not v.sealed and "fn" in v.trace


def test_the_work_folder_goes_after_the_call_in_both_modes(coded):
    coded.at().eval("l2kinds.scratchy", game="G1", memo=False)
    assert not CALLS["work"].exists()
    coded.at().eval("l2kinds.scratchy", game="G2")
    assert not CALLS["work"].exists()
    d = coded.at().eval("l2kinds.folder", game="G1", memo=False)    # an unsealed Dat is its folder
    assert (d.path / "a.txt").read_text() == "G1"


def test_a_dat_spec_kind_is_checked_against_the_row(L, tmp_path):
    good = tmp_path / "good"
    good.mkdir()
    (good / "_spec_.yaml").write_text(yaml.safe_dump({"dat": {"kind": "dvc_dat.ledger2.value.Dat"}}))
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "_spec_.yaml").write_text(yaml.safe_dump({"dat": {"kind": "elsewhere.Other"}}))
    with L.transaction(by="t") as t:
        sg = t.add_value(Dat(good))
        sb = t.add_value(Dat(bad))
    assert (L.at().load(sg).path / "_spec_.yaml").is_file()
    with pytest.raises(TypeError, match="elsewhere.Other"):
        L.at().load(sb)
