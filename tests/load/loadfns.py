"""The value kind and the base-mode ledger function the load harness seals and evaluates.

Kept free of repo imports beyond ``dvc_dat.ledger`` so its ``fn`` subject (the static import
closure inside ``tests/load``) is this one file.
"""

from dvc_dat.ledger import Value, ledger_class
from dvc_dat import dat

#: Runs of ``square`` in this process: an eval that moved it missed the memo.
CALLS = {"square": 0}


@ledger_class(preds=("owner", "seq"))
class Blob(Value):
    def __init__(self, data: bytes):
        self.data = data

    def encode(self, out) -> None:

        out.write(self.data)

    @classmethod
    def decode(cls, src, store):
        return cls(src.read())


def expected(n: int, salt: str) -> str:
    return f"{n}:{salt}:{n * n}"


@dat.fn
def square(rev, *, n: int) -> str:
    CALLS["square"] += 1
    salt = rev["load/config", "salt"]
    return expected(n, salt)
