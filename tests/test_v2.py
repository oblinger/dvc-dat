"""The 2.0 contract: specs that fork, one `do`, one `{}` expander, `validate_spec`."""
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dvc_dat import Dat, DataConfig, Do, do, expand, expand_spec, load  # noqa: E402
from dvc_dat.core import DATA_CONFIG_FILE, SPEC_YAML, RESULT_YAML  # noqa: E402

V2 = "v2tests"


def echo(_dat, *args, **kwargs):
    """A do-fn that reports the arguments the spec handed it."""
    return {"args": list(args), "kwargs": dict(kwargs)}


do.mount(at="v2_echo", value=echo)


def stored(dat_or_path, file_name=SPEC_YAML):
    """The file as it sits on disk, not the in-memory spec."""
    path = dat_or_path.get_path() if isinstance(dat_or_path, Dat) else dat_or_path
    return yaml.safe_load(Path(path, file_name).read_text())


@pytest.fixture
def restore_manager():
    """Undo whatever a test's own `configure()` did to the process singletons."""
    saved_manager, saved_config = Dat._manager, do.config
    yield
    Dat._manager, do.config = saved_manager, saved_config


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

    def test_a_dat_reruns_in_place_and_forks_when_given_arguments(self):
        do.mount(at="v2_forkable", value={
            "dat": {"do": "v2_echo", "name": f"{V2}/forkable{{unique}}"}})
        for stale in (f"{V2}/forkable", f"{V2}/forkable_2"):
            if Dat.manager.exists(stale):
                load(stale).delete()

        assert do("v2_forkable", 1) == {"args": [1], "kwargs": {}}
        dat = load(f"{V2}/forkable")
        spec_file = Path(dat.get_path(), SPEC_YAML)
        before = spec_file.read_bytes()

        # No arguments: the dat on disk runs again, as it is.
        assert do(dat) == {"args": [1], "kwargs": {}}
        assert spec_file.read_bytes() == before
        assert not Dat.manager.exists(f"{V2}/forkable_2")

        # Arguments: a new dat, and the original spec is untouched.
        assert do(dat, 9) == {"args": [9], "kwargs": {}}
        assert spec_file.read_bytes() == before
        forked = load(f"{V2}/forkable_2")
        assert forked.get_path() != dat.get_path()
        assert stored(forked)["dat"]["args"] == [9]

    def test_overwrite_with_a_fixed_name_reruns_into_the_same_folder(self):
        name = f"{V2}/dev"
        do.mount(at="v2_dev", value={
            "dat": {"do": "v2_echo", "name": name, "target_exists": "overwrite"}})

        do("v2_dev")
        first = load(name).get_path()
        marker = Path(first, "left_over.txt")
        marker.write_text("from the previous run")

        do("v2_dev")
        assert load(name).get_path() == first
        assert not marker.exists()   # the folder is squashed, not merged

    def test_target_exists_use_returns_the_existing_dat_without_running(self):
        name = f"{V2}/use_me"
        do.mount(at="v2_use", value={
            "dat": {"do": "v2_echo", "name": name, "target_exists": "use"}})
        if Dat.manager.exists(name):
            load(name).delete()

        assert do("v2_use", 1) == {"args": [1], "kwargs": {}}
        again = do("v2_use", 2)
        assert isinstance(again, Dat)
        assert stored(again)["dat"]["args"] == [1]   # the first run's spec, not re-run


class TestBaseList:
    def test_base_accepts_a_list_merged_left_to_right(self):
        do.mount(at="v2_base_a", value={"dat": {}, "x": 1, "shared": "from_a"})
        do.mount(at="v2_base_b", value={"dat": {}, "y": 2, "shared": "from_b"})

        spec = do.resolve_base({"dat": {"base": ["v2_base_a", "v2_base_b"]}, "z": 3})
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
        spec = do.resolve_base({"dat": {"base": "v2_base_truthy"}, "flag": False, "count": 0})
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
        assert expand("{os.path.join}") is os.path.join          # whole value: the object
        assert expand("sep is {os.sep}") == f"sep is {os.sep}"   # embedded: str()

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
    def test_get_spec_expands_and_caches_and_raw_is_the_file(self):
        dat = Dat.create(path=f"{V2}/expanded", spec={
            "dat": {"kind": "Dat", "target_exists": "overwrite"},
            "stamp": "{YYYY}", "fn": "{os.path.join}"})

        assert dat.get_spec(raw=True)["stamp"] == "{YYYY}"
        assert stored(dat)["stamp"] == "{YYYY}"        # the file keeps the reference
        assert dat.get_spec()["stamp"] == datetime.now().strftime("%Y")
        assert dat.get_spec()["fn"] is os.path.join
        assert dat.get_spec() is dat.get_spec()        # computed once per instance
        assert dat.spec is dat.get_spec()


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
        Dat.manager.dat_cache.pop(good.get_path(), None)

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


class TestExplicitConfigure:
    def test_configure_mounts_onto_the_object_imported_earlier(self, tmp_path,
                                                               restore_manager):
        (tmp_path / "mounted").mkdir()
        (tmp_path / "mounted" / "v2_greeter.py").write_text(
            "def __main__():\n    return 'hi'\n")
        (tmp_path / DATA_CONFIG_FILE).write_text(
            "local_prefix: sync/\nmount_commands:\n  - folder: mounted\n")

        probe = Do()                      # stands in for an early `from dvc_dat import do`
        assert probe.load("v2_greeter", default=None) is None

        config = probe.configure(tmp_path)
        assert isinstance(config, DataConfig)
        assert probe("v2_greeter") == "hi"          # same object, now mounted
        assert probe.config.cwd == os.path.realpath(tmp_path)
        assert Dat.manager.sync_folder == os.path.join(os.path.realpath(tmp_path), "sync/")

    def test_configure_accepts_a_config_file(self, tmp_path, restore_manager):
        config_file = tmp_path / DATA_CONFIG_FILE
        config_file.write_text("local_prefix: elsewhere/\n")
        probe = Do()
        assert probe.configure(config_file).local_prefix.endswith("/elsewhere/")

    def test_importing_dvc_dat_reads_no_config(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-c",
             "import dvc_dat; print(dvc_dat.do.config, dvc_dat.Dat._manager)"],
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


def test_first_use_installs_the_config_and_its_mounts(tmp_path, monkeypatch,
                                                      restore_manager):
    """T010 Q1: nobody calls `configure()` -- the first use discovers one."""
    pkg = tmp_path / "lazypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "job.py").write_text("def run(dat):\n    return 'ran'\n")
    (tmp_path / DATA_CONFIG_FILE).write_text(
        "local_prefix: warehouse\n"
        "mount_commands:\n"
        "  - {module: lazypkg.job, at: lazy}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))

    fresh = Do()
    assert fresh.config is None, "constructing a Do must read no filesystem"

    fn = fresh.load("lazy.run")                 # the mount, with no configure()
    assert callable(fn) and fn(None) == "ran"
    assert fresh.config is not None             # ... it installed one on the way
    assert fresh.load("lazypkg.job.run") is fn  # the static floor still resolves

    Dat._manager = None
    assert Dat.manager.sync_folder.rstrip("/").endswith("warehouse")
