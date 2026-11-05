"""Ledger functions the round-4 leftover tests run (module level, so `rev.run` resolves them by name)."""

from dvc_dat.ledger import Value
from dvc_dat import dat

CALLS = {}


@dat.fn
def reads(rev, *, s: str, p: str) -> dict:
    CALLS[s] = CALLS.get(s, 0) + 1
    return {"o": rev.get(s, p)}


@dat.fn
def local_value(rev, *, n: int) -> Value:
    class Inner(Value):
        def __init__(self, d):
            self.d = d

        def encode(self, out) -> None:

            out.write(self.d)

        @classmethod
        def decode(cls, src, store):
            return cls(src.read())
    return Inner(b"x" * n)


@dat.fn
def echo(rev, *, x: object) -> dict:
    return {"x": x}
