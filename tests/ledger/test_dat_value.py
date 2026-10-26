"""DAT 1038: a dat is a value. The core ``Dat`` seals, loads and is found with no subclass; ``rev.run`` of
a spec makes, runs and seals one through the ledger, memoised (DAT 1046: one ``run``)."""

import os

import pytest

import dvc_dat.ledger as ledger_pkg
from dvc_dat import Dat, DatContainer, DatManager

from ledger_kinds import CALLS, NotedDat

SPEC = {"dat": {"do": "ledger_kinds.build_table", "name": "tables/table{unique}", "kwargs": {"n": 12, "start": 1}}}


@pytest.fixture
def world(tmp_path):
    """The default dat world in this test's folder; the one before it restored after."""
    from dvc_dat import core

    before = core._default_manager
    Dat.manager = DatManager(dat_folders=[str(tmp_path / "data")])
    yield Dat.manager
    core._default_manager = before
    if before is not None:
        Dat.manager = before


def made(spec=SPEC, **kwargs):
    """A dat ``Dat.do`` made and ran: saved by its run function."""
    return Dat.do(spec, **kwargs)


def test_the_ledger_dat_is_the_core_dat():
    assert ledger_pkg.Dat is Dat and issubclass(Dat, ledger_pkg.Value)
    assert not hasattr(ledger_pkg.value, "Dat")


def test_a_do_made_dat_seals_and_loads_with_no_subclass(L, world):
    dat = made()
    with L.transaction(by="t") as t:
        dat.seal(t, name="table/12")
    assert repr(dat) == "<Dat table/12>" and dat.subject is not None
    L._values.clear()
    back = L.at().load("table/12")
    assert type(back) is Dat and back.subject == dat.subject
    assert back.get_spec()["dat"]["kwargs"] == {"n": 12, "start": 1}
    assert back.get_results()["cells"] == 144
    assert (back.path / "table.csv").read_text() == "12 from 1\n"
    assert sorted(p.name for p in back.path.iterdir()) == ["_result_.yaml", "_spec_.yaml", "run", "table.csv"]
    assert back.get_path() == str(back.path) and back.path.parent.name == "table"


def test_a_dats_preds_default_to_its_kwargs_and_results(L, world):
    dat = made()
    assert dict(dat.preds) == {"n": 12, "start": 1, "cells": 144}       # read from the folder
    dat.preds["start"] = 2                                              # a hand write wins
    dat.seal(L, name="table/12")
    assert dict(L.at().load("table/12").preds) == {"n": "12", "start": "2", "cells": "144"}
    assert "dat" not in dat.preds                                       # the seal record is no pred


def test_values_of_kind_dat_find_it(L, world):
    made().seal(L, name="table/12")
    made(n=5).seal(L, name="table/5")
    assert [str(v) for v in L.at().values(kind=Dat)] == ["table/12", "table/5"]
    assert str(L.at().value(n=5)) == "table/5"


def test_sealing_an_open_dat_is_refused(L, world):
    dat = Dat.create(spec=SPEC)                                         # instantiated, never run or saved
    with pytest.raises(ValueError, match=r"dat\.save\(\)"):
        dat.seal(L)
    with pytest.raises(ValueError, match=r"dat\.save\(\)"):
        dat.seal()
    dat.save()
    dat.seal(L)
    assert dat.subject is not None


def test_a_plain_folder_is_a_value_too(L, tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    (folder / "a.txt").write_text("a")
    d = Dat(folder)
    assert d.get_spec() == {} and dict(d.preds) == {}
    d.seal(L, name="f/1")
    assert (L.at().load("f/1").path / "a.txt").read_text() == "a"


def test_a_subclass_declares_preds_beside_the_folders(L, world):
    dat = made({"dat": {**SPEC["dat"], "kind": "ledger_kinds.NotedDat"}})
    assert type(dat) is NotedDat
    dat.preds["note"] = "x"
    dat.seal(L, name="noted/1")
    back = L.at().load("noted/1")
    assert type(back) is NotedDat and dict(back.preds) == {"note": "x", "n": "12", "start": "1", "cells": "144"}
    assert [v.subject for v in L.at().values(kind=NotedDat)] == [back.subject]


def test_rev_run_of_a_spec_runs_once_then_hits(coded, world, tmp_path):
    CALLS.clear()
    first = coded.at().run(SPEC)
    assert CALLS == {"build_table": 1} and str(first) == "tables/table"
    top = coded.at().id
    again = coded.at().run(SPEC)
    assert CALLS == {"build_table": 1} and again.subject == first.subject and coded.at().id == top
    assert again.path == first.path and (again.path / "table.csv").is_file()
    assert not list((tmp_path / "data").rglob("_spec_.yaml"))         # one folder: the view in the data folder
    rows = coded.at()
    assert rows.get(first.subject, "db/fn") == "ledger_kinds.build_table"
    assert rows.get(first.subject, "db/returns") == "dvc_dat.core.Dat"
    keys = rows.get(first.subject, "db/keys")
    assert keys == {"dat": {"do": "ledger_kinds.build_table", "kind": "dvc_dat.core.Dat",
                            "kwargs": {"n": 12, "start": 1}}}             # the memo key: the spec, dat.name removed
    assert first.dependencies["code"].startswith("db/code/") and first.dependencies["fn"] == "ledger_kinds.build_table"
    assert rows.get(first.subject, "db/provenance") == "eval:unsandboxed"     # installed: in this process
    assert first.dependencies["code/testrepo"] == "abc1234"


def test_rev_run_kwargs_fork_the_spec_and_path_names_it(coded, world):
    CALLS.clear()
    five = coded.at().run(SPEC, n=5, path="t/five")
    assert str(five) == "t/five" and dict(five.preds) == {"n": "5", "start": "1", "cells": "25"}
    assert coded.at().run(SPEC, n=5, seal="get").subject == five.subject and CALLS == {"build_table": 1}
    assert coded.at().run(SPEC, n=6, seal="get") is None


def test_rev_run_takes_a_spec_by_name_or_its_run_function_by_name(coded, world):
    CALLS.clear()
    a = coded.at().run("ledger_kinds.TABLE_SPEC")                       # a dict, by its dotted name
    assert coded.at().run(SPEC).subject == a.subject                    # the same memo key: dat.name is not in it
    b = coded.at().run("ledger_kinds.build_table", n=12, start=1)       # the spec {dat: {do: <name>}}
    assert b.subject == a.subject and CALLS == {"build_table": 1}


def test_rev_resolve_hands_back_what_a_name_denotes(coded):
    from dvc_dat.ledger import Fn
    import ledger_kinds

    rev = coded.at()
    assert rev.resolve("ledger_kinds.TABLE_SPEC") == ledger_kinds.TABLE_SPEC
    cut_fn = rev.resolve("ledger_kinds.cut")
    assert isinstance(cut_fn, Fn) and cut_fn.kind == "ledger" and cut_fn.code.sandboxed is False
    assert rev.resolve("ledger_kinds.build_table") is ledger_kinds.build_table   # installed, undecorated: itself
    assert rev.resolve("ledger_kinds.NotedDat") is NotedDat              # anything else: the object


def test_a_spec_naming_a_ledger_function_is_refused(coded, world):
    with pytest.raises(TypeError, match="rev.run"):
        coded.at().run({"dat": {"do": "ledger_kinds.cut"}})


def test_a_run_leaving_its_dat_open_is_refused(coded, world):
    with pytest.raises(ValueError, match=r"dat\.save\(\)"):
        coded.at().run({"dat": {"do": "ledger_kinds.never_saves"}})


def test_plain_do_is_unchanged(coded, world, tmp_path):
    a, b = made(), made()
    assert a.get_path_name() == "tables/table" and b.get_path_name() == "tables/table_2"
    assert a.subject is None and coded.at().values(kind=Dat) == []


def test_a_dat_container_still_lists_its_dats(world):
    box = world.create({"dat": {"kind": "dvc_dat.core.DatContainer"}}, path="box")
    world.create({}, path="box/one")
    assert isinstance(box, DatContainer) and [os.path.basename(p) for p in box.get_dat_paths()] == ["one"]
    assert [d.get_path_name() for d in box.get_dats()] == ["box/one"]


def test_a_ledger_project_gets_the_ledgers_do_and_a_plain_one_the_plain_do(tmp_path):
    from dvc_dat import Do
    from dvc_dat.ledger import Ledger, LedgerDo

    led, plain = tmp_path / "led", tmp_path / "plain"
    led.mkdir()
    plain.mkdir()
    (led / ".datconfig.yaml").write_text("ledger: .dat/ledger\n")
    Ledger(led / ".dat" / "ledger", create=True)
    (plain / ".datconfig.yaml").write_text("dat_folders: data\n")
    m = DatManager.load_dat_config(led)
    assert isinstance(m.do, LedgerDo) and m.do.load("os.path.join") is os.path.join
    assert m.do.load("dt.list") is not None                             # the world's own names stay
    with pytest.raises(TypeError, match="db/mount"):
        m.do.mount(value={"dat": {}}, at="specs.x")
    p = DatManager.load_dat_config(plain)
    assert type(p.do) is Do
    p.do.mount(value={"dat": {}}, at="specs.x")
    assert p.do.load("specs.x") == {"dat": {}}
