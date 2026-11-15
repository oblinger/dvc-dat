"""The reproducibility claim (SVP 251 Q2): how far a rerun of a function can be trusted, one ordered scale.

``@dat.fn(reproducible=...)`` takes a level, ``"exact"`` (bit-identical), ``True`` (good enough, no need to save
it), ``None`` (unknown, the default) or ``False`` (flaky, save it); a clause, a tuple of a level and the predicates
that must match for it, ``("exact", "platform/card")``; or a list of those read in order, first match wins:
``[("exact", "platform/card"), (True, "assets/rev"), False]``. A predicate is a row the value carries, which the
consumer writes; dvc-dat only compares them, and a clause naming one the value does not carry does not match.
Falling off the list means unknown.

The claim is read from the ledger, never from code, since ``safe`` cannot import a past commit: one row at seal,
``(<value>, db/reproducible, <clauses as JSON>)``, beside ``db/fn``, ``db/keys`` and ``db/returns``, outside the
subject's hash. ``None`` writes no row.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, List, Mapping, Optional, Sequence, Tuple

from .codec import canonical, show

if TYPE_CHECKING:
    from .rev import Rev

EXACT = "exact"
PREDICATE = "db/reproducible"
Clause = Tuple[Any, Tuple[str, ...]]


def _level(x: Any) -> Any:
    if x is None or x is True or x is False or (isinstance(x, str) and x == EXACT):
        return x
    raise TypeError(f"a reproducible level is 'exact', True, None or False, not {x!r}")


def clauses(claim: Any) -> List[Clause]:
    """``claim`` as its ordered ``(level, predicates)`` clauses; ``TypeError`` on anything the grammar refuses."""
    items = claim if isinstance(claim, list) else [claim]
    if not items:
        raise TypeError("a reproducible list holds at least one clause")
    out: List[Clause] = []
    for c in items:
        if not isinstance(c, tuple):
            out.append((_level(c), ()))
            continue
        if not c:
            raise TypeError("a reproducible clause is (level, predicate, ...), not ()")
        preds = c[1:]
        if not all(isinstance(p, str) and p for p in preds):
            raise TypeError(f"a reproducible clause names its predicates by non-empty str, not {preds!r}")
        out.append((_level(c[0]), tuple(preds)))
    return out


def claim_text(claim: Any) -> Optional[str]:
    """The ``db/reproducible`` row's document, canonical JSON; ``None`` for no claim (no row)."""
    found = clauses(claim)
    if found == [(None, ())]:
        return None
    return canonical([[level, list(preds)] for level, preds in found])


def claim_of(rev: "Rev", subject: str) -> List[Clause]:
    """The clauses the row on ``subject`` holds at ``rev``; a value with no row claims nothing."""
    held = rev._held(subject, PREDICATE)
    if not held:
        return [(None, ())]
    return [(level, tuple(preds)) for level, preds in json.loads(show(held[0].obj))]


def widens(claim: Any) -> bool:
    """Does a memo lookup of this function also ask for the same card and driver: any clause reaching ``exact``."""
    return any(level == EXACT for level, _preds in clauses(claim))


def unconditional(found: Sequence[Clause]) -> Any:
    """The level a value holds whatever exists later: the first clause with no predicates (none past it is ever
    reached); ``None`` with no such clause, since a claim only conditional on a predicate has no fallback."""
    return next((level for level, preds in found if not preds), None)


def judged(found: Sequence[Clause], old: Mapping[str, str], new: Mapping[str, str]) -> Any:
    """The level of the first clause whose every predicate both values carry, equal; ``None`` past the list."""
    for level, preds in found:
        if all(p in old and p in new and old[p] == new[p] for p in preds):
            return level
    return None


__all__ = ["EXACT", "PREDICATE", "clauses", "claim_text", "claim_of", "widens", "unconditional", "judged"]
