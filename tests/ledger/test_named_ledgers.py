"""Many ledgers (SVP 239 Q1 B): the `ledgers:` section, the named handles `ledgers.<name>`, and `L`, the active ledger."""

import pytest

from dvc_dat import DatManager, L, ledgers
from dvc_dat.ledger import Ledger, LedgerError


def project(tmp, config, override=None, make=("games", "record", "exp-jb-26", "exp-do-26")):
    """A project folder: `.datconfig.yaml`, optionally `.datconfig.override.yaml`, and a SQLite ledger per name."""
    (tmp / ".datconfig.yaml").write_text(config)
    if override is not None:
        (tmp / ".datconfig.override.yaml").write_text(override)
    for name in make:
        Ledger(tmp / "led" / name, create=True)
    return tmp


SECTION = ("ledgers:\n  games: led/games\n  record: led/record\n"
           "  exp-jb-26: led/exp-jb-26\n  exp-do-26: led/exp-do-26\n")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_two_named_ledgers_are_distinct_stores(here):
    project(here, SECTION)
    assert ledgers.games.path == (here / "led" / "games").resolve()
    assert ledgers.record.path == (here / "led" / "record").resolve()
    with ledgers.games.transaction(by="t") as t:
        t.add("game/G1", "home", "G4")
    assert ledgers.games.at()["game/G1", "home"] == "G4"
    assert ledgers.record.at().get("game/G1", "home") is None
    assert ledgers.games is ledgers["games"]                    # one handle per ledger
    assert isinstance(ledgers.games, Ledger)
    assert list(ledgers) == ["games", "record", "exp-jb-26", "exp-do-26"]
    assert "record" in ledgers and "nope" not in ledgers


def test_hyphenated_names_take_the_item_form(here):
    project(here, SECTION)
    assert ledgers["exp-jb-26"].path == (here / "led" / "exp-jb-26").resolve()
    with pytest.raises(AttributeError, match=r"ledgers\['exp-jb-26'\]"):
        ledgers.exp_jb_26
    with pytest.raises(KeyError, match="nope"):
        ledgers["nope"]
    with pytest.raises(AttributeError, match="nope"):
        ledgers.nope


def test_L_from_the_env_naming_an_entry(here, monkeypatch):
    project(here, SECTION)
    monkeypatch.setenv("DAT_LEDGER", "exp-do-26")
    assert L.path == (here / "led" / "exp-do-26").resolve()
    assert isinstance(L, Ledger)
    with L.transaction(by="t") as t:
        t.add("s", "p", "o")
    assert ledgers["exp-do-26"].at()["s", "p"] == "o"
    assert L.at().ledger is ledgers["exp-do-26"]                 # one handle per ledger, L's and the name's
    assert Ledger().path == L.path                               # Ledger() is the active ledger too


def test_L_from_the_env_as_a_location_still(here, monkeypatch):
    project(here, SECTION)
    other = Ledger(here / "elsewhere", create=True)
    monkeypatch.setenv("DAT_LEDGER", str(here / "elsewhere"))
    assert L.path == other.path


def test_L_from_the_override_file(here):
    project(here, SECTION, override="ledgers:\n  default: exp-jb-26\n")
    assert L.path == (here / "led" / "exp-jb-26").resolve()
    assert Ledger().path == L.path


def test_the_override_default_wins_over_the_committed_one(here):
    project(here, SECTION + "  default: record\n", override="ledgers:\n  default: exp-jb-26\n")
    assert L.path == (here / "led" / "exp-jb-26").resolve()
    (here / ".datconfig.override.yaml").unlink()
    assert L.path == (here / "led" / "record").resolve()        # the committed default, when present


def test_no_default_is_refused_with_the_one_line_fix(here):
    project(here, SECTION)
    import dvc_dat                                                # importing L never resolves it
    assert dvc_dat.L is L
    with pytest.raises(LedgerError) as e:
        L.at()
    msg = str(e.value)
    assert "\n" not in msg and "DAT_LEDGER" in msg and ".datconfig.override.yaml" in msg and "default" in msg
    with pytest.raises(LedgerError, match="DAT_LEDGER"):
        Ledger()
    assert "unresolved" in repr(L)


def test_the_single_ledger_key_is_unchanged(here):
    (here / ".datconfig.yaml").write_text("ledger: .dat/ledger\n")
    Ledger(here / ".dat" / "ledger", create=True)
    assert Ledger().path == (here / ".dat" / "ledger").resolve()
    assert L.path == Ledger().path
    with pytest.raises(LedgerError, match="ledgers:"):
        ledgers.games


def test_ledger_and_ledgers_together_are_refused(here):
    project(here, "ledger: led/games\n" + SECTION + "  default: games\n")
    with pytest.raises(LedgerError, match="both"):
        Ledger()
    with pytest.raises(LedgerError, match="both"):
        ledgers.games


def test_bad_sections_are_refused(here):
    project(here, "ledgers:\n  Games: led/games\n", make=())
    with pytest.raises(LedgerError, match="lowercase"):
        ledgers.games
    project(here, "ledgers:\n  games: led/games\n  default: record\n", make=())
    with pytest.raises(LedgerError, match="record"):
        L.at()
    project(here, "ledgers:\n  games: ''\n", make=())
    with pytest.raises(LedgerError, match="games"):
        ledgers.games
    project(here, "ledgers: [games]\n", make=())
    with pytest.raises(LedgerError, match="mapping"):
        ledgers.games


def test_create_in_a_ledgers_project_makes_the_active_one(here):
    (here / ".datconfig.yaml").write_text("ledgers:\n  scratch: led/scratch\n")
    (here / ".datconfig.override.yaml").write_text("ledgers:\n  default: scratch\n")
    made = Ledger(create=True)
    assert made.path == (here / "led" / "scratch").resolve()
    assert (here / ".datconfig.yaml").read_text() == "ledgers:\n  scratch: led/scratch\n"   # no ledger: added


def test_a_dsn_entry_is_passed_through(here):
    from dvc_dat.ledger.ledger import _entries

    dsn = "postgresql://u@h:5432/exp_jb_26?art=art/exp-jb-26"
    (here / ".datconfig.yaml").write_text(f"ledgers:\n  exp-jb-26: '{dsn}'\n")
    assert _entries(here / ".datconfig.yaml")["exp-jb-26"] == dsn


def test_a_ledgers_section_keeps_the_plain_namespace(here):
    """SVP 239 A2: the section names ledgers; it does not make the project's names the ledger's."""
    project(here, SECTION, override="ledgers:\n  default: games\n")
    m = DatManager.load_dat_config(here)
    assert type(m.ns).__name__ == "Namespace"
    m.ns.mount(value={"k": 1}, at="cfg")                     # a ledger namespace refuses this
    assert m.ns.load("cfg.k") == 1
    assert L.path == (here / "led" / "games").resolve()       # the section still names the active ledger


def test_the_one_ledger_key_still_gives_the_ledger_namespace(here):
    (here / ".datconfig.yaml").write_text("ledger: .dat/ledger\n")
    Ledger(here / ".dat" / "ledger", create=True)
    m = DatManager.load_dat_config(here)
    assert type(m.ns).__name__ == "LedgerNamespace"
    with pytest.raises(TypeError, match="db/mount"):
        m.ns.mount(value={"k": 1}, at="cfg")


def test_namespace_ledger_with_a_section_gives_the_ledger_namespace(here):
    project(here, SECTION + "namespace: ledger\n", override="ledgers:\n  default: games\n")
    m = DatManager.load_dat_config(here)
    assert type(m.ns).__name__ == "LedgerNamespace"
    with pytest.raises(TypeError, match="db/mount"):
        m.ns.mount(value={"k": 1}, at="cfg")


def test_namespace_key_is_checked(here):
    (here / ".datconfig.yaml").write_text("namespace: files\n")
    with pytest.raises(ValueError, match="namespace"):
        DatManager.load_dat_config(here)
    (here / ".datconfig.yaml").write_text("namespace: ledger\n")
    with pytest.raises(ValueError, match="names a ledger"):
        DatManager.load_dat_config(here)


def test_the_active_ledger_asserts_the_mounts(here):
    project(here, SECTION + "  default: games\nmounts:\n  pkg.etl: pkg/etl\n")
    assert L.at()["db/mount/pkg.etl"]["db/root"] == "pkg/etl"
    assert ledgers.record.at().get("db/mount/pkg.etl", "db/root") is None     # a named handle asserts nothing


_RAN = []


def test_x_in_a_ledgers_project_is_the_bare_run(here, monkeypatch):
    """`x TARGET` goes through the ledger only when the project's names are the ledger's."""
    from dvc_dat import core
    from dvc_dat.do import _cmd_do

    project(here, SECTION, override="ledgers:\n  default: games\n")
    m = DatManager.load_dat_config(here)
    monkeypatch.setattr(core, "_default_manager", m)
    m.ns.mount(at="fn_x", value=lambda *a, **k: _RAN.append(k))
    assert _cmd_do(["fn_x", "k=1"], config=here) == 0
    assert _RAN[-1] == {"k": 1}
    assert ledgers.games.at().get("db", "db/version") is None       # nothing sealed in the active ledger
