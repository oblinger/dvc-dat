"""`demo_game.etl.detect`: stage 1, detections from the game's rows."""
import json
from pathlib import Path

from dvc_dat.ledger import ledger_fn
from demo_game.etl.dat import StageDat, build

SPEC = {"main": "demo_game.etl.detect.find", "stage": "detect",
        "bins": 16}


@ledger_fn
def detections(rev, *, game: str, work: Path) -> StageDat:
    return build(rev, {**SPEC, "game": game}, work)


def find(rev, work, *, game, bins, **_):
    seed = sum(map(ord, rev[f"game/{game}", "court"]))   # traced
    boxes = [(seed * (i + 7)) % bins for i in range(40)]
    (work / "boxes.json").write_text(json.dumps(boxes))
    score = round(sum(boxes) / (bins * len(boxes)), 3)
    return {"metrics": {"count": len(boxes), "score": score}}
