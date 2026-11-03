"""SVP 1500: ``expand`` is a ``Namespace`` method; the ledger namespace counts ``{unique}``; a ledger's zone.

``ns.expand``, ``manager.ns.expand`` and ``rev.ns.expand`` each resolve through their own names; on a ledger
namespace ``{unique}`` counts against the revision (a whole segment ``1, 2, 3``, a suffix ``"", _2, _3``), and
the clock built-ins and the machine stamps are in the ledger's zone, fixed at creation (``tz=``, UTC default).
"""

import dataclasses
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from dvc_dat import Namespace
from dvc_dat.ledger import Checkout, Ledger, LedgerError

from ledger_kinds import Video


def test_rev_ns_expands_through_the_ledgers_mounts_and_the_plain_ns_does_not(L, envbox, tmp_path):
    tree = tmp_path / "proj" / "cfgs"
    tree.mkdir(parents=True)
    (tree / "names.yaml").write_text("word: mine\n")
    envbox.set(code={**envbox.env.code, "myrepo": Checkout(None, "abc1234", False, tmp_path / "proj")})
    with L.transaction(by="t") as t:
        t.ns.mount("mnt.cfg", root="cfgs", repo="myrepo")
    assert L.at().ns.expand("runs/{mnt.cfg.names.word}/x") == "runs/mine/x"
    with L.transaction(by="t", lock=10) as t:
        assert t.ns.expand("{mnt.cfg.names.word}") == "mine"
    with pytest.raises(ImportError):
        Namespace().expand("{mnt.cfg.names.word}")
    with pytest.raises(TypeError, match="string or a number"):
        L.at().ns.expand("{mnt.cfg.names}")                  # a dict: expand_spec's to inline, never expand's
    assert L.at().ns.expand_spec({"c": "{mnt.cfg.names}"}) == {"c": {"word": "mine"}}


def test_a_whole_segment_counts_from_one_and_a_suffix_from_empty(L):
    ns = L.at().ns
    assert ns.expand("events/{unique}") == "events/1"
    assert ns.expand("baseline{unique}") == "baseline"
    assert ns.expand("{unique}/x") == "1/x"
    assert ns.expand("a{{unique}}") == "a{unique}"           # the literal: nothing counted
    assert ns.expand("events/{unique}", unique="_7") == "events/_7"     # a keyword is used as given


def test_a_name_holding_a_value_or_a_folder_blocks_it(L):
    with L.transaction(by="t") as t:
        Video(b"one").seal(t, name="events/1")
        Video(b"two").seal(t, name="baseline")
    assert L.at().ns.expand("events/{unique}") == "events/2"
    assert L.at().ns.expand("baseline{unique}") == "baseline_2"
    (L._store.art.root / "dats" / "events" / "2").mkdir(parents=True)
    assert L.at().ns.expand("events/{unique}") == "events/3"
    assert L.at().ns.expand("/abs/{unique}") == "/abs/1"     # absolute: names nothing, not probed


def test_two_mints_in_one_transaction_differ(L):
    with L.transaction(by="t") as t:
        names = [t.ns.expand("ann/{g}/{kind}/{unique}", g="G7", kind="events") for _ in range(3)]
    assert names == ["ann/G7/events/1", "ann/G7/events/2", "ann/G7/events/3"]
    with L.transaction(by="t") as t:
        name = t.ns.expand("ann/{unique}")
        Video(b"v").seal(t, name=name)
        assert t.ns.expand("ann/{unique}") == "ann/2"          # pending as this transaction's alias
    assert L.at()["ann/1", "db/alias"]


def test_the_clock_is_in_the_ledgers_zone(tmp_path, monkeypatch):
    moment = datetime(2026, 11, 1, 20, 30, tzinfo=timezone.utc)   # 2026-11-02 05:30 in Tokyo

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz is not None else moment.astimezone().replace(tzinfo=None)

    import dvc_dat.core as core
    import dvc_dat.ledger.namespace as lns
    monkeypatch.setattr(core, "datetime", Fixed)
    monkeypatch.setattr(lns, "datetime", Fixed)
    tokyo = Ledger(tmp_path / "tokyo", create=True, tz="Asia/Tokyo")
    utc = Ledger(tmp_path / "utc", create=True)
    assert tokyo.at().ns.expand("{YYYY}-{MM}-{DD}") == "2026-11-02"
    assert utc.at().ns.expand("{YYYY}-{MM}-{DD}") == "2026-11-01"
    assert tokyo.at().ns.expand("d/{DD}/{unique}") == "d/02/1"


def test_a_ledgers_zone_is_fixed_at_creation_and_stamps_carry_its_offset(tmp_path):
    tokyo = Ledger(tmp_path / "tokyo", create=True, tz="Asia/Tokyo")
    assert tokyo.tz == ZoneInfo("Asia/Tokyo") and tokyo.at()["db", "db/tz"] == "Asia/Tokyo"
    with tokyo.transaction(by="t") as t:
        t.add("s", "p", "o")
    assert t.rev[t.rev.tx, "db/time"].endswith("+09:00")
    with tokyo.transaction(by="t") as t:
        v = Video(b"x")
        v.seal(t)
    assert v.sealed.endswith("+09:00")
    assert Ledger(tmp_path / "tokyo").tz == ZoneInfo("Asia/Tokyo")          # read back at open
    with tokyo.transaction(by="t") as t:
        with pytest.raises(ValueError, match="never changes"):
            t.add("db", "db/tz", "UTC")
        with pytest.raises(ValueError, match="never removed"):
            t.remove("db", "db/tz", "Asia/Tokyo")
    with pytest.raises(LedgerError, match="fixed when it was created"):
        Ledger(tmp_path / "tokyo", create=True, tz="UTC")
    assert Ledger(tmp_path / "tokyo", create=True, tz="Asia/Tokyo").tz.key == "Asia/Tokyo"

    utc = Ledger(tmp_path / "utc", create=True)
    assert utc.tz == ZoneInfo("UTC") and utc.at().id == 0                  # no tz: no row, no revision
    with utc.transaction(by="t") as t:
        t.add("s", "p", "o")
    assert t.rev[t.rev.tx, "db/time"].endswith("+00:00")


def test_tz_is_an_iana_name_given_at_create(tmp_path):
    with pytest.raises(ValueError, match="IANA"):
        Ledger(tmp_path / "bad", create=True, tz="Mars/Olympus")
    with pytest.raises(TypeError, match="create=True"):
        Ledger(tmp_path / "bad", tz="UTC")


def test_a_ledgers_entry_names_its_zone(tmp_path, monkeypatch):
    (tmp_path / ".datconfig.yaml").write_text(
        "ledgers:\n  default: games\n  games: {location: .dat/games, tz: America/Los_Angeles}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    assert Ledger(create=True).tz.key == "America/Los_Angeles"
    assert Ledger().tz.key == "America/Los_Angeles"
    (tmp_path / ".datconfig.yaml").write_text("ledgers:\n  default: games\n  games: {at: x}\n")
    with pytest.raises(LedgerError, match="location and tz"):
        Ledger()
