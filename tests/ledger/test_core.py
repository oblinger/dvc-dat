"""Contracts of the core: the constructor, transactions, the row reads, the bracket, db/type, bump."""


import pytest

from dvc_dat.ledger import Ledger, LedgerError, LockTimeout, Ref, Rev, Row, Unlocked, bump


def write(L, *ops, by="t"):
    with L.transaction(by=by) as t:
        for op in ops:
            if op[0] == "-":
                t.remove(*op[1:])
            else:
                t.add(*op)
    return t.rev


# -- the constructor (A49, A54) ------------------------------------------------------------------

def test_path_opens_and_missing_is_ledger_error(tmp_path):
    with pytest.raises(LedgerError):
        Ledger(tmp_path / "nope")
    assert not (tmp_path / "nope").exists()
    L = Ledger(tmp_path / "led", create=True)
    assert (tmp_path / "led" / "ledger.db").is_file() and L.at().id == 0
    assert Ledger(tmp_path / "led").path == L.path


def test_path_names_a_folder_never_a_file(tmp_path):
    (tmp_path / "f.db").write_text("x")
    with pytest.raises(LedgerError):
        Ledger(tmp_path / "f.db", create=True)


def test_walk_up_finds_the_config_and_none_is_ledger_error(tmp_path, monkeypatch):
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    with pytest.raises(LedgerError, match="searched|.datconfig"):
        Ledger()
    monkeypatch.chdir(tmp_path)
    L = Ledger(create=True)
    assert (tmp_path / ".datconfig.yaml").read_text() == "ledger: .dat/ledger\n"
    monkeypatch.chdir(deep)
    assert Ledger().path == L.path


def test_create_in_cwd_opens_an_existing_config_and_refuses_with_dat_ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".datconfig.yaml").write_text("ledger: elsewhere\n")
    L = Ledger(create=True)
    assert L.path == (tmp_path / "elsewhere").resolve()
    assert (tmp_path / ".datconfig.yaml").read_text() == "ledger: elsewhere\n"
    monkeypatch.setenv("DAT_LEDGER", str(tmp_path / "elsewhere"))
    with pytest.raises(ValueError):
        Ledger(create=True)
    assert Ledger().path == L.path


def test_mounts_sugar_asserted_once_on_walk_up(tmp_path, monkeypatch):
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    monkeypatch.chdir(tmp_path)
    Ledger(create=True)
    (tmp_path / ".datconfig.yaml").write_text("ledger: .dat/ledger\nmounts:\n  pkg.etl: pkg/etl\n")
    L = Ledger()
    rev = L.at()
    assert rev["db/mount/pkg.etl"] == {"db/root": "pkg/etl", "db/repo": tmp_path.name}
    assert rev[rev.tx, "db/by"].startswith("config:")
    assert Ledger().at().id == rev.id                       # unchanged: nothing written


# -- transactions ---------------------------------------------------------------------------------

def test_one_transaction_one_revision_and_tx_rows_last(L):
    with L.transaction(by="human:dan", why="w") as t:
        t.add("s", "p", "1")
        t.add(t.tx, "checked", "yes")
    rev = t.rev
    assert rev.id == 1 and rev.tx == "db/tx/1"
    rows = [(r.subject, r.predicate) for r in rev.rows()]
    assert rows[:2] == [("s", "p"), ("db/tx/1", "checked")]
    assert rows[2:5] == [("db", "db/format"), ("db/tx/1", "db/by"), ("db/tx/1", "db/time")]
    assert rev[rev.tx, "why"] == "w"


def test_every_transaction_is_stamped_and_time_is_refused(L):
    with L.transaction(by="t") as t:
        t.add("s", "p", "1")
    assert len(t.rev[t.rev.tx, "db/time"]) == 20                 # UTC, YYYY-MM-DDTHH:MM:SSZ
    with pytest.raises(TypeError, match="time= is gone"):
        L.transaction(by="t", time=True)


def test_by_is_a_str_or_a_json_dict_read_back_as_written(L):
    who = {"host": "github.com", "user": "dan", "admins": ["root"]}
    with L.transaction(by=who) as t:
        t.add("s", "p", "1")
    assert t.rev[t.rev.tx, "db/by"] == who                      # a dict, not an encoded string
    raw = [r.object for r in t.rev.rows(t.rev.tx, "db/by")]
    assert raw == [who]
    stored = L._store.rows(t.rev.id, subject=t.rev.tx, predicate="db/by")
    assert [r[4] for r in stored] == ['json:{"admins":["root"],"host":"github.com","user":"dan"}']
    with L.transaction(by="eval:x") as t2:                      # a str stays a str, eval: and all
        pass
    assert t2.rev[t2.rev.tx, "db/by"] == "eval:x"


@pytest.mark.parametrize("by", ["", {}, [], ["a"], None, 3, {"x": object()}])
def test_by_anything_else_is_refused_and_writes_nothing(L, by):
    with pytest.raises(TypeError, match="by"):
        L.transaction(by=by)
    assert L.at().id == 0


def test_an_exception_writes_nothing(L):
    with pytest.raises(RuntimeError):
        with L.transaction(by="t") as t:
            t.add("s", "p", "1")
            raise RuntimeError
    assert L.at().id == 0


def test_add_refuses_numbers_and_values_and_db_value(L):
    with pytest.raises(TypeError):
        with L.transaction(by="t") as t:
            t.add("s", "p", 3)
    with pytest.raises(TypeError):
        with L.transaction(by="t") as t:
            t.add("s", "db/value", "x")


def test_lock_timeout_writes_nothing(L):
    import time
    with pytest.raises(LockTimeout):
        with L.transaction(by="t", lock=0.2) as t:
            t.add("s", "p", "1")
            time.sleep(1)
    assert L.at().id == 0


# -- the fold (Q19, Q27, A12, A50) ----------------------------------------------------------------

def test_one_latest_add_wins_in_body_order(L):
    rev = write(L, ("g", "o", "kim"), ("g", "o", "ortiz"))
    assert rev["g", "o"] == "ortiz"


def test_many_earliest_surviving_add_order(L):
    write(L, ("db/pred/o", "db/cardinality", "many"))
    write(L, ("g", "o", "kim"), ("g", "o", "ortiz"))
    r3 = write(L, ("g", "o", "lee"), ("g", "o", "kim"))
    assert r3.all("g", "o") == ["kim", "ortiz", "lee"]
    write(L, ("-", "g", "o", "kim"))
    r5 = write(L, ("g", "o", "kim"))
    assert r5.all("g", "o") == ["ortiz", "lee", "kim"]
    assert r5["g", "o", "kim"] == r5 and r5["g", "o", "ortiz"].id == 2
    assert [(r.rev.id, r.added) for r in r5.rows("g", "o", "kim")] == [(2, True), (3, True), (4, False), (5, True)]


def test_bracket_reads(L):
    write(L, ("db/pred/o", "db/cardinality", "many"))
    rev = write(L, ("g", "home", "G4"), ("g", "o", "a"), ("g", "o", "b"))
    assert rev["g"] == {"home": "G4", "o": ["a", "b"]}
    with pytest.raises(TypeError, match="all"):
        rev["g", "o"]
    with pytest.raises(TypeError):
        rev["g*"]
    with pytest.raises(KeyError):
        rev["g", "away"]
    with pytest.raises(KeyError):
        rev["nobody"]
    with pytest.raises(KeyError):
        rev["g", "home", "G5"]
    assert rev.get("g", "away", default="x") == "x"


def test_rows_by_pattern_is_every_change(L):
    write(L, ("s", "v", "1"))
    write(L, ("s", "v", "2"))
    write(L, ("t", "v", "9"))
    rev = write(L, ("-", "s", "v", "2"))
    assert [(r.rev.id, r.object, r.added) for r in rev.rows("s", "v")] == [(1, "1", True), (2, "2", True),
                                                                          (4, "2", False)]
    assert [r.subject for r in rev.rows("*", "v")] == ["s", "s", "t", "s"]
    assert [r.rev.id for r in rev.rows("s", "v", since=rev.ledger.at(2))] == [4]
    with pytest.raises(TypeError, match="at most 3"):
        rev.rows("s", "v", "1", "x")


def test_rows_are_rev_and_decoded(L):
    rev = write(L, ("s", "doc", {"a": 1}))
    row = rev.rows()[0]
    assert isinstance(row, Row) and isinstance(row.rev, Rev) and row.object == {"a": 1} and row.added
    assert "doc" in str(row)


def test_at_digit_string_and_version(L):
    write(L, ("db", "version", "1.0.0"))
    write(L, ("x", "y", "z"))
    assert L.at("1").id == 1 and L.at("1.0.0").id == 1
    with pytest.raises(KeyError):
        L.at(9)


def test_all_glob_and_since(L):
    write(L, ("game/G1", "home", "a"))
    r2 = write(L, ("game/G2", "home", "b"), ("other", "home", "c"))
    assert r2.all("game/*", "home") == [("game/G1", "a"), ("game/G2", "b")]
    assert [x for x in r2.all(since=L.at(1)) if not x[0].startswith("db/tx")] == \
        [("game/G2", "home", "b"), ("other", "home", "c")]
    with pytest.raises(ValueError):
        r2.all("*/G1")


def test_select_and_refs_on_plain_subjects(L):
    rev = write(L, ("game/G1", "home", "G4"), ("game/G1", "away", "G5"), ("game/G2", "home", "G1"))
    assert rev.select(("home", "away"), s="game/*") == [("G4", "G5"), ("G1", None)]
    assert [r.subject for r in rev.refs(home="G1")] == ["game/G2"]
    assert Ref(rev, "game/G1").preds == {"home": "G4", "away": "G5"}


def test_unindexed_dotted_typo(L):
    from dvc_dat.ledger import Unindexed
    rev = write(L, ("s", "metrics.score", "1"))
    assert rev.refs(where={"metrics.score": "1"})
    with pytest.raises(Unindexed):
        rev.refs(where={"metrics.scroe": "1"})


# -- the bracket write (Q29, A34, A43, A44) -------------------------------------------------------

def test_record_write_is_closed_world_over_user_rows(L):
    with L.transaction(by="t", lock=10) as t:
        t["g"] = {"home": "a", "date": "d"}
    with L.transaction(by="t", lock=10) as t:
        t["g"] = {"home": "a"}
    assert t.rev["g"] == {"home": "a"}
    with L.transaction(by="t", lock=10) as t:
        t["g"] = t.previous_rev["g"]
    assert [r for r in t.rev.rows(since=L.at(t.rev.id - 1)) if not r.subject.startswith("db/tx")] == []
    with pytest.raises(TypeError):
        with L.transaction(by="t", lock=10) as t:
            t["g"] = {"home": "a", "db/doc": "x"}
    with L.transaction(by="t", lock=10) as t:
        del t["g"]
    assert t.rev.get("g", "home") is None


def test_bracket_many_and_glob_refusals(L):
    write(L, ("db/pred/o", "db/cardinality", "many"))
    with pytest.raises(TypeError):
        with L.transaction(by="t") as t:
            t["g", "o"] = "x"
    with L.transaction(by="t", lock=10) as t:
        t["g"] = {"o": ["a", "b"]}
    with L.transaction(by="t", lock=10) as t:
        t["g"] = {"o": ["b", "c"]}
    assert t.rev.all("g", "o") == ["b", "c"]
    with pytest.raises(TypeError):
        with L.transaction(by="t") as t:
            t["g*", "x"] = "y"


# -- db/type (Q35, A36) ---------------------------------------------------------------------------

def test_db_type_checked_at_commit_and_on_strict_reads(L):
    write(L, ("g", "score", {"h": 1}))
    write(L, ("db/pred/score", "db/type", "str"))
    top = L.at().id
    with pytest.raises(TypeError):
        write(L, ("g2", "score", {"h": 2}))
    assert L.at().id == top
    rev = L.at()
    with pytest.raises(TypeError):
        rev["g", "score"]
    assert rev.all("g", "score") == [{"h": 1}] and rev["g"]["score"] == {"h": 1}
    with pytest.raises(TypeError):        # same-transaction declaration counts
        write(L, ("db/pred/n", "db/type", "json"), ("g", "n", "text"))


# -- bump (Q33, A38, DAT 1043) -------------------------------------------------------------------------

def test_bump_patch_minor_confirm_and_backwards_add(L):
    with L.transaction(by="t", lock=10) as t:
        assert bump(t, "schema") == "0.0.1"
    with pytest.raises(ValueError):
        with L.transaction(by="t", lock=10) as t:
            bump(t, "schema", "minor")
    with L.transaction(by="t", lock=10) as t:
        assert bump(t, "schema", "minor", confirm=lambda a, b: True) == "0.1.0"
    write(L, ("schema", "version", "0.0.9"))
    assert L.at()["schema", "version"] == "0.0.9"


def test_bump_refuses_a_code_subject(L):
    with pytest.raises(TypeError, match="a code version lives in its source"):
        with L.transaction(by="t", lock=10) as t:
            bump(t, "db/repo/testrepo/ledger_kinds")
    assert L.at().get("db/repo/testrepo/ledger_kinds", "version") is None


# -- previous_rev and the lock (DAT 1039) --------------------------------------------------------

def test_previous_rev_unlocked_raises_unlocked(L):
    with L.transaction(by="t") as t:
        with pytest.raises(Unlocked, match="the transaction is not locked: previous_rev is the top only under lock="):
            t.previous_rev
        t.add("g", "home", "a")
    assert L.at()["g", "home"] == "a"


def test_previous_rev_before_enter_is_a_runtime_error(L):
    t = L.transaction(by="t", lock=10)
    with pytest.raises(RuntimeError, match="previous_rev"):
        t.previous_rev


def test_unlocked_bump_raises_unlocked_and_writes_nothing(L):
    write(L, ("schema", "version", "0.0.1"))
    top = L.at().id
    with pytest.raises(Unlocked):
        with L.transaction(by="t") as t:
            bump(t, "schema")
    assert L.at().id == top and L.at()["schema", "version"] == "0.0.1"


def test_unlocked_record_write_and_del_raise_unlocked(L):
    write(L, ("g", "home", "a"))
    top = L.at().id
    with pytest.raises(Unlocked):
        with L.transaction(by="t") as t:
            t["g"] = {"home": "b"}
    with pytest.raises(Unlocked):
        with L.transaction(by="t") as t:
            del t["g", "home"]
    with pytest.raises(Unlocked):
        with L.transaction(by="t") as t:
            del t["g"]
    assert L.at().id == top and L.at()["g", "home"] == "a"


def test_unlocked_pair_write_and_add_still_commit(L):
    with L.transaction(by="t") as t:
        t["g", "home"] = "a"
        t.add("g", "away", "b")
    assert L.at()["g"] == {"home": "a", "away": "b"}


def test_locked_previous_rev_is_the_top_and_the_helpers_work(L):
    write(L, ("g", "home", "a"), ("schema", "version", "0.0.1"))
    before = L.at()
    with L.transaction(by="t", lock=10) as t:
        assert t.previous_rev.id == before.id
        assert t.previous_rev["g"] == before["g"]
        assert bump(t, "schema") == "0.0.2"
        t["g"] = {**t.previous_rev["g"], "away": "b"}
    assert L.at()["g"] == {"home": "a", "away": "b"} and L.at()["schema", "version"] == "0.0.2"


def test_close_closes_every_thread_reader_and_a_later_read_reopens(L):
    import threading

    with L.transaction(by="t") as t:
        t.add("game/G1", "home", "A")
    seen = []
    th = [threading.Thread(target=lambda: seen.append(L.at().get("game/G1", "home"))) for _ in range(3)]
    for x in th:
        x.start()
    for x in th:
        x.join()
    assert seen == ["A"] * 3
    readers = list(L._store._readers)
    assert len(readers) == 4
    with L:
        assert L.at().get("game/G1", "home") == "A"
    assert L._store._readers == []
    for c in readers:
        with pytest.raises(Exception):
            c.execute("SELECT 1")
    assert L.at().get("game/G1", "home") == "A"
    with L.transaction(by="t") as t:
        t.add("game/G1", "away", "B")
    assert L.at().get("game/G1", "away") == "B"
    L.close()
