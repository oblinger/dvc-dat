"""``dat``: dvc-dat's decorators under one name (SVP 250 Q4), so code says what each belongs to.

    from dvc_dat import dat

    @dat.fn                              # a value function: the Rev first, keywords after, a Value back
    def cut(rev, *, game: str) -> Cut: ...

    @dat.fn(reproducible="exact")        # ... claiming a rerun gives the same bytes (on one card)
    def detect(rev, *, video: Video) -> Table: ...

    @dat.warm                            # a process-level memo by the canonical hash of the arguments
    def kit_at(ledger, rev) -> Kit: ...

    @dat.command(args="game=…", help="train on one game")   # also `just <name>`
    @dat.fn
    def train(rev, *, game: str, path: Path) -> StageDat: ...

    dat.at("do26@512")                   # a revision on any registered ledger
    dat.load("do26@512:sha256:<hex>")    # a value by the global reference; a bare name reads the active ledger

``at`` and ``load`` are ``dvc_dat.ledger.named``'s; ``ledger.at(rev)`` stays that ledger's alone (SVP 248).
``fn`` is ``dvc_dat.ledger.fn.fn``, ``warm`` is ``dvc_dat.ledger.warm.warm`` and ``command`` is
``dvc_dat.just.command``; each is documented there.
"""

from .just import command
from .ledger.fn import FnMark, fn, fn_mark
from .ledger.named import at, load
from .ledger.warm import warm

__all__ = ["fn", "warm", "command", "at", "load", "FnMark", "fn_mark"]
