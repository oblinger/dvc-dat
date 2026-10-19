"""The Postgres store's own surface: the DSN, the art folder beside it, two handles on one
ledger, the lock, byte-order prefix scans under a non-C collation, NUL, the indexes.
Everything else runs over both stores through the ``L`` fixture."""

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
    assert L._store.art.root == (tmp_path / "led" / "art").resolve()
    assert ":***@" in repr(L) and ":***@" not in L.path


def test_pg_dsn_without_art_is_refused(dsn):
    with pytest.raises(LedgerError, match="art"):
        Ledger(dsn.split("&art=")[0], create=True)


def test_pg_unreachable_server_is_ledger_error(tmp_path):
    with pytest.raises(LedgerError, match="cannot connect"):
        Ledger(f"postgresql://nobody:x@127.0.0.1:1/none?art={tmp_path}", create=True)


def test_pg_datconfig_names_the_dsn_and_art_is_relative_to_it(dsn, tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    (proj / "sub").mkdir(parents=True)
    rel = dsn.split("&art=")[0] + "&art=.dat/art"
    (proj / ".datconfig.yaml").write_text(f"ledger: {rel}\n")
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    monkeypatch.chdir(proj / "sub")
    with pytest.raises(LedgerError, match="no ledger"):
        Ledger()
    monkeypatch.chdir(proj)
    L = Ledger(create=True)
    assert L._store.art.root == (proj / ".dat" / "art").resolve()
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
