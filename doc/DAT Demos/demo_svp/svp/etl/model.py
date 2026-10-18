"""`svp.etl.model`: stage 3, a model trained on the tracks."""
import json

from dvc_dat.ledger import ledger_fn
from svp.etl.dat import StageDat, build


@ledger_fn
def train(rev, *, game: str) -> StageDat:
    trk = rev.eval("svp.etl.track.tracks", game=game)
    epochs = int(rev["cfg/train", "epochs"])            # traced
    d = build(rev, {"main": "svp.etl.model.fit",
                    "stage": "model", "game": game},
              tracks=trk, epochs=epochs)
    d.preds["gameset"] = rev[f"game/{game}", "gameset"]  # traced
    return d


def fit(rev, folder, *, tracks, epochs, **_):
    runs = json.loads((tracks.path / "tracks.json").read_text())
    weights = [round(r * epochs / 100, 3) for r in runs]
    (folder / "weights.json").write_text(json.dumps(weights))
    score = round(1 - 1 / (1 + sum(weights)), 3)
    return {"metrics": {"count": len(weights), "score": score}}
