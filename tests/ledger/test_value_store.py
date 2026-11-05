"""SVP 1511: a ledger names its value store, ``(db, db/store, <name>)``; ``local`` is the store this process runs in.

Every case runs against a fake, folder-backed remote registered through the public ``register_store``,
as ``gcp`` and ``azure``: what a consumer (sv-pipe) does with its own cloud code.
"""

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dvc_dat import Dat, DatManager
from dvc_dat.ledger import Ledger, LedgerError, LockTimeout, Remote, register_store
from dvc_dat.ledger import remote as remote_mod
from dvc_dat.ledger.remote import blob_name, resolve_local
from ledger_kinds import Video

HERE = Path(__file__).parent
SPEC = {"dat": {"do": "ledger_kinds.build_table", "name": "tables/table{unique}", "kwargs": {"n": 12, "start": 1}}}


class FolderRemote:
    """A remote that is a folder: ``<root>/ledgers/<ledger>/sha256/<2>/<hash>``, counting its calls."""

    def __init__(self, root: Path, ledger: str, hook=None):
        self.root, self.ledger, self.hook = Path(root), ledger, hook
        self.puts, self.gets = [], []

    def _p(self, h):
        return self.root / blob_name(self.ledger, h)

    def exists(self, h):
        return self._p(h).exists()

    def put_path(self, path, h):
        if self.hook:
            self.hook(h)
        self.puts.append(h)
        self._p(h).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, self._p(h))

    def get_to(self, h, dest):
        self.gets.append(h)
        shutil.copyfile(self._p(h), dest)


@pytest.fixture
def clouds(tmp_path, monkeypatch):
    """``gcp`` and ``azure`` registered as folder remotes under ``tmp_path/<cloud>``; ``local`` is ``folder`` unless a
    test says otherwise (no probe, no config)."""
    monkeypatch.setattr(remote_mod, "STORES", {})
    monkeypatch.setattr(remote_mod, "_REMOTES", {})
    monkeypatch.setattr(remote_mod, "probe", lambda: None)
    monkeypatch.delenv("DAT_STORE_LOCAL", raising=False)
    monkeypatch.chdir(tmp_path)
    made = {}

    def factory(cloud):
        def make(ledger):
            made[cloud] = FolderRemote(tmp_path / cloud, ledger)
            return made[cloud]
        return make
    register_store("gcp", factory("gcp"))
    register_store("azure", factory("azure"))
    return made


def store(L, name):
    with L.transaction(by="t") as t:
        t.add("db", "db/store", name)


def drop_cache(L):
    """The writer's copy gone: the art folder emptied and the handle's loaded values forgotten."""
    shutil.rmtree(L._store.art.root, ignore_errors=True)
    L._values.clear()


def seal_video(L, frames=b"G1 frames", name="video/G1"):
    v = Video(frames)
    with L.transaction(by="t") as t:
        v.seal(t, name=name)
    return v


def test_register_store_refuses_the_built_in_names_and_bad_ones(clouds):
    for bad in ("local", "folder"):
        with pytest.raises(ValueError, match="built-in"):
            register_store(bad, lambda ledger: None)
    with pytest.raises(ValueError):
        register_store("Gcp", lambda ledger: None)
    with pytest.raises(TypeError):
        register_store("aws", "not callable")
    assert isinstance(FolderRemote(Path("."), "x"), Remote)


def test_a_db_store_row_is_a_store_name(L, clouds):
    with pytest.raises(ValueError, match="db/store"):
        store(L, "gs://bucket")
    store(L, "gcp")
    assert L.at()["db", "db/store"] == "gcp"


def test_no_row_and_no_local_store_keeps_the_folder_alone(L, clouds):
    v = seal_video(L)
    assert L.at().get(v.subject, "db/store") is None and clouds == {}
    drop_cache(L)
    with pytest.raises(FileNotFoundError):
        L.at().load("video/G1")


def test_a_value_sealed_on_gcp_is_fetched_from_gcp_on_a_miss(L, clouds):
    store(L, "gcp")
    v = seal_video(L)
    gcp = clouds["gcp"]
    assert L.at().get(v.subject, "db/store") == "gcp"
    assert gcp.puts == [v.hash] and (gcp.root / blob_name(L._store.name, v.hash)).read_bytes() == b"G1 frames"
    assert L._store.art.exists(v.hash)                  # the writer's folder keeps its copy
    drop_cache(L)
    back = L.at().load("video/G1")
    assert back.frames == b"G1 frames" and gcp.gets == [v.hash]
    assert L._store.art.exists(v.hash)                  # the folder is now a cache
    L._values.clear()
    L.at().load("video/G1")
    assert gcp.gets == [v.hash]                         # a hit: nothing fetched again


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
        assert len(az.puts) > 1 and dat.hash in az.puts
        drop_cache(L)
        back = L.at().load("table/12")
        assert (back.path / "table.csv").read_text() == "12 from 1\n"
        assert set(az.gets) == set(az.puts)
    finally:
        core._default_manager = before


def test_local_is_the_env_store(L, clouds, monkeypatch):
    monkeypatch.setenv("DAT_STORE_LOCAL", "gcp")
    v = seal_video(L)                                   # no row: local
    assert L.at().get(v.subject, "db/store") == "gcp" and "azure" not in clouds
    monkeypatch.setenv("DAT_STORE_LOCAL", "aws")
    with pytest.raises(LedgerError, match="aws"):
        resolve_local()
    monkeypatch.setenv("DAT_STORE_LOCAL", "folder")
    assert resolve_local() == "folder"


def test_local_order_env_probe_config_folder(clouds, monkeypatch, tmp_path):
    assert resolve_local() == "folder"
    (tmp_path / ".datconfig.yaml").write_text("dat_folders: [data]\n")
    (tmp_path / ".datconfig.override.yaml").write_text("stores: {local: azure}\n")
    assert resolve_local() == "azure"
    monkeypatch.setattr(remote_mod, "probe", lambda: "gcp")
    assert resolve_local() == "gcp"
    monkeypatch.setattr(remote_mod, "probe", lambda: "oracle")       # a cloud no code here registered
    assert resolve_local() == "azure"
    monkeypatch.setenv("DAT_STORE_LOCAL", "folder")
    assert resolve_local() == "folder"


def test_nothing_registered_means_folder_and_no_probe(monkeypatch):
    monkeypatch.setattr(remote_mod, "STORES", {})
    monkeypatch.delenv("DAT_STORE_LOCAL", raising=False)
    monkeypatch.setattr(remote_mod, "probe", lambda: pytest.fail("probed with no store registered"))
    assert resolve_local() == "folder"


def test_a_value_on_azure_is_read_from_a_gcp_process(L, clouds, monkeypatch):
    store(L, "azure")
    v = seal_video(L)
    monkeypatch.setenv("DAT_STORE_LOCAL", "gcp")
    drop_cache(L)
    assert L.at().load("video/G1").frames == b"G1 frames"
    assert clouds["azure"].gets == [v.hash] and "gcp" not in clouds


def test_upload_runs_before_the_write_lock(L, clouds, tmp_path):
    other = Ledger(L.path)
    took = []

    def hook(h):
        with other.transaction(by="other", lock=1) as t:     # LockTimeout if the seal held the lock
            t.add("probe", "note", h[:8])
        took.append(h)
    register_store("gcp", lambda ledger: FolderRemote(tmp_path / "gcp", ledger, hook=hook))
    store(L, "gcp")
    v = seal_video(L)
    assert took == [v.hash] and L.at().get("probe", "note") == v.hash[:8]


def test_a_failed_upload_writes_nothing(L, clouds, tmp_path):
    def boom(h):
        raise OSError("bucket refused")
    register_store("gcp", lambda ledger: FolderRemote(tmp_path / "gcp", ledger, hook=boom))
    store(L, "gcp")
    top = L.at().id
    v = Video(b"G1 frames")
    with pytest.raises(OSError, match="bucket refused"):
        with L.transaction(by="t") as t:
            v.seal(t, name="video/G1")
    assert L.at().id == top and v.subject is None and not L._store.art.exists(v.hash)


def test_a_held_blob_is_not_uploaded_again(L, clouds):
    store(L, "gcp")
    seal_video(L, name="video/A")
    gcp = clouds["gcp"]
    gcp.puts.clear()
    with L.transaction(by="t") as t:
        Video(b"G1 frames").seal(t, name="video/B")         # the same bytes: one subject, already held
    assert gcp.puts == []


def test_a_fetch_that_fails_or_lies_is_a_ledger_error(L, clouds):
    store(L, "gcp")
    v = seal_video(L)
    gcp = clouds["gcp"]
    blob = gcp.root / blob_name(L._store.name, v.hash)
    blob.write_bytes(b"other bytes")
    drop_cache(L)
    with pytest.raises(LedgerError, match="hashing to"):
        L.at().load("video/G1")
    assert not L._store.art.exists(v.hash)
    blob.unlink()
    with pytest.raises(LedgerError, match="cannot fetch"):
        L.at().load("video/G1")


def test_a_store_no_code_registered_is_named_on_the_miss(L, clouds, monkeypatch):
    store(L, "gcp")
    seal_video(L)
    drop_cache(L)
    monkeypatch.setattr(remote_mod, "STORES", {})
    monkeypatch.setattr(remote_mod, "_REMOTES", {})
    with pytest.raises(LedgerError, match="'gcp'.*register_store"):
        L.at().load("video/G1")


def test_a_fresh_process_with_an_empty_cache_fetches(tmp_path, monkeypatch, clouds):
    folder = tmp_path / "led"
    L = Ledger(folder, create=True)
    store(L, "gcp")
    seal_video(L)
    shutil.rmtree(L._store.art.root)
    script = textwrap.dedent(f"""
        import shutil, sys
        sys.path.insert(0, {str(HERE)!r})
        from pathlib import Path
        from dvc_dat.ledger import Ledger, register_store
        from test_value_store import FolderRemote
        register_store("gcp", lambda ledger: FolderRemote(Path({str(tmp_path / 'gcp')!r}), ledger))
        print(Ledger({str(folder)!r}).at().load("video/G1").frames.decode())
    """)
    env = dict(os.environ)
    env.pop("DAT_STORE_LOCAL", None)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "G1 frames"


def test_a_copy_fetches_from_the_sources_store_and_lands_on_the_destinations(L, clouds, tmp_path):
    """SVP 251: the bytes reach a copy by hash, through both stores; the store row is the destination's."""
    from dvc_dat.ledger import Ref

    store(L, "gcp")
    v = seal_video(L)
    drop_cache(L)
    other = Ledger(tmp_path / "other", create=True)
    store(other, "azure")
    other.at().copy(Ref(L.at(), v.subject), safe=False)
    assert clouds["azure"].exists(v.hash) and other._store.art.exists(v.hash)
    assert other.at()[v.subject, "db/store"] == "azure" and L.at()[v.subject, "db/store"] == "gcp"
    drop_cache(other)
    assert Ref(other.at(), v.subject).load().frames == b"G1 frames"
