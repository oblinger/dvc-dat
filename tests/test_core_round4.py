"""Core latent bugs (deep scan round 4, 2026-10-27): a fork that wipes or reuses its parent, an overwrite
that hands back the old object or wipes the old dat before its spec is made, a stored literal brace
re-expanded, a dat.base cycle, a _spec_.json dat's save, the k=v grammar, a dotted --set under a scalar."""
import json
from pathlib import Path

import pytest
import yaml

from dvc_dat import Dat
from dvc_dat.do import arg_value


@pytest.fixture
def world(tmp_path):
    from dvc_dat import DatManager, Namespace

    saved = Dat.manager
    data = tmp_path / "data"
    data.mkdir()
    m = DatManager(dat_folders=[str(data)], ns=Namespace())
    Dat.manager = m
    yield m
    Dat.manager = saved


def _seal(dat, *a, **k):
    dat.save()
    return dat


# --- F1: forking a Dat whose spec says target_exists: overwrite deletes the parent ---------
def test_fork_of_overwrite_dat_keeps_parent(world):
    world.ns.mount(at="seal_fn", value=_seal)
    parent = world.run({"dat": {"do": "seal_fn", "name": "exp1", "target_exists": "overwrite",
                                "kwargs": {"x": 1}}})
    Path(parent.get_path(), "precious.txt").write_text("only copy")
    try:
        world.run(parent, x=2)
    except Exception:
        pass        # today: the fork rmtree's the parent, then trips on the stale cached (sealed) parent
    # docstring: "forks a new dat from its spec ... a fork lands beside its parent"
    assert Path(parent.get_path(), "precious.txt").exists()


# --- F1b: create with target_exists: overwrite hands back the stale cached dat -------------
def test_overwrite_create_returns_fresh_dat(world):
    first = world.create({"dat": {"name": "ow", "target_exists": "overwrite"}, "v": 1})
    second = world.create({"dat": {"name": "ow", "target_exists": "overwrite"}, "v": 2})
    assert first is not None
    on_disk = yaml.safe_load(Path(second.get_path(), "_spec_.yaml").read_text())
    assert on_disk["v"] == 2
    assert second.get_spec()["v"] == 2


# --- F2: forking a Dat whose spec says target_exists: use returns the parent, args dropped --
def test_fork_of_use_dat_runs_with_new_args(world):
    world.ns.mount(at="seal_fn", value=_seal)
    parent = world.run({"dat": {"do": "seal_fn", "name": "exp2", "target_exists": "use",
                                "kwargs": {"x": 1}}})
    child = world.run(parent, x=2)
    assert Dat.get(child.get_spec(), "dat.kwargs.x") == 2


# --- F4: forking a stored dat re-expands its already-expanded spec ------------------------
def test_fork_of_dat_with_literal_brace_in_spec(world):
    world.ns.mount(at="seal_fn", value=_seal)
    parent = world.run({"dat": {"do": "seal_fn", "name": "exp4"}, "note": "{{literal}}"})
    assert parent.get_spec()["note"] == "{literal}"       # expanded once, as documented
    child = world.run(parent, x=2)                         # today: KeyError unknown name {literal}
    assert child.get_spec()["note"] == "{literal}"


# --- F5: a dat.base cycle is unbounded recursion, not a clear error -----------------------
def test_base_cycle_is_a_clear_error(world):
    world.ns.mount(at="cyc_a", value={"dat": {"base": "cyc_b"}})
    world.ns.mount(at="cyc_b", value={"dat": {"base": "cyc_a"}})
    with pytest.raises((ValueError, TypeError, KeyError)):
        world.expand_spec({"dat": {"base": "cyc_a"}})


# --- F6: save() of a dat whose spec is _spec_.json (spec-format: "a _spec_.json is read too")
def test_save_of_json_spec_dat(world):
    folder = Path(world._dat_folders[0], "jdat")
    folder.mkdir()
    (folder / "_spec_.json").write_text(json.dumps({"dat": {"kind": "dvc_dat.core.Dat"}}))
    dat = world.load("jdat")
    dat.save()
    assert dat.verify()




# --- F8: arg_value turns a non-JSON-finite number into float inf ---------------------------
def test_arg_value_overflowing_number_is_not_inf():
    v = arg_value("1e999")
    # docstring: NaN/Infinity are refused as "not JSON"; 1e999 parses to the same inf
    assert v == "1e999"


# --- F9: arg_value strips whitespace though it claims "the text exactly as typed" ---------
def test_arg_value_keeps_padded_text():
    assert arg_value(" 7") == " 7"


# --- F10: arg_value crashes on a deeply nested value instead of falling back --------------
def test_arg_value_deep_nesting_falls_back_to_text():
    text = "[" * 100000
    assert arg_value(text) == text


# --- F1c: re-running an overwrite template while the last result is still referenced -------
def test_rerun_overwrite_template_while_previous_is_held(world):
    world.ns.mount(at="seal_fn", value=_seal)
    tmpl = {"dat": {"do": "seal_fn", "name": "again", "target_exists": "overwrite"}}
    held = world.run(tmpl)  # noqa: F841 -- a notebook keeps `held`
    again = world.run(tmpl)                # today: RuntimeError "<Dat: again> is sealed", folder already wiped
    # frozen either way: `referenceable` from a clean checkout, `sealed` when the run's code is dirty
    assert again.get_results()["dat"]["standing"] in ("sealed", "referenceable")



# --- F11: a create that fails (bad {} reference) after `overwrite` has already wiped the old dat
def test_failed_overwrite_create_keeps_old_dat(world):
    world.create({"dat": {"name": "keep", "target_exists": "overwrite"}, "v": 1})
    old = Path(world._dat_folders[0], "keep")
    (old / "result.csv").write_text("hours of compute")
    with pytest.raises(KeyError):
        world.create({"dat": {"name": "keep", "target_exists": "overwrite"}, "v": "{typo}"})
    # spec-format: a reference that does not resolve is an error at create "and no folder is made"
    assert (old / "result.csv").exists()




# --- F13: a --set dotted key under a scalar it set itself escapes as a traceback ------------
def test_set_dotted_under_scalar_is_a_cli_error(world):
    from dvc_dat.do import _cmd_do
    world.ns.mount(at="tmpl13", value={"dat": {}})
    # _cmd_do turns a malformed line into exit 1 + "run: ..." -- it catches ValueError only
    assert _cmd_do(["tmpl13", "--set", "a=1", "--set", "a.b=2"]) == 1
