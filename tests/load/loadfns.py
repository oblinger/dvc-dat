"""The value kind and the base-mode ledger function the load harness seals and evaluates.

Kept free of repo imports beyond ``dvc_dat.ledger`` so its ``fn`` subject (the static import
closure inside ``tests/load``) is this one file.
"""

from dvc_dat.ledger import Value, ledger_class, ledger_fn

#: Runs of ``square`` in this process: an eval that moved it missed the memo.
CALLS = {"square": 0}


@ledger_class(preds=("owner", "seq"))
class Blob(Value):
    def __init__(self, data: bytes):
        self.data = data

    def encode(self) -> bytes:
        return self.data

    @classmethod
    def decode(cls, data, store):
        return cls(data)


def expected(n: int, salt: str) -> str:
    return f"{n}:{salt}:{n * n}"


@ledger_fn
def square(rev, *, n: int) -> str:
    CALLS["square"] += 1
    salt = rev["load/config", "salt"]
    return expected(n, salt)
