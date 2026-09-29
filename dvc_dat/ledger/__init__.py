"""``dvc_dat.ledger``: the ledger, one append-only table of events under a rev.

A dat is space, the ledger is time. Everything the ledger commits to is
re-exported here; anything else in ``dvc_dat.ledger.*`` is not a surface,
except :class:`~dvc_dat.ledger.sql.SqlLedger` for a backend to subclass.

    from dvc_dat.ledger import Ledger, Ref
    L = Ledger.open()                       # a profile, DAT_LEDGER, or ledger.profile.yaml
    with L.transaction(by="dan") as tx:
        tx.assign("game/G7", "court", "hs-wood-2")
        tx.add("gameset", "NORM", Ref("game/G7"))
    L.get_spec("game/G7", rev=tx.rev)
"""

from .codec import BLOB_BYTES
from .core import Batch, Ledger
from .errors import LedgerError
from .ref import Event, Ref, Rev, Value
from .shelf import LocalShelf, Shelf
from .sql import SqlLedger, SqliteLedger
from .types import Artifact, Node, ckpt, file, json, video

__all__ = ["Ledger", "Ref", "Event", "Batch", "Rev", "Value", "Node", "Artifact", "LedgerError", "BLOB_BYTES",
           "SqlLedger", "SqliteLedger", "Shelf", "LocalShelf", "json", "file", "ckpt", "video"]
