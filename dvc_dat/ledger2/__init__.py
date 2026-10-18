"""``dvc_dat.ledger2``: the SVP447 Ledger Module, a spike beside ``dvc_dat.ledger``.

One logical store: every fact is a quad ``(rev, subject, predicate, object)``;
every read is a function of a ``Rev``; every write is a ``Transaction``;
everything held or handed back is a ``Value``; a sealed computation is a memo
entry findable by ``eval``. SQLite backend; ``eval`` in base mode only.

    from dvc_dat.ledger2 import Ledger, bump, attr
    L = Ledger.open()                    # DAT_LEDGER
    rev = L.at()
    with L.transaction(by="human:dan") as t:
        bump(t, "code/sv-pipe", "patch")
"""

from .errors import (Exists, LedgerError, LockTimeout, Multiple, NotEvaluated, Unindexed, UnmountedImport,
                     UntracedRead)
from .fn import Code, Env, Fn, current_env, set_env_provider
from .helpers import bump
from .ledger import Ledger
from .rev import Ref, Rev
from .txn import Transaction, attr
from .value import Dat, Pickled, Table, Value

__all__ = ["Ledger", "Rev", "Ref", "Transaction", "Value", "Pickled", "Table", "Dat", "Fn", "Code", "Env",
           "bump", "attr", "set_env_provider", "current_env", "LedgerError", "Multiple", "NotEvaluated",
           "UnmountedImport", "UntracedRead", "LockTimeout", "Unindexed", "Exists"]
