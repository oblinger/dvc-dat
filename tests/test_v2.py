"""The 2.0 contract: specs that fork, one `do`, one `{}` expander, `validate_spec`."""
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dvc_dat import Dat, DatManager, Do  # noqa: E402
from dvc_dat.core import expand, expand_spec  # noqa: E402

do, merge_dicts = Dat.do, Dat.merge_dicts
from dvc_dat.core import DAT_CONFIG_FILE, SPEC_YAML, RESULT_YAML  # noqa: E402

V2 = "v2tests"
SAMPLE = {"a": 1, "b": [2, 3]}     # a data object a spec may reference whole


def echo(_dat, *args, **kwargs):
    """A do-fn that reports the arguments the spec handed it, and seals its dat."""
    _dat.save()
    return {"args": list(args), "kwargs": dict(kwargs)}


do.mount(at="v2_echo", value=echo)


def stored(dat_or_path, file_name=SPEC_YAML):
    """The file as it sits on disk, not the in-memory spec."""
    path = dat_or_path.get_path() if isinstance(dat_or_path, Dat) else dat_or_path
    return yaml.safe_load(Path(path, file_name).read_text())


@pytest.fixture
def restore_manager():
    """Put back the default world a test replaced."""
    saved = Dat.manager
    yield
    Dat.manager = saved


class TestForkRule:
    """Arguments make a new spec, never a call."""

    def test_kwargs_land_in_the_new_spec_not_in_the_results(self):
        name = f"{V2}/fork_kwargs"
        do.mount(at="v2_kw", value={
            "dat": {"do": "v2_echo", "name": name, "target_exists": "overwrite"}})

        assert do("v2_kw", alpha=1, beta="two") == \
            {"args": [], "kwargs": {"alpha": 1, "beta": "two"}}

        spec = stored(Dat.load(name))
        assert spec["dat"]["kwargs"] == {"alpha": 1, "beta": "two"}
        assert spec["dat"]["name"] == name   # the stored spec is the whole recipe

        results = stored(Dat.load(name), RESULT_YAML)
        assert "args" not in results["dat"] and "kwargs" not in results["dat"]
        assert results["dat"]["run_at"] and results["dat"]["run_time"]

    def test_kwargs_update_the_templates_kwargs_key_by_key(self):
        name = f"{V2}/fork_kwargs_merge"
        do.mount(at="v2_kw2", value={
            "dat": {"do": "v2_echo", "name": name, "target_exists": "overwrite",
                    "kwargs": {"c": 33, "d": 44}}})

        assert do("v2_kw2", a=1, c=3) == {"args": [], "kwargs": {"c": 3, "d": 44, "a": 1}}
        assert stored(Dat.load(name))["dat"]["kwargs"] == {"c": 3, "d": 44, "a": 1}

    def test_positional_args_replace_the_templates_args(self):
        name = f"{V2}/fork_args"
        do.mount(at="v2_args", value={
            "dat": {"do": "v2_echo", "name": name, "target_exists": "overwrite",
                    "args": [4, 5, 6]}})

        assert do("v2_args") == {"args": [4, 5, 6], "kwargs": {}}
        assert do("v2_args", 1, 2) == {"args": [1, 2], "kwargs": {}}   # not [4,5,6,1,2]
        assert stored(Dat.load(name))["dat"]["args"] == [1, 2]

    def test_a_sealed_dat_does_not_rerun_and_forks_when_given_arguments(self):
        do.mount(at="v2_forkable", value={
            "dat": {"do": "v2_echo", "name": f"{V2}/forkable{{unique}}"}})
        for stale in (f"{V2}/forkable", f"{V2}/forkable_2"):
            if Dat.manager.exists(stale):
                Dat.load(stale).delete()

        assert do("v2_forkable", 1) == {"args": [1], "kwargs": {}}
        dat = Dat.load(f"{V2}/forkable")
        spec_file = Path(dat.get_path(), SPEC_YAML)
        before = spec_file.read_bytes()

        # No arguments: a sealed dat does not run again.
        with pytest.raises(Exception) as err:
            do(dat)
        assert "sealed" in str(err.value.__cause__)
        assert spec_file.read_bytes() == before
        assert not Dat.manager.exists(f"{V2}/forkable_2")

        # Arguments: a new dat, and the original spec is untouched.
        assert do(dat, 9) == {"args": [9], "kwargs": {}}
        assert spec_file.read_bytes() == before
        forked = Dat.load(f"{V2}/forkable_2")
        assert forked.get_path() != dat.get_path()
        assert stored(forked)["dat"]["args"] == [9]

    def test_overwrite_with_a_fixed_name_reruns_into_the_same_folder(self):
        name = f"{V2}/dev"
        do.mount(at="v2_dev", value={
            "dat": {"do": "v2_echo", "name": name, "target_exists": "overwrite"}})

        do("v2_dev")
        first = Dat.load(name).get_path()
        marker = Path(first, "left_over.txt")
        marker.write_text("from the previous run")

        do("v2_dev")
        assert Dat.load(name).get_path() == first
        assert not marker.exists()   # the folder is squashed, not merged

    def test_target_exists_use_returns_the_existing_dat_without_running(self):
        name = f"{V2}/use_me"
        do.mount(at="v2_use", value={
            "dat": {"do": "v2_echo", "name": name, "target_exists": "use"}})
        if Dat.manager.exists(name):
            Dat.load(name).delete()

        assert do("v2_use", 1) == {"args": [1], "kwargs": {}}
        again = do("v2_use", 2)
        assert isinstance(again, Dat)
        assert stored(again)["dat"]["args"] == [1]   # the first run's spec, not re-run


class TestBaseList:
    def test_base_accepts_a_list_merged_left_to_right(self):
        do.mount(at="v2_base_a", value={"dat": {}, "x": 1, "shared": "from_a"})
        do.mount(at="v2_base_b", value={"dat": {}, "y": 2, "shared": "from_b"})

        spec = do.resolve({"dat": {"base": ["v2_base_a", "v2_base_b"]}, "z": 3})
        assert (spec["x"], spec["y"], spec["z"]) == (1, 2, 3)
        assert spec["shared"] == "from_b"      # the later entry wins
        assert "base" not in spec["dat"]

    def test_the_stored_spec_has_no_base(self):
        name = f"{V2}/based"
        do.mount(at="v2_base_a", value={"dat": {}, "x": 1, "shared": "from_a"})
        do.mount(at="v2_base_b", value={"dat": {}, "y": 2, "shared": "from_b"})

        dat = Dat.create(path=name, spec={
            "dat": {"base": ["v2_base_a", "v2_base_b"], "target_exists": "overwrite"}})
        spec = stored(dat)
        assert "base" not in spec["dat"]
        assert spec["shared"] == "from_b" and spec["x"] == 1 and spec["y"] == 2

    def test_a_falsy_override_still_overrides(self):
        do.mount(at="v2_base_truthy", value={"dat": {}, "flag": True, "count": 7})
        spec = do.resolve({"dat": {"base": "v2_base_truthy"}, "flag": False, "count": 0})
        assert spec["flag"] is False and spec["count"] == 0


class TestExpand:
    def test_built_ins(self):
        now = datetime.now()
        assert expand("{YYYY}") == now.strftime("%Y")
        assert expand("{YY}") == now.strftime("%Y")[2:]
        assert expand("run-{YYYY}-{MM}") == now.strftime("run-%Y-%m")
        assert expand("{cwd}") == os.getcwd()
        assert expand("{unique}") == ""

    def test_vars_and_literal_braces(self):
        assert expand("hello {who}!", {"who": "dat"}) == "hello dat!"
        assert expand("{{literal}}") == "{literal}"
        assert expand("{{{who}}}", {"who": "x"}) == "{x}"

    def test_an_unknown_undotted_name_is_an_error(self):
        with pytest.raises(KeyError):
            expand("{no_such_name}")

    def test_a_dotted_name_resolves_through_do_load(self):
        import collections
        assert expand("{collections.OrderedDict}") is collections.OrderedDict  # a class: itself
        assert expand("sep is {os.sep}") == f"sep is {os.sep}"   # embedded: a string
        with pytest.raises(TypeError):
            expand("cls is {collections.OrderedDict}")           # embedded: not a scalar

    def test_a_function_is_called_with_no_arguments(self):
        assert expand("{os.getcwd}") == os.getcwd()
        assert expand("at {os.getcwd}/x") == f"at {os.getcwd()}/x"

    def test_literal_arguments_call_it(self):
        assert expand('{os.path.join("a", "b")}') == os.path.join("a", "b")
        assert expand("{builtins.max(1, 7, 3)}") == 7
        assert expand("{builtins.round(2.567, ndigits=1)}") == 2.6
        assert expand("{collections.OrderedDict()}") == {}       # parentheses call a class

    @pytest.mark.parametrize("ref", ["{os.path.join(x)}", "{builtins.max(1 + 2)}",
                                     "{builtins.max(*[1])}", "{builtins.max(1))}"])
    def test_arguments_are_literals_only(self, ref):
        with pytest.raises(ValueError, match="expand"):
            expand(ref)

    def test_a_call_needs_a_dotted_callable(self):
        with pytest.raises(ValueError, match="only a dotted name"):
            expand("{who()}", {"who": "x"})
        with pytest.raises(TypeError, match="not callable"):
            expand("{os.sep()}")

    def test_mounted_functions_are_called_and_callable_objects_are_not(self):
        class Proxy:                      # like SVP's `asset`: callable, attribute access
            ocr = "ocr-2026-09-23"

            def __call__(self):
                raise AssertionError("a callable object is never called")
        do.mount(value=lambda: "c2dbdc6", at="v2_meta.commit")
        do.mount(value=Proxy(), at="v2_asset.proxy")
        assert expand("{v2_meta.commit}") == "c2dbdc6"
        assert isinstance(expand("{v2_asset.proxy}"), Proxy)

    def test_a_whole_value_reference_keeps_the_object(self):
        marker = object()
        assert expand("{thing}", {"thing": marker}) is marker
        assert expand("[{thing}]", {"thing": 7}) == "[7]"

    def test_expand_spec_walks_the_tree_and_leaves_keys_alone(self):
        spec = {"{YYYY}": ["{YY}", {"deep": "{who}"}, 5], "plain": None}
        out = expand_spec(spec, {"who": "dat"})
        assert list(out) == ["{YYYY}", "plain"]        # keys are never expanded
        assert out["{YYYY}"][0] == datetime.now().strftime("%Y")[2:]
        assert out["{YYYY}"][1] == {"deep": "dat"}
        assert out["{YYYY}"][2] == 5 and out["plain"] is None
        assert spec["{YYYY}"][1]["deep"] == "{who}"    # the input is not touched


class TestGetSpec:
    def test_create_expands_once_and_the_file_is_the_record(self):
        """T011 Q7 (B): every `{}` is expanded at create; the file holds the values."""
        dat = Dat.create(path=f"{V2}/expanded", spec={
            "dat": {"kind": "Dat", "target_exists": "overwrite"},
            "stamp": "{YYYY}", "sep": "{os.sep}", "cfg": "{test_v2.SAMPLE}",
            "where": "{os.getcwd}"})

        year = datetime.now().strftime("%Y")
        assert dat.get_spec()["stamp"] == year
        assert stored(dat)["stamp"] == year            # the file holds the value
        assert stored(dat)["sep"] == os.sep
        assert isinstance(stored(dat)["cfg"], dict)    # a whole-value reference: data, inlined
        assert stored(dat)["where"] == os.getcwd()     # a function: called once, its value kept
        assert dat.get_spec()["dat"]["name"] == f"{V2}/expanded"   # the name is the folder

    def test_a_reference_to_a_non_data_object_is_refused_at_create(self):
        with pytest.raises(TypeError):
            Dat.create(path=f"{V2}/notdata", spec={
                "dat": {"kind": "Dat", "target_exists": "overwrite"}, "fn": "{collections.OrderedDict}"})
        assert not Dat.manager.exists(f"{V2}/notdata")

    def test_a_fork_from_a_dat_lands_beside_it(self):
        template = {"dat": {"do": "v2_echo", "name": f"{V2}/parent{{unique}}"}}
        do(template, 1)
        parent = Dat.load(f"{V2}/parent")
        assert parent.get_spec()["dat"]["name"] == f"{V2}/parent"
        do(parent, 2)
        child = Dat.load(f"{V2}/parent_2")
        assert child.get_spec()["dat"]["args"] == [2]
        assert child.get_spec()["dat"]["target_exists"] == "increment"


class Strict(Dat):
    """A Dat whose specs must carry a `required` key."""

    @classmethod
    def validate_spec(cls, spec):
        spec = super().validate_spec(spec)
        if "required" not in spec:
            raise ValueError("Strict: a spec needs a 'required' key")
        return spec


class TestValidateSpec:
    def test_a_subclass_hook_rejects_on_create(self):
        with pytest.raises(ValueError, match="required"):
            Strict.create(path=f"{V2}/strict_bad", spec={"dat": {"kind": "Strict"}})
        assert not Dat.manager.exists(f"{V2}/strict_bad")

    def test_a_subclass_hook_rejects_on_load(self):
        name = f"{V2}/strict_ok"
        good = Strict.create(path=name, spec={
            "dat": {"kind": "Strict", "target_exists": "overwrite"}, "required": 1})
        spec_file = Path(good.get_path(), SPEC_YAML)

        broken = yaml.safe_load(spec_file.read_text())
        del broken["required"]
        spec_file.write_text(yaml.safe_dump(broken, sort_keys=False))
        Dat.manager._dat_cache.pop(good.get_path(), None)

        with pytest.raises(ValueError, match="required"):
            Strict.load(name)

    def test_an_unquoted_reference_in_yaml_is_named_as_the_error(self):
        spec = yaml.safe_load("dat:\n  name: {svp.CONFIG}\n")
        assert isinstance(spec["dat"]["name"], dict), "YAML read it as a flow mapping"
        with pytest.raises(TypeError, match="quoted"):
            Dat.create(spec=spec)


class TestStaticResolution:
    def test_an_importable_dotted_name_needs_no_mount(self):
        assert do.load("os.path.join") is os.path.join
        assert do.load("dvc_dat.core.Dat") is Dat

    def test_what_is_missing_raises_what_python_raises(self):
        with pytest.raises(AttributeError):
            do.load("os.path.nope")
        with pytest.raises(ImportError):
            do.load("nope_pkg_2026.x")

    def test_default_swallows_both(self):
        assert do.load("os.path.nope", default="fallback") == "fallback"
        assert do.load("nope_pkg_2026.x", default=None) is None

    def test_kind_mismatch_is_a_type_error(self):
        with pytest.raises(TypeError):
            do.load("os.path.join", kind=dict)

    def test_name_of_round_trips_through_load(self):
        assert do.load(do.name_of(os.path.join)) is os.path.join
        assert do.name_of(Dat) == "dvc_dat.core.Dat"
        assert do.load(do.name_of(Dat)) is Dat
        assert do.name_of(os.path) == "posixpath"
        with pytest.raises(ValueError):
            do.name_of(lambda: None)


class TestExplicitConfig:
    def test_a_loaded_config_adopting_do_keeps_its_mounts(self, tmp_path,
                                                          restore_manager):
        (tmp_path / "mounted").mkdir()
        (tmp_path / "mounted" / "v2_greeter.py").write_text(
            "def __main__():\n    return 'hi'\n")
        (tmp_path / "explicit_main.py").write_text(
            "from pathlib import Path\nfrom dvc_dat import Dat\ndo = Dat.do\n"
            "do.mount(folder=str(Path(__file__).parent / 'mounted'))\n")
        (tmp_path / DAT_CONFIG_FILE).write_text("dat_folders: sync/\n")

        assert do.load("v2_greeter", default=None) is None

        do_before = do._current()
        Dat.manager = DatManager.load_dat_config(tmp_path, do=do)
        import explicit_main  # noqa: F401  -- the config folder is on sys.path now
        assert do("v2_greeter") == "hi"             # its mounts landed on `do`
        assert sys.path[0] == os.path.realpath(tmp_path)
        assert do._current() is do_before          # the namespace kept its identity
        assert do.load("v2_echo") is echo          # ... and the mounts made before
        assert Dat.manager._dat_folders == [os.path.join(os.path.realpath(tmp_path), "sync")]

    def test_load_dat_config_accepts_a_config_file(self, tmp_path):
        config_file = tmp_path / DAT_CONFIG_FILE
        config_file.write_text("dat_folders: elsewhere/\n")
        before = Dat.manager
        other = DatManager.load_dat_config(config_file)   # a world of its own
        assert other._dat_folders[0].endswith("/elsewhere")
        assert Dat.manager is before

    def test_importing_dvc_dat_reads_no_config(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-c",
             "import dvc_dat; print(dvc_dat.core._default_manager, dvc_dat.Dat.do._current())"],
            cwd=tmp_path, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "None None"


class TestCleanup:
    def test_cleanup(self):
        sync = Path(__file__).parent / "test_sync_folder"
        shutil.rmtree(sync / V2, ignore_errors=True)
        shutil.rmtree(sync / "anonymous", ignore_errors=True)
        assert not (sync / V2).exists()


def test_first_use_installs_the_config(tmp_path):
    """T010 Q1: nobody configures anything; the first use builds `Dat.manager`
    from cwd.  The namespace is what the program imported (T011, Dan)."""
    pkg = tmp_path / "lazypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "job.py").write_text("def run(dat):\n    return 'ran'\n")
    (tmp_path / "lazy_main.py").write_text(
        "from dvc_dat import Dat\ndo = Dat.do\nimport lazypkg.job\n"
        "do.mount(module=lazypkg.job, at='lazy')\n")
    (tmp_path / DAT_CONFIG_FILE).write_text("dat_folders: warehouse\n")
    (tmp_path / "notes").mkdir()                # a subfolder: cwd is not the root

    probe = (
        "from dvc_dat import Dat\ndo = Dat.do\n"
        "import lazy_main\n"                    # the program's own mounts
        "fn = do.load('lazy.run')\n"            # the alias, nothing configured
        "assert fn(None) == 'ran'\n"
        "assert do.load('lazypkg.job.run') is fn\n"   # the static floor agrees
        "print(Dat.manager._dat_folders[0])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=tmp_path / "notes",
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": f"{REPO_ROOT}:{tmp_path}"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().rstrip("/").endswith("warehouse")


def test_increment_on_a_plain_name_counts_up(tmp_path, restore_manager):
    """`target_exists: increment` on a name with no `{unique}` appends `_2`, `_3`
    instead of spinning forever (found 2026-09-22)."""
    Dat.manager = DatManager(dat_folders=[str(tmp_path / "data")], do=do)
    spec ={"dat": {"kind": "Dat", "name": "plain", "target_exists": "increment"}}
    assert Dat.create(spec=spec).get_path_name() == "plain"
    assert Dat.create(spec=spec).get_path_name() == "plain_2"
    assert Dat.create(spec=spec).get_path_name() == "plain_3"


DOCS = REPO_ROOT / "docs"


@pytest.mark.parametrize("page", ["concepts.md", "spec-format.md"])
def test_the_documented_variation_recipe_runs_verbatim(page):
    """The docs' `merge_dicts(d.get_spec(), ...)` recipe, executed as written."""
    blocks = re.findall(r"```python\n(.*?)```", (DOCS / page).read_text(), re.S)
    (recipe,) = [b for b in blocks if "merge_dicts(d.get_spec()" in b]
    parent_name = f"{V2}/variation_{page.split('.')[0]}"
    for stale in (parent_name, parent_name + "_2"):
        if Dat.manager.exists(stale):
            Dat.load(stale).delete()
    d = Dat.create(path=parent_name, spec={"gameset": "G1"})

    with pytest.raises(FileExistsError):     # the recipe without increment
        Dat.create(spec=merge_dicts(d.get_spec(), {"gameset": "G7"}))

    namespace = {"d": d}
    exec(recipe, namespace)
    child = Dat.load(parent_name + "_2")
    assert child.get_spec()["dat"]["name"] == parent_name + "_2"
    assert stored(d)["dat"]["name"] == parent_name   # the parent is untouched
    for dat in (child, d):
        dat.delete()
