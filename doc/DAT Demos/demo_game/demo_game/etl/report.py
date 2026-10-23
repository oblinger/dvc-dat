"""`demo_game.etl.report`: one parquet `Value.Table` over a game set."""
import pyarrow as pa

from dvc_dat.ledger import Value, ledger_fn
from demo_game.etl.dat import StageDat


@ledger_fn
def scores(rev, *, gameset: str) -> Value.Table:
    models = rev.values(kind=StageDat, stage="model",
                        gameset=gameset)        # traced: a q: item
    rows = sorted((m.preds["game"], m.preds["metrics.score"])
                  for m in models)
    return Value.Table(pa.table({"game": [g for g, _ in rows],
                           "score": [s for _, s in rows]}))
