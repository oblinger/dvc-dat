"""Root, the one list (SVP 239): `root:` in the one `.datconfig.yaml`, the registry on root as the list of ledgers,
`ledgers` a mutable mapping filled lazily from it, and `L`, the active ledger (`DAT_LEDGER` over `default:`)."""

import pytest

from dvc_dat import DatManager, L, ledgers
from dvc_dat.ledger import Ledger, LedgerError
from dvc_dat.ledger import named


def register(root, **where):
    """Rows of root's registry: `ledger/<name> ledger/location <where>`."""
    with root.transaction(by="t") as t:
        for name, loc in where.items():
            t.add(f"ledger/{name}", "ledger/location", str(loc))


def project(tmp, config="root: led/root\n", make=("games", "record", "do26", "prod_run26")):
    """A project: `.datconfig.yaml`, its root at `led/root` registering a SQLite ledger per name in `led/`."""
    (tmp / ".datconfig.yaml").write_text(config)
    root = Ledger(tmp / "led" / "root", create=True)
    for name in make:
        Ledger(tmp / "led" / name, create=True)
    register(root, **{name: f"led/{name}" for name in make})
    return root


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    monkeypatch.delenv("DAT_FOLDERS", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_two_registered_ledgers_are_distinct_stores(here):
    project(here)
    assert ledgers.games.path == (here / "led" / "games").resolve()
    assert ledgers.record.path == (here / "led" / "record").resolve()
    with ledgers.games.transaction(by="t") as t:
        t.add("game/G1", "home", "G4")
    assert ledgers.games.at()["game/G1", "home"] == "G4"
    assert ledgers.record.at().get("game/G1", "home") is None
    assert ledgers.games is ledgers["games"]                    # one handle per ledger
    assert isinstance(ledgers.games, Ledger)
    assert list(ledgers) == ["root", "games", "record", "do26", "prod_run26"]
    assert len(ledgers) == 5
    assert "record" in ledgers and "nope" not in ledgers
    assert ledgers.root.path == (here / "led" / "root").resolve()


def test_an_unknown_name_is_a_key_error_naming_the_registry(here):
    project(here)
    with pytest.raises(KeyError, match="registry"):
        ledgers["nope"]
    with pytest.raises(AttributeError, match="registry"):
        ledgers.nope
    assert sorted(dir(ledgers)) == ["do26", "games", "prod_run26", "record", "root"]


def test_root_is_read_once_per_process_and_not_before_a_name(here, monkeypatch):
    root = project(here)
    reads = []
    real = named._View.fill

    def counted(view):
        if not view.filled:
            reads.append(view.cfg)
        real(view)

    monkeypatch.setattr(named._View, "fill", counted)
    import dvc_dat                                              # importing never reads root
    assert dvc_dat.ledgers is ledgers and reads == []
    ledgers.games, ledgers.record, list(ledgers), len(ledgers), "do26" in ledgers
    assert len(reads) == 1
    register(root, late=here / "led" / "games")                  # registered after the read: not seen this process
    assert "late" not in ledgers and len(reads) == 1


def test_a_dropped_ledger_resolves_no_more(here):
    root = project(here)
    with root.transaction(by="t") as t:
        t.add("ledger/do26", "ledger/dropped", "2026-11-05")
    assert "do26" not in ledgers and "games" in ledgers


def test_a_registered_dsn_is_passed_through(here):
    dsn = "postgresql://u@h:5432/prod_run26?art=art/prod_run26"
    root = project(here, make=())
    register(root, prod_run26=dsn)
    assert named.view_of(here / ".datconfig.yaml").get("prod_run26") == dsn


# -- the mapping is mutable, for this process --------------------------------------------------------------------

def test_del_drops_a_name_for_this_process_only(here):
    project(here)
    held = ledgers.prod_run26
    del ledgers["prod_run26"]
    assert "prod_run26" not in ledgers and len(ledgers) == 4
    with pytest.raises(KeyError, match="dropped"):
        ledgers["prod_run26"]
    with pytest.raises(AttributeError):
        ledgers.prod_run26
    assert held.at().id >= 0                                    # a handle already in hand keeps working
    with pytest.raises(KeyError):
        del ledgers["prod_run26"]
    assert ledgers.root.at().get("ledger/prod_run26", "ledger/location") == "led/prod_run26"  # registry untouched


def test_setitem_puts_a_ledger_in_by_hand(here):
    project(here)
    tmp = Ledger(here / "scratch", create=True)
    ledgers["tmp"] = tmp
    assert ledgers.tmp is tmp and ledgers["tmp"] is tmp
    assert list(ledgers)[-1] == "tmp" and len(ledgers) == 6
    del ledgers["games"]
    ledgers["games"] = tmp                                       # a dropped name set again
    assert ledgers.games is tmp
    with pytest.raises(TypeError, match="Ledger"):
        ledgers["x"] = str(here / "scratch")
    with pytest.raises(ValueError, match="identifier"):
        ledgers["not-a-name"] = tmp
    assert ledgers.root.at().get("ledger/tmp", "ledger/location") is None  # never the registry


def test_setting_root_before_the_first_read_is_a_temp_root(here):
    """How a test runs on a temp root: the configured one is never opened."""
    (here / ".datconfig.yaml").write_text("root: postgresql://nobody@127.0.0.1:1/never\n")
    temp = Ledger(here / "temp_root", create=True)
    register(temp, games=here / "led" / "games")
    Ledger(here / "led" / "games", create=True)
    ledgers["root"] = temp
    assert ledgers.games.path == (here / "led" / "games").resolve()
    assert ledgers.root is temp


# -- root: and its default -----------------------------------------------------------------------------------------

def test_no_root_key_is_a_sqlite_root_under_the_dat_folder_made_on_first_use(here):
    (here / ".datconfig.yaml").write_text("dat_folders: dats\n")
    made = here / "dats" / ".ledgers" / "root"
    DatManager.load_dat_config(here)
    assert not made.exists()                                    # a dat-only user never meets a ledger
    assert list(ledgers) == ["root"]
    assert ledgers.root.path == made.resolve() and (made / "ledger.db").is_file()
    assert ledgers.root._store.name == "root"


def test_the_default_root_follows_DAT_FOLDERS(here, monkeypatch):
    (here / ".datconfig.yaml").write_text("dat_folders: dats\n")
    monkeypatch.setenv("DAT_FOLDERS", str(here / "elsewhere"))
    assert ledgers.root.path == (here / "elsewhere" / ".ledgers" / "root").resolve()


def test_a_named_root_is_never_made(here):
    (here / ".datconfig.yaml").write_text("root: led/root\n")
    with pytest.raises(LedgerError, match="no ledger at"):
        ledgers.games
    assert not (here / "led" / "root").exists()


def test_root_key_is_checked(here):
    (here / ".datconfig.yaml").write_text("root: ''\n")
    with pytest.raises(LedgerError, match="root: is a folder or a DSN"):
        ledgers.games


# -- the removed keys and the override file -------------------------------------------------------------------------

@pytest.mark.parametrize("text, says", [("ledger: .dat/ledger\n", "'root: .dat/ledger' and 'default: root'"),
                                        ("ledgers:\n  games: led/games\n", "registry on the root ledger")])
def test_a_removed_key_names_its_replacement(here, text, says):
    (here / ".datconfig.yaml").write_text(text)
    for use in (lambda: ledgers.games, lambda: L.at(), Ledger):
        with pytest.raises(LedgerError, match=says.replace("(", r"\(")):
            use()


def test_an_override_file_is_refused(here):
    project(here)
    (here / ".datconfig.override.yaml").write_text("default: games\n")
    with pytest.raises(LedgerError, match="override file is no longer read"):
        L.at()
    with pytest.raises(LedgerError, match="override file is no longer read"):
        ledgers.games


# -- L: DAT_LEDGER over default: ----------------------------------------------------------------------------------------

def test_L_from_the_env_naming_a_registered_ledger(here, monkeypatch):
    project(here)
    monkeypatch.setenv("DAT_LEDGER", "do26")
    assert L.path == (here / "led" / "do26").resolve()
    assert isinstance(L, Ledger)
    with L.transaction(by="t") as t:
        t.add("s", "p", "o")
    assert ledgers["do26"].at()["s", "p"] == "o"
    assert L.at().ledger is ledgers["do26"]                    # one handle per ledger, L's and the name's
    assert Ledger().path == L.path                             # Ledger() is the active ledger too


def test_L_from_the_env_as_a_location(here, monkeypatch):
    project(here)
    other = Ledger(here / "elsewhere", create=True)
    monkeypatch.setenv("DAT_LEDGER", str(here / "elsewhere"))
    assert L.path == other.path


def test_DAT_LEDGER_wins_over_the_committed_default(here, monkeypatch):
    project(here, "root: led/root\ndefault: record\n")
    assert L.path == (here / "led" / "record").resolve()        # the committed default, alone
    monkeypatch.setenv("DAT_LEDGER", "prod_run26")
    assert L.path == (here / "led" / "prod_run26").resolve()
    assert Ledger().path == L.path


def test_default_root_and_a_default_location(here):
    project(here, "root: led/root\ndefault: root\n")
    assert L.path == (here / "led" / "root").resolve()
    (here / ".datconfig.yaml").write_text("root: led/root\ndefault: led/games\n")
    assert L.path == (here / "led" / "games").resolve()


def test_an_unregistered_name_in_DAT_LEDGER_is_refused(here, monkeypatch):
    project(here)
    monkeypatch.setenv("DAT_LEDGER", "nope")
    with pytest.raises(LedgerError, match="DAT_LEDGER=nope.*registry"):
        L.at()


def test_no_active_ledger_is_refused_with_the_one_line_fix(here):
    project(here)
    import dvc_dat                                              # importing L never resolves it
    assert dvc_dat.L is L
    with pytest.raises(LedgerError) as e:
        L.at()
    msg = str(e.value)
    assert "\n" not in msg and "DAT_LEDGER" in msg and "default:" in msg
    with pytest.raises(LedgerError, match="DAT_LEDGER"):
        Ledger()
    assert "unresolved" in repr(L)


def test_a_deleted_name_cannot_be_made_active(here, monkeypatch):
    project(here)
    del ledgers["prod_run26"]
    monkeypatch.setenv("DAT_LEDGER", "prod_run26")
    with pytest.raises(LedgerError, match="dropped"):
        L.at()


def test_create_writes_default_root_and_makes_the_root(here):
    made = Ledger(create=True)
    assert (here / ".datconfig.yaml").read_text() == "default: root\nnamespace: ledger\n"
    assert made.path == (here / "data" / ".ledgers" / "root").resolve()
    assert L.path == made.path


def test_create_makes_a_named_root(here):
    (here / ".datconfig.yaml").write_text("root: elsewhere\n")
    made = Ledger(create=True)
    assert made.path == (here / "elsewhere").resolve()
    assert (here / ".datconfig.yaml").read_text() == "root: elsewhere\ndefault: root\nnamespace: ledger\n"


def test_create_makes_the_registered_default(here):
    root = project(here, "root: led/root\ndefault: scratch\n", make=())
    register(root, scratch="led/scratch")
    made = Ledger(create=True)
    assert made.path == (here / "led" / "scratch").resolve()
    assert (here / ".datconfig.yaml").read_text() == "root: led/root\ndefault: scratch\n"


def test_the_active_ledger_asserts_the_mounts(here):
    project(here, "root: led/root\ndefault: games\nmounts:\n  mnt.pkg.etl: pkg/etl\n")
    assert L.at()["db/mount/pkg.etl"]["db/root"] == "pkg/etl"
    assert ledgers.record.at().get("db/mount/pkg.etl", "db/root") is None     # a named handle asserts nothing


# -- namespace: ledger, the one switch ------------------------------------------------------------------------------

def test_root_and_default_keep_the_plain_namespace(here):
    project(here, "root: led/root\ndefault: games\n")
    m = DatManager.load_dat_config(here)
    assert type(m.ns).__name__ == "Namespace"
    m.ns.mount(value={"k": 1}, at="cfg")                     # a ledger namespace refuses this
    assert m.ns.load("cfg.k") == 1
    assert L.path == (here / "led" / "games").resolve()


def test_namespace_ledger_gives_the_ledger_namespace(here):
    project(here, "root: led/root\ndefault: games\nnamespace: ledger\n")
    m = DatManager.load_dat_config(here)
    assert type(m.ns).__name__ == "LedgerNamespace"
    with pytest.raises(TypeError, match="db/mount"):
        m.ns.mount(value={"k": 1}, at="cfg")


def test_namespace_key_is_checked(here):
    (here / ".datconfig.yaml").write_text("namespace: files\n")
    with pytest.raises(ValueError, match="namespace"):
        DatManager.load_dat_config(here)


_RAN = []


def test_x_without_namespace_ledger_is_the_bare_run(here, monkeypatch):
    """`x TARGET` goes through the ledger only when the project's names are the ledger's."""
    from dvc_dat import core
    from dvc_dat.do import _cmd_do

    project(here, "root: led/root\ndefault: games\n")
    m = DatManager.load_dat_config(here)
    monkeypatch.setattr(core, "_default_manager", m)
    m.ns.mount(at="fn_x", value=lambda *a, **k: _RAN.append(k))
    assert _cmd_do(["fn_x", "k=1"], config=here) == 0
    assert _RAN[-1] == {"k": 1}
    assert ledgers.games.at().get("db", "db/version") is None       # nothing sealed in the active ledger


# -- two registered ledgers on one Postgres server, each its own database (SVP 239 § How it will be verified) ----------

def test_two_registered_postgres_ledgers_are_separate_databases(here):
    import uuid
    from urllib.parse import urlsplit, urlunsplit

    import backends

    backends.database()                                         # skips with no server (DVC_DAT_TEST_PG)
    parts = urlsplit(backends.SERVER)
    names = [f"dvcdat_reg_{uuid.uuid4().hex[:8]}_{n}" for n in ("games", "do26")]
    with backends._admin() as c:
        for n in names:
            c.execute(f'CREATE DATABASE "{n}"')
    try:
        dsns = {n: urlunsplit((parts.scheme, parts.netloc, "/" + n, f"art={here / n / 'art'}", "")) for n in names}
        for dsn in dsns.values():
            Ledger(dsn, create=True)
        root = project(here, make=())
        register(root, games=dsns[names[0]], do26=dsns[names[1]])
        with ledgers.games.transaction(by="t") as t:
            t.add("game/G1", "home", "G4")
        assert ledgers.games.at()["game/G1", "home"] == "G4"
        assert ledgers.do26.at().get("game/G1", "home") is None
        assert (ledgers.games._store.name, ledgers.do26._store.name) == tuple(names)
    finally:
        for led in list(named._handles.values()):
            led.close()
        with backends._admin() as c:
            for n in names:
                c.execute(f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)')
