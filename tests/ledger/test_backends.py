"""SVP 1599: backends registered by URI scheme. A ledger's bytes live at its values URI, ``(db, db/values, <uri>)``.

Every case runs against a fake, folder-backed values backend registered through the public ``register_values``
under the scheme ``bucket`` (``bucket://<name>`` is the folder ``<tmp>/<name>``): what a consumer (sv-pipe, ``gs``)
does with its own cloud code.
"""

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dvc_dat import Dat, DatManager
from dvc_dat.ledger import Ledger, LedgerError, Values, register_triples, register_values
from dvc_dat.ledger import backends as backends_mod
from dvc_dat.ledger.backends import blob_path
from ledger_kinds import Video

HERE = Path(__file__).parent
SPEC = {"dat": {"do": "ledger_kinds.build_table", "name": "tables/table${unique:}", "kwargs": {"n": 12, "start": 1}}}


class FolderValues:
    """A values backend that is a folder: ``<root>/sha256/<2>/<hash>``, counting its calls."""

    def __init__(self, root: Path, hook=None):
        self.root, self.hook = Path(root), hook
        self.pushes, self.pulls = [], []

    def _p(self, h):
        return self.root / blob_path(h)

    def has(self, h):
        return self._p(h).exists()

    def push(self, path, h):
        if self.hook:
            self.hook(h)
        self.pushes.append(h)
        self._p(h).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, self._p(h))

    def pull(self, h, path):
        self.pulls.append(h)
        shutil.copyfile(self._p(h), path)


@pytest.fixture
def clouds(tmp_path, monkeypatch):
    """The scheme ``bucket`` registered: ``bucket://<name>`` is a ``FolderValues`` at ``tmp_path/<name>``, kept in
    the dict returned by ``<name>`` once made. Nothing else is registered beyond the built-ins."""
    monkeypatch.setattr(backends_mod, "_VALUES", dict(backends_mod._VALUES))
    monkeypatch.setattr(backends_mod, "_TRIPLES", dict(backends_mod._TRIPLES))
    monkeypatch.setattr(backends_mod, "_MADE", {})
    monkeypatch.setattr(backends_mod, "_IMPORTED", set())
    monkeypatch.chdir(tmp_path)
    made = {}

    def make(uri):
        name = uri.partition("://")[2]
        made[name] = FolderValues(tmp_path / name)
        return made[name]
    register_values("bucket", make)
    return made


def store(L, name):
    """``L``'s values URI is ``bucket://<name>``."""
    with L.transaction(by="t") as t:
        t.add("db", "db/values", f"bucket://{name}")


def drop_cache(L):
    """The writer's copy gone: the cache folder emptied and the handle's loaded values forgotten."""
    shutil.rmtree(L._store.art.root, ignore_errors=True)
    L._values.clear()


def seal_video(L, frames=b"G1 frames", name="video/G1"):
    v = Video(frames)
    with L.transaction(by="t") as t:
        v.seal(t, name=name)
    return v


# -- the registries -------------------------------------------------------------------------------------------

def test_register_refuses_a_bad_scheme_and_a_non_callable(clouds):
    for register in (register_values, register_triples):
        for bad in ("Gs", "9p", "", "g s", None):
            with pytest.raises(ValueError, match="scheme"):
                register(bad, lambda *a: None)
        with pytest.raises(TypeError, match="factory"):
            register("s3", "not callable")
    assert isinstance(FolderValues(Path(".")), Values)


def test_the_built_ins(clouds):
    triples, values = backends_mod.registered()
    assert triples == ["postgres", "postgresql", "sqlite"] and values == ["bucket", "file"]


def test_an_unknown_values_scheme_is_refused_at_add_listing_what_is_registered(L, clouds):
    with pytest.raises(LedgerError, match=r"no values backend for scheme 'gs' \(gs://b/p\): registered: bucket, file; "
                                          r"call register_values\('gs', factory\), or list its module under "
                                          r"backends: in .datconfig.yaml"):
        with L.transaction(by="t") as t:
            t.add("db", "db/values", "gs://b/p")
    for bad in ("gcp", "/a/folder", 7):
        with pytest.raises(ValueError, match="db/values"):
            with L.transaction(by="t") as t:
                t.add("db", "db/values", bad)
    with pytest.raises(ValueError, match="subject db"):
        with L.transaction(by="t") as t:
            t.add("video/G1", "db/values", "bucket://a")
    assert L.values is None
    store(L, "a")
    assert L.values == "bucket://a" == L.at()["db", "db/values"]


def test_an_unknown_triples_scheme_lists_what_is_registered(clouds):
    with pytest.raises(LedgerError, match=r"no triples backend for scheme 'mysql' \(mysql://u:\*\*\*@h/db\): registered: "
                                          r"postgres, postgresql, sqlite; call register_triples\('mysql', factory\)"):
        Ledger("mysql://u:secret@h/db")


def test_a_registered_triples_scheme_opens_the_ledger(clouds, tmp_path):
    from dvc_dat.ledger.store import SqliteStore

    asked = []

    def factory(uri, create, overlay):
        asked.append((uri, create, overlay))
        return SqliteStore(tmp_path / uri.partition("://")[2], overlay)
    register_triples("lite", factory)
    L = Ledger("lite://led", create=True)
    with L.transaction(by="t") as t:
        t.add("s", "p", "o")
    assert asked == [("lite://led", True, None)] and L.triples == "lite://led" == L.path
    assert Ledger(tmp_path / "led").at()["s", "p"] == "o"


def test_a_folder_is_also_written_sqlite(tmp_path, clouds):
    L = Ledger(tmp_path / "led", create=True)
    with L.transaction(by="t") as t:
        t.add("s", "p", "o")
    assert L.triples == f"sqlite://{L.path}"
    again = Ledger(L.triples)
    assert again.path == L.path and again.at()["s", "p"] == "o"
    (tmp_path / ".datconfig.yaml").write_text("root: sqlite://led\ndefault: root\n")
    assert Ledger().path == L.path


BACKEND_MODULE = """
    import shutil
    from pathlib import Path
    from dvc_dat.ledger import register_values
    from dvc_dat.ledger.backends import blob_path


    class Shelf:
        def __init__(self, uri):
            self.root = Path(__file__).parent / uri.partition("://")[2]

        def has(self, h):
            return (self.root / blob_path(h)).exists()

        def pull(self, h, path):
            shutil.copyfile(self.root / blob_path(h), path)

        def push(self, path, h):
            (self.root / blob_path(h)).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, self.root / blob_path(h))


    register_values("shelf", Shelf)
"""


def test_backends_in_the_config_are_imported_on_a_miss(tmp_path, clouds, monkeypatch):
    (tmp_path / "shelf_backend.py").write_text(textwrap.dedent(BACKEND_MODULE))
    monkeypatch.syspath_prepend(str(tmp_path))
    L = Ledger(tmp_path / "led", create=True)
    with pytest.raises(LedgerError, match="no values backend for scheme 'shelf'"):
        with L.transaction(by="t") as t:
            t.add("db", "db/values", "shelf://s")
    (tmp_path / ".datconfig.yaml").write_text("backends: [shelf_backend]\n")
    monkeypatch.setattr(backends_mod, "_IMPORTED", set())
    with L.transaction(by="t") as t:
        t.add("db", "db/values", "shelf://s")
    v = seal_video(L)
    assert (tmp_path / "s" / blob_path(v.hash)).read_bytes() == b"G1 frames"
    sys.modules.pop("shelf_backend", None)


def test_a_fresh_process_has_the_configs_backends(tmp_path, clouds, monkeypatch):
    (tmp_path / "shelf_backend.py").write_text(textwrap.dedent(BACKEND_MODULE))
    (tmp_path / ".datconfig.yaml").write_text("backends: [shelf_backend]\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    folder = tmp_path / "led"
    L = Ledger(folder, create=True)
    with L.transaction(by="t") as t:
        t.add("db", "db/values", "shelf://s")
    seal_video(L)
    shutil.rmtree(L._store.art.root)
    sys.modules.pop("shelf_backend", None)
    script = textwrap.dedent(f"""
        import sys
        sys.path[:0] = [{str(HERE)!r}, {str(tmp_path)!r}]
        from dvc_dat.ledger import Ledger
        print(Ledger({str(folder)!r}).at().load("video/G1").frames.decode())
    """)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "G1 frames"


def test_a_backends_module_that_does_not_import_is_named(tmp_path, clouds):
    (tmp_path / ".datconfig.yaml").write_text("backends: [no_such_backend_module]\n")
    L = Ledger(tmp_path / "led", create=True)
    with pytest.raises(LedgerError, match="backends: cannot import 'no_such_backend_module'"):
        with L.transaction(by="t") as t:
            t.add("db", "db/values", "shelf://s")
    (tmp_path / ".datconfig.yaml").write_text("backends: shelf_backend\n")
    backends_mod._IMPORTED.clear()
    with pytest.raises(LedgerError, match="'backends:' is a list of module names"):
        with L.transaction(by="t") as t:
            t.add("db", "db/values", "shelf://s")


def test_the_removed_stores_key_is_refused(tmp_path, clouds):
    (tmp_path / ".datconfig.yaml").write_text("default: root\nstores: {local: gcp}\n")
    with pytest.raises(LedgerError, match="'stores:' was removed.*db/values.*backends:"):
        Ledger()


# -- file ----------------------------------------------------------------------------------------------------

def test_the_file_backend_round_trips_and_an_art_folder_is_one(tmp_path, clouds):
    L = Ledger(tmp_path / "led", create=True)
    shared = tmp_path / "shared"
    with L.transaction(by="t") as t:
        t.add("db", "db/values", f"file://{shared}")
    v = seal_video(L)
    assert (shared / blob_path(v.hash)).read_bytes() == b"G1 frames"
    drop_cache(L)
    assert L.at().load("video/G1").frames == b"G1 frames" and L._store.art.exists(v.hash)
    other = Ledger(tmp_path / "other", create=True)        # another ledger's art folder, as it stands
    w = seal_video(other, b"G2 frames", "video/G2")
    with L.transaction(by="t") as t:
        t.add("db", "db/values", f"file://{other._store.art.root}")
    assert backends_mod.values_at(L.values).has(w.hash)


def test_a_relative_file_uri_is_refused(L, clouds):
    for bad in ("file://shared/art", "file://host/shared"):
        with L.transaction(by="t") as t:
            t.add("db", "db/values", bad)
        with pytest.raises(LedgerError, match="absolute folder"):
            seal_video(L)


# -- writing and reading -------------------------------------------------------------------------------------

def test_no_row_keeps_the_folder_alone(L, clouds):
    v = seal_video(L)
    assert L.values is None and clouds == {} and L._store.art.exists(v.hash)
    drop_cache(L)
    with pytest.raises(FileNotFoundError):
        L.at().load("video/G1")


def test_a_sealed_value_is_pushed_and_pulled_on_a_miss(L, clouds):
    store(L, "gcp")
    v = seal_video(L)
    gcp = clouds["gcp"]
    assert L.at().get(v.subject, "db/values") is None      # no per-value row: the ledger's row is the one place
    assert gcp.pushes == [v.hash] and (gcp.root / blob_path(v.hash)).read_bytes() == b"G1 frames"
    assert L._store.art.exists(v.hash)                  # the writer's folder keeps its copy
    drop_cache(L)
    back = L.at().load("video/G1")
    assert back.frames == b"G1 frames" and gcp.pulls == [v.hash]
    assert L._store.art.exists(v.hash)                  # the folder is a cache
    L._values.clear()
    L.at().load("video/G1")
    assert gcp.pulls == [v.hash]                        # a hit: nothing pulled again


def test_a_dats_parts_travel_with_it(L, clouds, tmp_path):
    from dvc_dat import core

    before = core._default_manager
    Dat.manager = DatManager(dat_folders=[str(tmp_path / "data")])
    try:
        store(L, "azure")
        dat = Dat.manager.run(SPEC)
        with L.transaction(by="t") as t:
            dat.seal(t, name="table/12")
        az = clouds["azure"]
        assert len(az.pushes) > 1 and dat.hash in az.pushes
        drop_cache(L)
        back = L.at().load("table/12")
        assert (back.path / "table.csv").read_text() == "12 from 1\n"
        assert set(az.pulls) < set(az.pushes)              # its run is a subdat, fetched by its own name (SVP 241)
        L.at().load("table/12/run")
        assert set(az.pulls) == set(az.pushes)
    finally:
        core._default_manager = before


def test_a_row_set_after_a_seal_serves_it(L, clouds):
    """The values URI read is the one at the ledger's top: bytes moved to a bucket after the fact are found."""
    v = seal_video(L)
    sealed_at = L.at().id
    shutil.copytree(L._store.art.root / "sha256", clouds_folder(L, "late") / "sha256")
    store(L, "late")
    drop_cache(L)
    assert L.at(sealed_at).load("video/G1").frames == b"G1 frames" and clouds["late"].pulls == [v.hash]


def clouds_folder(L, name):
    return Path.cwd() / name


def test_the_values_uri_may_move(L, clouds):
    store(L, "azure")
    v = seal_video(L)
    store(L, "gcp")
    w = seal_video(L, b"G2 frames", "video/G2")
    assert clouds["azure"].pushes == [v.hash] and clouds["gcp"].pushes == [w.hash]
    drop_cache(L)
    assert L.at().load("video/G2").frames == b"G2 frames"
    with pytest.raises(LedgerError, match="cannot pull"):      # its bytes stayed where the row no longer points
        L.at().load("video/G1")


def test_push_runs_before_the_write_lock(L, clouds, tmp_path):
    other = Ledger(L.path)
    took = []

    def hook(h):
        with other.transaction(by="other", lock=1) as t:     # LockTimeout if the seal held the lock
            t.add("probe", "note", h[:8])
        took.append(h)
    register_values("bucket", lambda uri: FolderValues(tmp_path / "gcp", hook=hook))
    store(L, "gcp")
    v = seal_video(L)
    assert took == [v.hash] and L.at().get("probe", "note") == v.hash[:8]


def test_a_failed_push_writes_nothing(L, clouds, tmp_path):
    def boom(h):
        raise OSError("bucket refused")
    register_values("bucket", lambda uri: FolderValues(tmp_path / "gcp", hook=boom))
    store(L, "gcp")
    top = L.at().id
    v = Video(b"G1 frames")
    with pytest.raises(OSError, match="bucket refused"):
        with L.transaction(by="t") as t:
            v.seal(t, name="video/G1")
    assert L.at().id == top and v.subject is None and not L._store.art.exists(v.hash)


def test_a_held_blob_is_not_pushed_again(L, clouds):
    store(L, "gcp")
    seal_video(L, name="video/A")
    gcp = clouds["gcp"]
    gcp.pushes.clear()
    with L.transaction(by="t") as t:
        Video(b"G1 frames").seal(t, name="video/B")         # the same bytes: one subject, already held
    assert gcp.pushes == []


def test_a_pull_that_fails_or_lies_is_a_ledger_error(L, clouds):
    store(L, "gcp")
    v = seal_video(L)
    gcp = clouds["gcp"]
    blob = gcp.root / blob_path(v.hash)
    blob.write_bytes(b"other bytes")
    drop_cache(L)
    with pytest.raises(LedgerError, match="hashing to"):
        L.at().load("video/G1")
    assert not L._store.art.exists(v.hash)
    blob.unlink()
    with pytest.raises(LedgerError, match="cannot pull"):
        L.at().load("video/G1")


def test_a_scheme_no_code_registered_is_named_on_the_miss(L, clouds, monkeypatch):
    store(L, "gcp")
    seal_video(L)
    drop_cache(L)
    monkeypatch.setattr(backends_mod, "_VALUES", {"file": backends_mod.FileValues})
    monkeypatch.setattr(backends_mod, "_MADE", {})
    with pytest.raises(LedgerError, match="no values backend for scheme 'bucket'.*registered: file"):
        L.at().load("video/G1")


def test_a_fresh_process_with_an_empty_cache_pulls(tmp_path, clouds):
    folder = tmp_path / "led"
    L = Ledger(folder, create=True)
    store(L, "gcp")
    seal_video(L)
    shutil.rmtree(L._store.art.root)
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(HERE)!r})
        from pathlib import Path
        from dvc_dat.ledger import Ledger, register_values
        from test_backends import FolderValues
        register_values("bucket", lambda uri: FolderValues(Path({str(tmp_path)!r}) / uri.partition("://")[2]))
        print(Ledger({str(folder)!r}).at().load("video/G1").frames.decode())
    """)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=dict(os.environ),
                         cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "G1 frames"


def test_a_copy_pulls_from_the_sources_values_and_pushes_to_the_destinations(L, clouds, tmp_path):
    """SVP 251: the bytes reach a copy by hash, through both values URIs."""
    from dvc_dat.ledger import Ref

    store(L, "gcp")
    v = seal_video(L)
    drop_cache(L)
    other = Ledger(tmp_path / "other", create=True)
    store(other, "azure")
    other.at().copy(Ref(L.at(), v.subject), safe=False)
    assert clouds["azure"].has(v.hash) and other._store.art.exists(v.hash)
    assert other.values == "bucket://azure" and L.values == "bucket://gcp"
    drop_cache(other)
    assert Ref(other.at(), v.subject).load().frames == b"G1 frames"
