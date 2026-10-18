"""`svp.etl.detect`: stage 1, detections from the game's rows."""
import json

from dvc_dat.ledger import ledger_fn
from svp.etl.dat import StageDat, build


@ledger_fn
def detections(rev, *, game: str) -> StageDat:
    return build(rev, {"main": "svp.etl.detect.find",
                       "stage": "detect", "game": game, "bins": 16})


def find(rev, folder, *, game, bins, **_):
    seed = sum(map(ord, rev[f"game/{game}", "court"]))   # traced
    boxes = [(seed * (i + 7)) % bins for i in range(40)]
    (folder / "boxes.json").write_text(json.dumps(boxes))
    score = round(sum(boxes) / (bins * len(boxes)), 3)
    return {"metrics": {"count": len(boxes), "score": score}}
