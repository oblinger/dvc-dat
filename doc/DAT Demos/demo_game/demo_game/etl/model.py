"""`demo_game.etl.model`: stage 3, a model trained on the tracks."""
import json
from pathlib import Path

from dvc_dat.ledger2 import ledger_fn
from demo_game.etl.dat import StageDat, build


@ledger_fn
def train(rev, *, game: str, work: Path) -> StageDat:
    epochs = int(rev["cfg/train", "epochs"])            # traced
    d = build(rev, {"main": "demo_game.etl.model.fit", "stage": "model",
                    "game": game, "epochs": epochs}, work)
    d.preds["gameset"] = rev[f"game/{game}", "gameset"]  # traced
    return d


def fit(rev, work, *, game, epochs, **_):
    trk = rev.eval("demo_game.etl.track.tracks", game=game)
    runs = json.loads((trk.path / "tracks.json").read_text())
    weights = [round(r * epochs / 100, 3) for r in runs]
    (work / "weights.json").write_text(json.dumps(weights))
    score = round(1 - 1 / (1 + sum(weights)), 3)
    return {"metrics": {"count": len(weights), "score": score}}
