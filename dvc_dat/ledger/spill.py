"""Large values spilled to the art store: a row too big for the triples holds a reference to its bytes.

Two per-ledger settings, rows of the subject ``db`` as every setting is (``db/memo-policy``, ``db/timezone``,
``db/values``), read at the transaction's base, each a ``str`` of a whole number of bytes:

``(db, db/spill-threshold, <n>)``
    a user row whose object encodes to more than ``n`` bytes (its tagged text, UTF-8) is spilled: its bytes go to
    the ledger's art store by their sha256, pushed to its values URI with the seals' bytes, and the row holds
    ``spill:<tag>:<sha256>:<size>``. At or under ``n`` it is stored inline. Absent: ``DEFAULT_THRESHOLD`` (64 KiB).
    Under ``FLOOR`` is refused: the reference is ~90 bytes, so spilling less saves nothing.
``(db, db/max-fact, <n>)``
    a user row whose object encodes to more than ``n`` bytes is refused at commit (``FactTooLarge``), nothing
    written. Absent: no limit of the ledger's own. At or below the threshold, nothing ever spills: a small-facts
    ledger.

Both judge user rows only: a predicate not starting ``db/`` (a sealed value's preds and a transaction's keywords
included). The ledger's own ``db/`` rows are never spilled nor refused, since its machinery finds them by object.

Bytes are content-addressed, so identical values are stored once. A single read (``rev[s, p]``, ``rev.get(s, p)``, a
sealed value's ``v.preds[p]``) returns the value itself; every other read (``all``, ``history``, ``select``,
``rev[s]``, iterating ``preds``) returns a ``Spilled``, its hash and size read off the row, its bytes fetched only by
``load``. A query never looks inside a spilled value: ``where=``, ``in`` and a three-position pattern match it only
by equality with the whole value given, compared by hash.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional, Tuple

from .codec import parse_spill, show

if TYPE_CHECKING:
    from .rev import Rev

#: The settings' predicates.
SPILL_THRESHOLD = "db/spill-threshold"
MAX_FACT = "db/max-fact"
#: The threshold with no row: 64 KiB.
DEFAULT_THRESHOLD = 65536
#: The least threshold a row may set.
FLOOR = 128


def check_setting(subject: str, predicate: str, obj: Any) -> None:
    """Refuse a malformed ``db/spill-threshold`` or ``db/max-fact`` row at ``add`` (``ValueError``)."""
    if subject != "db":
        raise ValueError(f"{predicate} is a setting of the ledger, a row of the subject db, not {subject!r}")
    if not (isinstance(obj, str) and obj.isdigit() and obj.isascii()):
        raise ValueError(f"db {predicate}: a whole number of bytes as a str, such as '65536', not {obj!r}")
    if predicate == SPILL_THRESHOLD and int(obj) < FLOOR:
        raise ValueError(f"db {SPILL_THRESHOLD}: {obj} is under {FLOOR} bytes; a spill's reference is about 90 "
                         "bytes, so spilling less saves nothing")


def limits(rev: "Rev") -> Tuple[int, Optional[int]]:
    """``(spill threshold, max fact or None)`` in force at ``rev``."""
    if not rev.id:
        return DEFAULT_THRESHOLD, None
    held = rev._held("db", SPILL_THRESHOLD)
    threshold = int(show(held[0].obj)) if held else DEFAULT_THRESHOLD
    held = rev._held("db", MAX_FACT)
    return threshold, (int(show(held[0].obj)) if held else None)


def decode_plain(text: str) -> Any:
    """A ``str:`` or ``json:`` text's object."""
    t, _, rest = text.partition(":")
    if t == "str":
        return rest
    if t == "json":
        return json.loads(rest)
    raise ValueError(f"a spilled object is a str: or json: text, not {text[:40]!r}")


class Spilled:
    """A row's object stored in the art store, as a listing, scan or query returns it: ``tag`` (``str`` or
    ``json``), ``hash`` (the sha256 of its encoded text) and ``size`` (bytes), all read off the row. ``load()``
    fetches the bytes (from the values URI on a miss) and returns the ``str``, ``dict`` or ``list`` itself. Equal to
    another by its bytes."""

    __slots__ = ("_rev", "_text", "tag", "hash", "size")

    def __init__(self, rev: "Rev", text: str) -> None:
        self._rev = rev
        self._text = text
        self.tag, self.hash, self.size = parse_spill(text)

    def load(self) -> Any:
        """The value: its bytes from the ledger's art store, pulled from its values URI on a miss."""
        from .backends import puller

        ledger = self._rev.ledger
        art = ledger._store.art
        with art.fetching(puller(ledger)), art.open(self.hash) as f:
            return decode_plain(f.read().decode("utf-8"))

    def _opener(self) -> Any:
        """A zero-arg opener of the bytes, for a transaction carrying them to another ledger."""
        from .backends import puller

        ledger = self._rev.ledger
        art, fetch, h = ledger._store.art, puller(ledger), self.hash

        def opener() -> Any:
            with art.fetching(fetch):
                return art.open(h)
        return opener

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Spilled) and other._text == self._text

    def __hash__(self) -> int:
        return hash(self._text)

    def __repr__(self) -> str:
        return f"<Spilled {self.tag} {self.size} bytes #{self.hash[:8]}>"

    def __reduce__(self) -> Any:
        raise TypeError("a Spilled is bound to an open ledger and does not pickle; load() it")


__all__ = ["Spilled", "SPILL_THRESHOLD", "MAX_FACT", "DEFAULT_THRESHOLD", "FLOOR", "limits"]
