"""``dvc_dat.ledger``: the ledger, rebuilt to the value-space design (SVP447 Ledger Module).

One logical store: every fact is a quad ``(rev, subject, predicate, object)``;
every read is a function of a ``Rev``; every write is a ``Transaction``;
everything held or handed back is a ``Value``; a sealed computation is a memo
entry findable by ``Rev.run``. SQLite backend; ``run`` unsandboxed (in this
process) or sandboxed (under a ``db/mount/<prefix>``, in a worker).

    from dvc_dat.ledger import Ledger, Ref, ledger_fn, ledger_class, bump, bump_source, attr
    L = Ledger()                         # the nearest .datconfig.yaml
    rev = L.at()
    with L.transaction(by="human:dan", lock=10, why="release") as t:
        bump(t, "db", "minor", confirm=lambda old, new: True)
    bump_source("demo_game")             # __version__ in the source; the next clean run moves db/repo/demo-game/demo_game

The environment is found by discovery; ``set_env_provider``, ``Env`` and
``Checkout`` are the test suite's seam only (A51), importable by name.
"""

from .code import Code
from .env import Checkout, Env, set_env_provider  # noqa: F401  (the test seam, importable by name)
from .errors import (AliasLoop, ConfinedNetwork, ConfinedWrite, Exists, LedgerError, LockTimeout, Multiple, NotClean, NotEvaluated, SealBroken, Undeclared, Unlocked,
                     Unindexed,
                     UnmountedImport, UntracedRead)
from .fn import Fn, ledger_fn
from .namespace import LedgerNamespace
from .helpers import SourceBump, bump, bump_source
from .ledger import Ledger
from .rev import Ref, Rev, Row
from .txn import Transaction, attr
from .value import Value, ledger_class
from ..core import Dat                  # one class: a dat is a Value (DAT 1038)

__all__ = ["Ledger", "Rev", "Ref", "Row", "Transaction", "Value", "Dat", "Fn", "Code", "LedgerNamespace",
           "ledger_fn", "ledger_class", "bump", "bump_source", "SourceBump", "attr", "LedgerError", "Multiple", "NotEvaluated", "NotClean",
           "UnmountedImport", "UntracedRead", "ConfinedWrite", "ConfinedNetwork", "LockTimeout", "Unindexed", "Exists", "Undeclared", "Unlocked",
           "AliasLoop", "SealBroken"]
