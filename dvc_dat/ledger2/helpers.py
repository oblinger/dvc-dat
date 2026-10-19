"""``bump``: raise a clock subject's version inside a transaction (Q33). (``attr`` lives in ``txn``.)"""

from __future__ import annotations

import re
from typing import Callable, Optional

from .codec import show
from .txn import Transaction

_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def bump(t: Transaction, subject: str, part: str = "patch", *,
         confirm: Optional[Callable[[str, str], bool]] = None) -> str:
    """Read ``version`` through ``t.base`` (``0.0.0`` when absent), add the next by ``part``, return it.

    For clocks only: a subject holding a ``db/alias`` row raises ``TypeError`` naming the alias (a
    value's version is a pred; a new version is a new seal and a re-point). On ``code/<repo>`` it
    also writes ``commit``, read from that repo's checkout by discovery; no checkout, or a dirty
    one, is ``ValueError`` (A29). ``minor`` and ``major`` need ``confirm(old, new)`` to answer
    ``True``; without ``confirm`` they are refused (A38). Nothing is written on any refusal.
    """
    from .env import current_env

    held = t.base._held(subject, "db/alias")
    if held:
        raise TypeError(f"{subject!r} is an alias (of {show(held[0].obj)[:12]}…): a value's version is a pred; "
                        "seal the new version and re-point the alias")
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
    commit = None
    if subject.startswith("code/"):
        repo = subject[len("code/"):]
        code = current_env().code.get(repo)
        if code is None or not code.commit:
            raise ValueError(f"no checkout for {subject} in this environment")
        if code.dirty:
            raise ValueError(f"the checkout of {repo} has uncommitted changes: commit them, then bump "
                             f"(a version must pin a commit)")
        commit = code.commit
    t.add(subject, "version", new)
    if commit is not None:
        t.add(subject, "commit", commit)
    return new
