"""`svp.etl.track`: stage 2, tracks linked from the detections."""
import json

from dvc_dat.ledger import ledger_fn
from svp.etl.dat import StageDat, build


@ledger_fn
def tracks(rev, *, game: str) -> StageDat:
    dets = rev.eval("svp.etl.detect.detections", game=game)
    return build(rev, {"main": "svp.etl.track.link",
                       "stage": "track", "game": game}, dets=dets)


def link(rev, folder, *, dets, **_):
    boxes = json.loads((dets.path / "boxes.json").read_text())
    runs = [b for a, b in zip(boxes, boxes[1:]) if a <= b]
    (folder / "tracks.json").write_text(json.dumps(runs))
    score = round(len(runs) / len(boxes), 3)
    return {"metrics": {"count": len(runs), "score": score}}
