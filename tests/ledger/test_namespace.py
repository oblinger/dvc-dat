"""SVP 1500: ``expand`` is a ``Namespace`` method; the ledger namespace counts ``{unique}``. SVP 1505 Q2: the display zone.

``ns.expand``, ``manager.ns.expand`` and ``rev.ns.expand`` each resolve through their own names; on a ledger
namespace ``{unique}`` counts against the revision (a whole segment ``1, 2, 3``, a suffix ``"", _2, _3``), and
stamps are stored UTC, and the clock built-ins and printed times are in the revision's display zone, the row
``db db/timezone`` (UTC with none), which any revision may change.
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


def _tokyo(L):
    with L.transaction(by="t") as t:
        t.add("db", "db/timezone", "Asia/Tokyo")
    return t.rev


def test_the_clock_is_in_the_revisions_display_zone(L, monkeypatch):
    moment = datetime(2026, 11, 1, 20, 30, tzinfo=timezone.utc)   # 2026-11-02 05:30 in Tokyo

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz is not None else moment.astimezone().replace(tzinfo=None)

    import dvc_dat.core as core
    import dvc_dat.ledger.namespace as lns
    monkeypatch.setattr(core, "datetime", Fixed)
    monkeypatch.setattr(lns, "datetime", Fixed)
    utc = L.at()
    tokyo = _tokyo(L)
    assert utc.ns.expand("{YYYY}-{MM}-{DD}") == "2026-11-01"
    assert tokyo.ns.expand("{YYYY}-{MM}-{DD}") == "2026-11-02"
    assert tokyo.ns.expand("d/{DD}/{unique}") == "d/02/1"
    with L.transaction(by="t", lock=10) as t:
        assert t.ns.expand("{DD}") == "02"


def test_stamps_are_stored_utc_and_print_in_the_display_zone(L):
    assert L.at().timezone == ZoneInfo("UTC")                          # no row: UTC
    tokyo = _tokyo(L)
    assert tokyo.timezone == ZoneInfo("Asia/Tokyo") and tokyo["db", "db/timezone"] == "Asia/Tokyo"
    with L.transaction(by="t") as t:
        v = Video(b"x")
        v.seal(t)
    stored = t.rev[t.rev.tx, "db/time"]
    assert stored.endswith("Z") and v.sealed.endswith("Z")              # storage never moves
    shown = t.rev.show_time(stored)
    assert shown.endswith("+09:00")
    assert datetime.fromisoformat(shown) == datetime.fromisoformat(stored)
    row = next(r for r in t.rev.history() if r.subject == t.rev.tx and r.predicate == "db/time")
    assert f"db/time {shown} rev=" in repr(row)
    assert L.at(0).show_time(stored) == stored                          # before the row: UTC, unchanged


def test_the_display_zone_changes_at_any_revision_and_only_how_times_print(L):
    tokyo = _tokyo(L)
    with L.transaction(by="t") as t:
        t.add("db", "db/timezone", "America/Los_Angeles")
    la = t.rev
    with L.transaction(by="t") as t:
        t.remove("db", "db/timezone", "America/Los_Angeles")
    back = t.rev
    stamp = la[la.tx, "db/time"]
    assert tokyo.timezone.key == "Asia/Tokyo" and la.timezone.key == "America/Los_Angeles"
    assert back.timezone.key == "UTC" and back.show_time(stamp) == stamp
    assert la.show_time(stamp)[-6:] in ("-07:00", "-08:00")
    assert tokyo.show_time(stamp).endswith("+09:00")


def test_the_display_zone_is_validated_when_it_is_asserted(L):
    with L.transaction(by="t") as t:
        with pytest.raises(ValueError, match="IANA"):
            t.add("db", "db/timezone", "Mars/Olympus")
        with pytest.raises(ValueError, match="subject db"):
            t.add("game/G1", "db/timezone", "UTC")
        t.add("s", "p", "o")
    assert L.at().timezone.key == "UTC"


def test_a_ledger_takes_no_zone_and_an_entry_is_a_location(tmp_path, monkeypatch):
    with pytest.raises(TypeError):
        Ledger(tmp_path / "x", create=True, tz="UTC")
    assert not hasattr(Ledger(tmp_path / "y", create=True), "tz")
    (tmp_path / ".datconfig.yaml").write_text(
        "root: {location: .dat/games, tz: America/Los_Angeles}\ndefault: root\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    with pytest.raises(LedgerError, match="a folder or a DSN"):
        Ledger()
