"""``L.at(timestamp)`` (SVP 1507): an ISO 8601 prefix at any precision names the latest revision whose
``db/time`` is at or before the start of its span, read in the display zone (``db db/timezone`` at the top,
UTC with none) unless it carries ``Z`` or an offset."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

import dvc_dat.ledger.txn as txn_mod
from dvc_dat.ledger.value import is_moment, moment

STAMPS = ["2026-11-02T00:00:00Z",       # rev 1
          "2026-11-02T01:00:00Z",       # rev 2
          "2026-11-02T01:30:00Z",       # rev 3
          "2026-11-02T01:30:15Z",       # rev 4
          "2026-11-03T12:00:00Z"]       # rev 5


def stamped(L, monkeypatch, stamps, zone=None):
    """One revision per stamp, each with ``db/time`` the given stamp; ``zone`` set on the last."""
    for i, s in enumerate(stamps):
        monkeypatch.setattr(txn_mod, "stamp", lambda s=s: s)
        with L.transaction(by="t") as t:
            t.add("x", "a", str(i))
            if zone is not None and i == len(stamps) - 1:
                t.add("db", "db/timezone", zone)


@pytest.mark.parametrize("which,rev", [
    ("2026-11-02", 1),                    # a day: its 00:00, at or before which rev 1 is stamped
    ("2026-11-03", 4),                    # to include Nov 2, name Nov 3
    ("2026-11-02T01", 2),                 # an hour: exactly 01:00
    ("2026-11-02 01", 2),                 # a space for T
    ("2026-11-02T01:29", 2),              # a minute
    ("2026-11-02T01:30", 3),
    ("2026-11-02T01:30:14", 3),           # a second
    ("2026-11-02T01:30:15", 4),
    ("2026-11-02 01:30:15", 4),
    ("2026-11-04", 5),                    # after the last stamp: the top
])
def test_at_reads_every_precision_as_the_start_of_its_span(L, monkeypatch, which, rev):
    stamped(L, monkeypatch, STAMPS)
    assert L.at(which).id == rev


def test_at_reads_an_unsuffixed_stamp_in_utc_with_no_zone(L, monkeypatch):
    stamped(L, monkeypatch, STAMPS)
    assert L.at().timezone.key == "UTC"
    assert L.at("2026-11-02T01:29:59").id == 2 and L.at("2026-11-02T01:29:59Z").id == 2


def test_at_reads_an_unsuffixed_stamp_in_the_display_zone_at_the_top(L, monkeypatch):
    """``db db/timezone`` at the top decides (set here on the last revision only); ``Z`` or an offset
    overrides it."""
    stamped(L, monkeypatch, STAMPS, zone="America/Los_Angeles")      # PST, -08:00, after Nov 1 2026 02:00
    assert L.at("2026-11-01T17").id == 2                               # 17:00 PST is 01:00Z
    assert L.at("2026-11-01 17:30").id == 3
    assert L.at("2026-11-02").id == 4                                  # 08:00Z
    assert L.at("2026-11-02T01Z").id == 2
    assert L.at("2026-11-02T01:00+00:00").id == 2
    assert L.at("2026-11-02T02:30:15+01:00").id == 4                  # 01:30:15Z
    assert L.at("2026-11-01T17:29:59-08:00").id == 2
    assert L.at("2026-11-01T18:30-07:00").id == 3                     # 01:30Z


def test_at_before_the_first_stamp_is_a_key_error(L, monkeypatch):
    stamped(L, monkeypatch, STAMPS)
    with pytest.raises(KeyError, match="first is stamped 2026-11-02T00:00:00"):
        L.at("2026-11-01T23:59:59")
    with pytest.raises(KeyError, match="first is stamped"):
        L.at("2026-11-01")


def test_at_reads_the_offset_form_of_db_time(L, monkeypatch):
    """2.44.0 to 2.46.x stored ``db/time`` with an offset (``+00:00``, ``-07:00``); both forms parse."""
    stamped(L, monkeypatch, ["2026-11-02T00:00:00+00:00", "2026-11-01T18:00:00-07:00", "2026-11-02T02:00:00Z"])
    assert L.at("2026-11-02T00:59").id == 1
    assert L.at("2026-11-02T01").id == 2                               # 18:00-07:00 is 01:00Z
    assert L.at("2026-11-02T02").id == 3


def test_a_moment_out_of_range_is_a_value_error(L, monkeypatch):
    stamped(L, monkeypatch, STAMPS)
    for bad in ("2026-13-02", "2026-11-02T25", "2026-11-02T01:61", "2026-11-02T01:00+24:00"):
        with pytest.raises(ValueError, match="moment"):
            L.at(bad)


def test_a_string_that_is_no_moment_is_still_a_tag(L, monkeypatch):
    """The order: digits, version, timestamp, tag; a near-miss of the timestamp form is a tag name."""
    for near in ("2026-11", "2026-11-02T", "2026-11-02Z", "2026-11-02T1", "2026-11-02T01:30:15.5",
                 "2026-Q4-official", "2026-11-02T01+01"):
        assert not is_moment(near)
    stamped(L, monkeypatch, STAMPS)
    with L.transaction(by="t") as t:
        t.add("db", "db/tag", "2026-11")
    assert L.at("2026-11").id == 6
    assert L.at("2026-11-02T01").id == 2


@pytest.mark.parametrize("name", ["2026-11-02", "2026-11-02T14", "2026-11-02 14:30", "2026-11-02T14:30:15Z",
                                  "2026-11-02T14:30+05:30", "2026-13-40"])
def test_a_db_tag_that_parses_as_a_timestamp_is_refused(L, name):
    with pytest.raises(ValueError, match="ISO 8601 timestamp"):
        with L.transaction(by="t") as t:
            t.add("db", "db/tag", name)
    assert L.at().id == 0


def test_moment_reads_a_dst_ambiguous_or_skipped_time_with_fold_0():
    """Los Angeles 2026: 01:30 on Nov 1 happens twice (fold=0, the first, PDT -07:00); 02:30 on Mar 8 never
    happens (fold=0, the offset before the change, PST -08:00)."""
    la = ZoneInfo("America/Los_Angeles")
    assert moment("2026-11-01T01:30", la) == datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc)
    assert moment("2026-03-08T02:30", la) == datetime(2026, 3, 8, 10, 30, tzinfo=timezone.utc)
    assert moment("2026-07-01", la) == datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc)
    assert moment("2026-07-01T00Z", la) == datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
