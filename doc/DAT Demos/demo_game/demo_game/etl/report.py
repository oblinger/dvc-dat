"""`demo_game.etl.report`: one parquet `Table` over a game set."""
import pyarrow as pa

from dvc_dat.ledger import Table, ledger_fn
from demo_game.etl.dat import StageDat


@ledger_fn
def scores(rev, *, gameset: str) -> Table:
    models = rev.values(kind=StageDat, stage="model",
                        gameset=gameset)        # traced: a q: item
    rows = sorted((m.preds["game"], m.preds["metrics.score"])
                  for m in models)
    return Table(pa.table({"game": [g for g, _ in rows],
                           "score": [s for _, s in rows]}))
