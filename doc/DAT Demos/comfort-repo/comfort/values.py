"""`comfort.values`: a city's days and a comfort count."""
import json

from dvc_dat.ledger import Value, ledger_class


@ledger_class(preds=("city",))
class Days(Value):
    """A city's days: one row per day, [date, °F, humidity %], and its comfort once scored."""

    def __init__(self, days):
        self.days = [list(day) for day in days]

    def encode(self) -> bytes:
        return json.dumps(self.days).encode()

    @classmethod
    def decode(cls, data: bytes, store) -> "Days":
        return cls(json.loads(data))


@ledger_class(preds=("city",))
class ComfortCounts(Value):
    """How many of a city's days sit at each comfort level, 0 (miserable) to 9 (ideal)."""

    def __init__(self, counts):
        self.counts = list(counts)

    def encode(self) -> bytes:
        return json.dumps(self.counts).encode()

    @classmethod
    def decode(cls, data: bytes, store) -> "ComfortCounts":
        return cls(json.loads(data))
