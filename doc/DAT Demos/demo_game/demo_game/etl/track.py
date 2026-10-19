"""`demo_game.etl.track`: stage 2, tracks linked from the detections."""
import json
from pathlib import Path

from dvc_dat.ledger2 import ledger_fn
from demo_game.etl.dat import StageDat, build

SPEC = {"main": "demo_game.etl.track.link", "stage": "track"}


@ledger_fn
def tracks(rev, *, game: str, work: Path) -> StageDat:
    return build(rev, {**SPEC, "game": game}, work)


def link(rev, work, *, game, **_):
    dets = rev.eval("demo_game.etl.detect.detections", game=game)
    boxes = json.loads((dets.path / "boxes.json").read_text())
    runs = [b for a, b in zip(boxes, boxes[1:]) if a <= b]
    (work / "tracks.json").write_text(json.dumps(runs))
    score = round(len(runs) / len(boxes), 3)
    return {"metrics": {"count": len(runs), "score": score}}
