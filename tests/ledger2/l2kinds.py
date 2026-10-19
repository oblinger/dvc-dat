"""Value kinds and value functions the ledger2 tests seal and evaluate (module level: ``Ref.type``
resolves a class by its dotted name, ``load_fn`` a function by its)."""

from pathlib import Path

import l2helper
from dvc_dat.ledger2 import Dat, Ref, Value, ledger_class, ledger_fn

CALLS = {}


def _count(name):
    CALLS[name] = CALLS.get(name, 0) + 1


@ledger_class(preds=("game", "camera", "span"))
class Video(Value):
    def __init__(self, frames: bytes):
        self.frames = frames

    def encode(self) -> bytes:
        return self.frames

    @classmethod
    def decode(cls, data, store):
        return cls(data)


@ledger_class(preds=("game", "version", "video", "team"))
class Cut(Value):
    def __init__(self, clip: bytes):
        self.clip = clip

    def encode(self) -> bytes:
        return self.clip

    @classmethod
    def decode(cls, data, store):
        return cls(data)


class Plain(Value):
    def __init__(self, data: bytes):
        self.data = data

    def encode(self) -> bytes:
        return self.data

    @classmethod
    def decode(cls, data, store):
        return cls(data)


@ledger_fn
def cut(rev, *, game: str, version: str = "1.0.0") -> Cut:
    _count("cut")
    home = rev[f"game/{game}", "home"]
    raw = rev.value(kind=Video, game=game)
    c = Cut(raw.frames[:4] + home.encode())
    c.preds.update(game=game, version=version, video=raw)
    return c


@ledger_fn
def thumb(rev, *, clip) -> dict:
    _count("thumb")
    return {"n": len(clip.load().clip)}


@ledger_fn
def poster(rev, *, game: str) -> dict:
    _count("poster")
    return {"n": len(rev.load(f"game/{game}").clip)}


@ledger_fn
def chain(rev, *, game: str) -> dict:
    _count("chain")
    return {"thumb": rev.eval("l2kinds.cut", game=game).hash[:8]}


@ledger_fn
def folder(rev, *, game: str, work: Path) -> Dat:
    _count("folder")
    (work / "a.txt").write_text(game)
    return Dat(work)


@ledger_fn
def wrong(rev, *, game: str) -> Cut:
    return {"not": "a cut"}


@ledger_fn
def via_ref(rev, *, name: str) -> dict:
    return {"n": l2helper.twice(len(Ref(rev, name).load().data))}


@ledger_fn
def via_ref_preds(rev, *, name: str) -> dict:
    return {"game": Ref(rev, name).preds.get("game")}


@ledger_fn
def via_refs_rev(rev, *, game: str) -> dict:
    r = rev.refs(game=game)[0]
    return {"note": r.rev.get(r.subject, "note")}


@ledger_fn
def maybe(rev, *, game: str) -> dict:
    hit = rev.eval("l2kinds.cut", game=game, memo="get")
    return {"had": hit is not None}


@ledger_fn
def scratchy(rev, *, game: str, work: Path) -> dict:
    CALLS["work"] = work
    (work / "tmp.txt").write_text(game)
    return {"game": game}
