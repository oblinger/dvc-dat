"""On a ledger project `Dat.delete()` and `Dat.create(target_exists="overwrite")` onto an existing dat
refuse (SVP 1467 Q15 (A)): a ledger only appends rows and never reclaims bytes.

The non-ledger half -- `delete()` still removes the folder -- is
`tests/test_dat.py::TestDatCopyMoveDelete::test_copy_exists_and_delete`.
"""

import os

import pytest

from dvc_dat import DatManager
from dvc_dat.ledger import Ledger


@pytest.fixture
def project(tmp_path):
    """A ledger project's manager: `ledger:` in its `.datconfig.yaml`."""
    (tmp_path / ".datconfig.yaml").write_text("ledger: .dat/ledger\n")
    Ledger(tmp_path / ".dat" / "ledger", create=True)
    return DatManager.load_dat_config(tmp_path)


def _keys_of(m, name):
    return [k for k, v in m._read_index().items() if v == {"dat": name}]


def test_delete_refuses_and_leaves_the_folder_and_the_index(project):
    dat = project.create({"k": 1}, path="runs/one")
    dat.save()
    assert _keys_of(project, "runs/one")
    with pytest.raises(TypeError, match="a ledger never deletes"):
        dat.delete()
    assert os.path.isdir(dat.get_path()) and project.exists("runs/one")
    assert _keys_of(project, "runs/one")


def test_overwrite_onto_an_existing_dat_refuses_and_keeps_the_old_one(project):
    old = project.create({"k": 1}, path="runs/one")
    old.save()
    with pytest.raises(TypeError, match="target_exists: overwrite"):
        project.create({"k": 2, "dat": {"target_exists": "overwrite"}}, path="runs/one")
    assert project.load("runs/one").get_spec()["k"] == 1
    assert _keys_of(project, "runs/one")


def test_overwrite_onto_a_new_path_still_creates(project):
    dat = project.create({"k": 2, "dat": {"target_exists": "overwrite"}}, path="runs/fresh")
    assert os.path.isdir(dat.get_path()) and dat.get_spec()["k"] == 2
