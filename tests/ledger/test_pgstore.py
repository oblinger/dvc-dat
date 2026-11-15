"""The Postgres store's own surface: the DSN, the art folder beside it, two handles on one
ledger, the lock, byte-order prefix scans under a non-C collation, NUL, the indexes.
Everything else runs over both stores through the ``L`` fixture."""

import base64
import random
import threading
import time

import pytest

import backends
from dvc_dat.ledger import Ledger, LedgerError, LockTimeout


@pytest.fixture
def dsn(tmp_path):
    return backends.dsn(tmp_path / "led")


def test_pg_dsn_opens_and_missing_is_ledger_error(dsn, tmp_path):
    with pytest.raises(LedgerError, match="no ledger"):
        Ledger(dsn)
    L = Ledger(dsn, create=True)
    assert Ledger(L.path).path == L.path
    assert L._store.art.root == (tmp_path / "cache" / L._store.name / "art").resolve()
    assert ":***@" in repr(L) and ":***@" not in L.path


def test_pg_art_parameter_is_refused_naming_what_replaces_it(dsn):
    with pytest.raises(LedgerError, match=r"\?art=.*removed.*DAT_CACHE.*db/values"):
        Ledger(dsn + "&art=/somewhere", create=True)


def test_pg_cache_is_the_env_then_the_config_and_neither_is_refused(dsn, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAT_CACHE")
    with pytest.raises(LedgerError, match="no cache folder.*DAT_CACHE.*cache:"):
        Ledger(dsn, create=True)
    (tmp_path / ".datconfig.yaml").write_text("cache: bytes\n")
    L = Ledger(dsn, create=True)
    assert L._store.art.root == (tmp_path / "bytes" / L._store.name / "art").resolve()
    monkeypatch.setenv("DAT_CACHE", str(tmp_path / "env"))
    assert Ledger(dsn)._store.art.root == (tmp_path / "env" / L._store.name / "art").resolve()


def test_pg_unreachable_server_is_ledger_error(tmp_path):
    with pytest.raises(LedgerError, match="cannot connect"):
        Ledger("postgresql://nobody:x@127.0.0.1:1/none", create=True)


def test_pg_datconfig_names_the_dsn_and_cache_is_relative_to_it(dsn, tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    (proj / "sub").mkdir(parents=True)
    (proj / ".datconfig.yaml").write_text(f"root: '{dsn}'\ndefault: root\ncache: .dat\n")
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    monkeypatch.delenv("DAT_CACHE")
    monkeypatch.chdir(proj / "sub")
    with pytest.raises(LedgerError, match="no ledger"):
        Ledger()
    monkeypatch.chdir(proj)
    L = Ledger(create=True)
    assert L._store.art.root == (proj / ".dat" / L._store.name / "art").resolve()
    monkeypatch.chdir(proj / "sub")
    assert Ledger()._store.art.root == L._store.art.root
    monkeypatch.setenv("DAT_LEDGER", str(L.path))
    assert Ledger().path == L.path


def test_pg_two_handles_share_one_ledger(dsn):
    a = Ledger(dsn, create=True)
    b = Ledger(dsn)
    with a.transaction(by="a") as t:
        t.add("game/G1", "home", "A")
    with b.transaction(by="b") as t:
        t.add("game/G1", "away", "B")
    assert a.at()["game/G1"] == {"home": "A", "away": "B"} == b.at()["game/G1"]
    assert a.at().id == b.at().id == 2


def test_pg_lock_held_elsewhere_is_lock_timeout(dsn):
    a = Ledger(dsn, create=True)
    b = Ledger(dsn)
    held, done = threading.Event(), threading.Event()

    def hold():
        with a.transaction(by="a", lock=10) as t:
            t.add("s", "p", "a")
            held.set()
            done.wait(5)
    th = threading.Thread(target=hold)
    th.start()
    assert held.wait(5)
    t0 = time.monotonic()
    with pytest.raises(LockTimeout):
        with b.transaction(by="b", lock=0.5) as t:
            t.add("s", "p", "b")
    assert time.monotonic() - t0 < 3
    done.set()
    th.join(10)
    assert b.at().id == 1 and b.at()["s", "p"] == "a"


def test_pg_concurrent_writers_get_contiguous_revisions(dsn):
    Ledger(dsn, create=True)
    errors = []

    def write(n):
        try:
            L = Ledger(dsn)
            for i in range(8):
                with L.transaction(by=f"w{n}") as t:
                    t.add(f"w/{n}", "i", str(i))
        except Exception as e:      # surfaced below
            errors.append(e)
    ths = [threading.Thread(target=write, args=(n,)) for n in range(4)]
    for th in ths:
        th.start()
    for th in ths:
        th.join(60)
    assert not errors
    rev = Ledger(dsn).at()
    assert rev.id == 32
    assert sorted({r[0] for r in rev.ledger._store.rows(rev.id)}) == list(range(1, 33))
    assert {rev[f"w/{n}", "i"] for n in range(4)} == {"7"}


def test_pg_prefix_scan_is_byte_order_whatever_the_collation(dsn):
    L = Ledger(dsn, create=True)
    names = ["x/a", "x-a", "x/b", "xa", "x/", "x/é", "x0", "X/a", "x//"]
    with L.transaction(by="t") as t:
        for n in names:
            t.add(n, "p", "1")
    got = sorted(s for s, _p, _o in L.at().all("x/*"))
    assert got == sorted(n for n in names if n.startswith("x/"))


def test_pg_nul_is_refused_on_write_and_found_nowhere_on_read(dsn):
    L = Ledger(dsn, create=True)
    with pytest.raises(LedgerError, match="NUL"):
        with L.transaction(by="t") as t:
            t.add("a\x00b", "p", "1")
    assert L.at().id == 0
    assert L.at().get("a\x00b", "p") is None


def test_pg_indexes_and_the_prefix_plan(dsn):
    L = Ledger(dsn, create=True)
    with L.transaction(by="t") as t:
        t.add("db/pred/home", "db/index", "true")
    names = L._store.index_names()
    assert {"quads_sp", "quads_po"} <= set(names) and any(n.startswith("pred_") for n in names)
    conn = L._store._reader()
    conn.execute("SET enable_seqscan = off")
    plan = " ".join(r[0] for r in conn.execute(
        "EXPLAIN SELECT rev FROM quads WHERE subject ~>=~ %s AND subject ~<~ %s", ("x/", "x/\U0010ffff")))
    conn.execute("RESET enable_seqscan")
    assert "quads_sp" in plan


def test_pg_close_ends_the_server_backends(dsn):
    import psycopg

    L = Ledger(dsn, create=True)
    th = [threading.Thread(target=lambda: L.at().id) for _ in range(3)]
    for x in th:
        x.start()
    for x in th:
        x.join()
    pids = {c.info.backend_pid for c in L._store._readers}
    assert len(pids) == 3
    q = "SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(%s)"
    with psycopg.connect(backends.database(), autocommit=True) as admin:
        assert admin.execute(q, (list(pids),)).fetchone()[0] == 3
        L.close()
        for _ in range(50):
            if admin.execute(q, (list(pids),)).fetchone()[0] == 0:
                break
            time.sleep(0.1)
        assert admin.execute(q, (list(pids),)).fetchone()[0] == 0


def test_pg_lock_alarm_mid_read_leaves_the_reader_usable(dsn):
    """``lock=`` interrupting a read in the body: LockTimeout, nothing written, and the next read works
    (an interrupted psycopg connection left "another command is already in progress")."""
    L = Ledger(dsn, create=True)
    with L.transaction(by="t") as t:
        t.add("game/G1", "home", "A")
    for _ in range(3):
        with pytest.raises(LockTimeout):
            with L.transaction(by="slow", lock=0.2) as t:
                t.add("game/G1", "away", "B")
                L._store.read("SELECT pg_sleep(2)")
        assert L.at().get("game/G1", "home") == "A"
        assert L.at().get("game/G1", "away") is None
    with L.transaction(by="t", lock=5) as t:
        t.add("game/G1", "away", "C")
    assert L.at().get("game/G1", "away") == "C"


#: past Postgres's 8191-byte btree entry even compressed (a sandboxed call's ``db/modules`` is ~20 KB)
BIG = base64.b64encode(random.Random(255).randbytes(15000)).decode()


def _plan(L, sql, params):
    conn = L._store._reader()
    conn.execute("SET enable_seqscan = off")
    try:
        return " ".join(r[0] for r in conn.execute("EXPLAIN " + sql, params))
    finally:
        conn.execute("RESET enable_seqscan")


def test_pg_a_20kb_object_is_stored_and_found_by_object_equality(dsn):
    """``quads_po`` and a ``db/index`` partial index hold ``md5(object)``, not the object (SVP 255 Q3): a
    20 KB object commits, reads back whole, and an object-equality lookup finds it through the index."""
    L = Ledger(dsn, create=True)
    with L.transaction(by="t") as t:
        t.add("db/pred/modules", "db/index", "true")
    with L.transaction(by="t") as t:
        t.add("code/a", "modules", BIG)
        t.add("code/b", "modules", BIG[:-1])
        t.add("code/c", "other", BIG)
    assert L.at().get("code/a", "modules") == BIG
    top, obj = L.at().id, L._store.rows(L.at().id, subject="code/a")[0][4]
    assert len(obj) > 20000
    assert L._store.subjects(top, predicate="modules", obj=obj) == ["code/a"]
    assert [r[2] for r in L._store.rows(top, predicate="other", obj=obj)] == ["code/c"]
    q = "SELECT subject FROM quads WHERE predicate = %s AND md5(object) = md5(%s) AND object = %s"
    assert "quads_po" in _plan(L, q, ("other", obj, obj))
    assert "pred_" in _plan(L, q, ("modules", obj, obj))


def test_pg_migrate_rebuilds_the_object_indexes_and_is_idempotent(dsn):
    """A ledger made before 3.1.1 indexes the object itself; ``migrate`` rebuilds ``quads_po`` and every
    ``db/index`` partial index on ``md5(object)``, keeps their names, and a second run changes nothing."""
    from dvc_dat.ledger import pgstore

    L = Ledger(dsn, create=True)
    with L.transaction(by="t") as t:
        t.add("db/pred/home", "db/index", "true")
        t.add("game/G1", "home", "A")
    conn = L._store._reader()
    pred = next(n for n in L._store.index_names() if n.startswith("pred_"))
    conn.execute("DROP INDEX quads_po")
    conn.execute("CREATE INDEX quads_po ON quads (predicate, object text_pattern_ops, rev)")
    conn.execute(f'DROP INDEX "{pred}"')
    conn.execute(f"CREATE INDEX \"{pred}\" ON quads (object text_pattern_ops, subject, rev) WHERE predicate = 'home'")
    assert pgstore.migrate(dsn) == ["quads_po", pred]
    defs = dict(conn.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema()"
                             " AND tablename = 'quads'").fetchall())
    assert "md5(object)" in defs["quads_po"] and "md5(object)" in defs[pred] and "'home'" in defs[pred]
    assert pgstore.migrate(dsn) == []
    with L.transaction(by="t") as t:
        t.add("code/a", "home", BIG)
    obj = L._store.rows(L.at().id, subject="code/a")[0][4]
    assert L._store.subjects(L.at().id, predicate="home", obj=obj) == ["code/a"]
    assert L.at().get("game/G1", "home") == "A"


def test_pg_a_read_at_a_committed_revision_is_answered_once_then_from_memory(dsn):
    """SVP 255: rows are only appended, a revision in one transaction, so a read at or below a top this store saw
    committed never changes: its second asking is no round trip. A read above it, or through an open write
    transaction, always goes to the server; a later commit is seen at the new top."""
    L = Ledger(dsn, create=True)
    with L.transaction(by="t") as t:
        t.add("game/G1", "home", "A")
    st = L._store
    asked = []
    real = st.read

    def read(sql, params=()):
        asked.append(sql)
        return real(sql, params)
    st.read = read
    top = L.at().id                                 # top() sees the commit: reads at or below it settle
    first = st.rows(top, subject="game/G1")
    n = len(asked)
    assert st.rows(top, subject="game/G1") == first and len(asked) == n
    assert st.subjects(top, predicate="home") == ["game/G1"] and st.subjects(top, predicate="home") == ["game/G1"]
    assert len(asked) == n + 1
    assert st.has_predicate("home", top) and st.has_predicate("home", top) and len(asked) == n + 2
    st.rows(top + 5, subject="game/G1")
    st.rows(top + 5, subject="game/G1")             # above the settled top: asked each time
    assert len(asked) == n + 4
    with st.writer(10, locked=False) as w, st.reading_through(w):
        st.rows(top, subject="game/G1")
        st.rows(top, subject="game/G1")                 # through an open write transaction: never kept
    assert len(asked) == n + 6
    with L.transaction(by="t") as t:
        t.add("game/G1", "away", "B")
    assert L.at()["game/G1"] == {"home": "A", "away": "B"}
    assert st.rows(top, subject="game/G1") == first


def test_pg_the_settled_cache_is_bounded(dsn, monkeypatch):
    from dvc_dat.ledger import pgstore

    monkeypatch.setattr(pgstore, "CACHE_ENTRIES", 3)
    monkeypatch.setattr(pgstore, "CACHE_MAX_RESULT", 1)
    L = Ledger(dsn, create=True)
    with L.transaction(by="t") as t:
        for i in range(5):
            t.add(f"s/{i}", "p", "x")
    st, top = L._store, L.at().id
    for i in range(5):
        st.rows(top, subject=f"s/{i}")
    st.rows(top, predicate="p")                     # five rows: over the largest result kept
    assert len(st._cache) == 3 and ("rows", top, None, "p", None, None, 0) not in st._cache
