"""`Shots`: a hand-made `Value` kind, a shot table as parquet."""

import pandas as pd

from dvc_dat.ledger import Value


class Shots(Value):
    def __init__(self, table: pd.DataFrame):
        self.table = table

    def encode(self, out) -> None:
        self.table.to_parquet(out)

    @classmethod
    def decode(cls, src, store):
        return cls(pd.read_parquet(src))
