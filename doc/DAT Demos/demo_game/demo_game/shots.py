"""`Shots`: a hand-made `Value` kind, a shot table as parquet."""

import io

import pandas as pd

from dvc_dat.ledger import Value


class Shots(Value):
    def __init__(self, table: pd.DataFrame):
        self.table = table

    def encode(self) -> bytes:
        return self.table.to_parquet()

    @classmethod
    def decode(cls, data, store):
        return cls(pd.read_parquet(io.BytesIO(data)))
