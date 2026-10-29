"""Ledger functions the round-4 leftover tests run (module level, so `rev.run` resolves them by name)."""

from dvc_dat.ledger import ledger_fn, Value

CALLS = {}


@ledger_fn
def reads(rev, *, s: str, p: str) -> dict:
    CALLS[s] = CALLS.get(s, 0) + 1
    return {"o": rev.get(s, p)}


@ledger_fn
def local_value(rev, *, n: int) -> Value:
    class Inner(Value):
        def __init__(self, d):
            self.d = d

        def encode(self):
            return self.d

        @classmethod
        def decode(cls, data, store):
            return cls(data)
    return Inner(b"x" * n)
