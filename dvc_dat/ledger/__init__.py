"""``dvc_dat.ledger``: the ledger, rebuilt to the value-space design (SVP447 Ledger Module).

One logical store: every fact is a quad ``(rev, subject, predicate, object)``;
every read is a function of a ``Rev``; every write is a ``Transaction``;
everything held or handed back is a ``Value``; a sealed computation is a memo
entry findable by ``Rev.run``. SQLite backend; ``run`` unsandboxed (in this
process) or sandbox mode (under a ``db/mount/<prefix>``, in a worker).

    from dvc_dat.ledger import Ledger, Ref, ledger_fn, ledger_class, bump, attr
    L = Ledger()                         # the nearest .datconfig.yaml
    rev = L.at()
    with L.transaction(by="human:dan") as t:
        bump(t, "code/demo-game")

The environment is found by discovery; ``set_env_provider``, ``Env`` and
``Code`` are the test suite's seam only (A51), importable by name.
"""

from .env import Code, Env, set_env_provider  # noqa: F401  (the test seam, importable by name)
from .errors import (AliasLoop, ConfinedNetwork, ConfinedWrite, Exists, LedgerError, LockTimeout, Multiple, NotClean, NotEvaluated, SealBroken, Undeclared,
                     Unindexed,
                     UnmountedImport, UntracedRead)
from .fn import Fn, ledger_fn
from .helpers import bump
from .ledger import Ledger
from .rev import Ref, Rev, Row
from .txn import Transaction, attr
from .value import Dat, Value, ledger_class

__all__ = ["Ledger", "Rev", "Ref", "Row", "Transaction", "Value", "Dat", "Fn",
           "ledger_fn", "ledger_class", "bump", "attr", "LedgerError", "Multiple", "NotEvaluated", "NotClean",
           "UnmountedImport", "UntracedRead", "ConfinedWrite", "ConfinedNetwork", "LockTimeout", "Unindexed", "Exists", "Undeclared",
           "AliasLoop", "SealBroken"]
