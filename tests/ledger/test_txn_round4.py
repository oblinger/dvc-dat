"""Transaction latent bugs (deep scan round 4, 2026-10-27): bytes dropped outside the write lock or after
COMMIT, a record write left half done, the caller's itimer cancelled, the clock keeping a lower version, the
subjects order past 10**6 rows, a NaN stored as JSON, a create that breaks the config, an empty location."""

import signal
import sqlite3
import threading
import time

import pytest

from dvc_dat.ledger import Ledger, LockTimeout, Value


def write(L, *triples):
    with L.transaction(by="t") as t:
        for s, p, o in triples:
            t.add(s, p, o)


@pytest.fixture
def SL(tmp_path):
    """A sqlite ledger (the store's own connection and SQL are what these tests reach)."""
    return Ledger(tmp_path / "sqlite-ledger", create=True)


def test_a_refused_record_write_writes_none_of_its_rows(L):
    write(L, ("g", "home", "a"), ("g", "date", "d"))
    with L.transaction(by="t", lock=5) as t:
        with pytest.raises(TypeError):
            t["g"] = {"home": "b", "bad": 5}               # 5 is refused by _encode
    assert t.rev["g"] == {"home": "a", "date": "d"}


def test_a_refused_commit_drops_its_bytes_while_it_holds_the_write_lock(SL, monkeypatch):
    """Dropped after the lock went, the bytes could be another writer's, committed in the window:
    it found them stored, so it neither wrote them nor claimed them."""
    from dvc_dat.ledger.txn import Transaction

    write(SL, ("db/pred/n", "db/type", "json"))
    real = Transaction._abandon
    held = []

    def abandon(self, *a, **kw):
        if self._state == "committing":
            out = []

            def other():
                try:
                    with SL._store.writer(0.2, locked=True):
                        out.append(False)
                except LockTimeout:
                    out.append(True)
            th = threading.Thread(target=other)
            th.start()
            th.join()
            held.extend(out)
        return real(self, *a, **kw)
    monkeypatch.setattr(Transaction, "_abandon", abandon)
    with pytest.raises(TypeError, match="db/type"):
        with SL.transaction(by="A") as ta:
            Value.Blob({"same": "bytes"}).seal(ta)
            ta.add("g", "n", "not json")                    # refused at commit by the db/type check
    assert held == [True]


def test_an_interrupt_after_commit_keeps_the_committed_bytes(SL, monkeypatch):
    store = SL._store
    real_connect = store._connect

    class Conn(sqlite3.Connection):
        committed = False

        def execute(self, sql, *a):
            out = super().execute(sql, *a)
            if sql == "COMMIT":
                Conn.committed = True
            return out

        def close(self):
            super().close()
            if Conn.committed:
                Conn.committed = False
                raise KeyboardInterrupt            # a signal / async LockTimeout right after COMMIT

    def connect(timeout):
        return sqlite3.connect(str(store.path), isolation_level=None, timeout=timeout,
                               check_same_thread=False, factory=Conn)
    monkeypatch.setattr(store, "_connect", connect)
    with pytest.raises(KeyboardInterrupt):
        with SL.transaction(by="t") as t:
            Value.Blob({"k": "v"}).seal(t)
    monkeypatch.setattr(store, "_connect", real_connect)
    top = SL.at()
    subj = list(top._store.subjects(top.id, predicate="db/value"))
    assert subj, "the revision committed"
    assert top.load(subj[0]) is not None


def test_subjects_keep_row_order_past_a_million_rows_in_one_revision(SL):
    store = SL._store
    with store.writer(30.0, locked=False) as w:
        w.insert(1, [("bulk", "p", "str:x", True)] * 1_000_001 + [("late", "q", "str:x", True)])
    with store.writer(30.0, locked=False) as w:
        w.insert(2, [("next", "q", "str:x", True)])
    assert store.subjects(2, predicate="q") == ["late", "next"]


def test_a_nan_is_not_json(L):
    with pytest.raises(TypeError):
        with L.transaction(by={"x": float("nan")}):
            pass
    with pytest.raises(TypeError):
        with L.transaction(by="t") as t:
            t.add("g", "p", {"x": float("inf")})


def test_a_locked_transaction_keeps_the_callers_itimer(L):
    fired = []
    old = signal.signal(signal.SIGALRM, lambda *a: fired.append(1))
    try:
        signal.setitimer(signal.ITIMER_REAL, 0.3)
        with L.transaction(by="t", lock=5) as t:
            t.add("g", "p", "o")
        time.sleep(0.5)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
    assert fired


def test_the_clock_takes_the_highest_version_one_body_ran(L):
    with L.transaction(by="a") as t:
        t._advance_clock("testrepo", "pkg", "1.0.0", "abc1234")
        t._advance_clock("testrepo", "pkg", "1.1.0", "abc1234")
        t._advance_clock("testrepo", "pkg", "1.0.5", "abc1234")
    assert t.rev["db/repo/testrepo/pkg", "db/version"] == "1.1.0"


def test_create_refuses_a_config_that_is_not_a_mapping(tmp_path, monkeypatch):
    from dvc_dat.ledger import LedgerError

    monkeypatch.delenv("DAT_LEDGER", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".datconfig.yaml").write_text("- a\n")
    with pytest.raises(LedgerError, match="not a mapping"):
        Ledger(create=True)
    assert (tmp_path / ".datconfig.yaml").read_text() == "- a\n"


def test_an_empty_location_is_refused(SL, monkeypatch):
    monkeypatch.chdir(SL.path)
    with pytest.raises(TypeError, match="empty location"):
        Ledger("")
