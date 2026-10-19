"""``dvc_dat.ledger2``: the SVP447 Ledger Module, a spike beside ``dvc_dat.ledger``.

One logical store: every fact is a quad ``(rev, subject, predicate, object)``;
every read is a function of a ``Rev``; every write is a ``Transaction``;
everything held or handed back is a ``Value``; a sealed computation is a memo
entry findable by ``eval``. SQLite backend; ``eval`` in base mode (in this
process) or sandbox mode (under a ``db/mount/<prefix>``, in a worker).

    from dvc_dat.ledger2 import Ledger, Ref, ledger_fn, ledger_class, bump, attr
    L = Ledger()                         # the nearest .datconfig.yaml
    rev = L.at()
    with L.transaction(by="human:dan") as t:
        bump(t, "code/demo-game")

The environment is found by discovery; ``set_env_provider``, ``Env`` and
``Code`` are the test suite's seam only (A51), importable by name.
"""

from .env import Code, Env, set_env_provider
from .errors import (AliasLoop, Exists, LedgerError, LockTimeout, Multiple, NotEvaluated, Undeclared, Unindexed,
                     UnmountedImport, UntracedRead)
from .fn import Fn, ledger_fn
from .helpers import bump
from .ledger import Ledger
from .rev import Ref, Rev, Row
from .txn import Transaction, attr
from .value import Dat, Pickled, Table, Value, ledger_class

__all__ = ["Ledger", "Rev", "Ref", "Row", "Transaction", "Value", "Pickled", "Table", "Dat", "Fn",
           "ledger_fn", "ledger_class", "bump", "attr", "LedgerError", "Multiple", "NotEvaluated",
           "UnmountedImport", "UntracedRead", "LockTimeout", "Unindexed", "Exists", "Undeclared", "AliasLoop",
           "set_env_provider", "Env", "Code"]
