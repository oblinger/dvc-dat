"""``bump``: raise a subject's version inside a transaction. (``attr`` lives in ``txn``.)"""

from __future__ import annotations

import re
from typing import Callable, Optional

from .txn import Transaction

_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def bump(t: Transaction, subject: str, part: str = "patch", *,
         confirm: Optional[Callable[[str, str], bool]] = None) -> str:
    """Read ``version`` through ``t.base`` (``0.0.0`` when absent), add the next by ``part``, return it.

    ``minor`` and ``major`` need ``confirm(old, new)`` to answer ``True``; without ``confirm`` they are refused.
    """
    if part not in ("patch", "minor", "major"):
        raise ValueError(f"part is 'patch', 'minor' or 'major', not {part!r}")
    old = t.base.get(subject, "version", default="0.0.0")
    m = _VERSION.match(old) if isinstance(old, str) else None
    if m is None:
        raise ValueError(f"{subject!r} version {old!r} is not MAJOR.MINOR.PATCH")
    a, b, c = (int(x) for x in m.groups())
    new = {"patch": f"{a}.{b}.{c + 1}", "minor": f"{a}.{b + 1}.0", "major": f"{a + 1}.0.0"}[part]
    if part != "patch":
        if confirm is None:
            raise ValueError(f"bump {part} of {subject!r} ({old} -> {new}) needs confirm=")
        if confirm(old, new) is not True:
            raise ValueError(f"bump {part} of {subject!r} ({old} -> {new}) refused by confirm")
    t.add(subject, "version", new)
    return new
