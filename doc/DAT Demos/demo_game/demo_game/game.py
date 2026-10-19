"""`demo_game.game`: the values notebook's worked example, a cut.

A `Value` subclass lives in a module, never in a notebook cell: the
`db/value` row names its class by dotted name (`Ref.type`), and a
class defined in a cell has no name a later `load` can import.
Written to the ledger design of 2026-10-18 (T534).
"""
import random
import time

from dvc_dat.ledger import Ref, Value, ledger_class, ledger_fn


class PlainVideo(Value):
    """A game's raw video, as imported: no decorator, so no preds."""

    def __init__(self, frames: bytes):
        self.frames = frames

    def encode(self) -> bytes:
        return self.frames

    @classmethod
    def decode(cls, data: bytes, store) -> "PlainVideo":
        return cls(data)


@ledger_class(preds=("game", "camera", "span"))
class Video(Value):
    """A game's raw video, as imported."""

    def __init__(self, frames: bytes):
        self.frames = frames

    def encode(self) -> bytes:
        return self.frames

    @classmethod
    def decode(cls, data: bytes, store) -> "Video":
        return cls(data)


@ledger_class(preds=("game", "version", "video", "team"))
class Cut(Value):
    """A cut of a game's video: the clip the pipeline runs on."""

    def __init__(self, clip: bytes):
        self.clip = clip

    def encode(self) -> bytes:
        return self.clip

    @classmethod
    def decode(cls, data: bytes, store) -> "Cut":
        return cls(data)


def cut_video(raw: Video, home: str, away: str) -> bytes:
    """The stand-in cutter: the first frames, stamped with the teams.

    The cutter's version does not enter the bytes, so two versions of
    one cut can be byte-identical.
    """
    return raw.frames[:16] + f"|{home}-{away}".encode()


@ledger_fn
def cut(rev, *, game: str, version: str) -> Cut:
    """Cut a game: rows read through `rev`, the video by preds."""
    home = rev[f"game/{game}", "home"]      # traced: game/G1 home
    away = rev[f"game/{game}", "away"]      # traced: game/G1 away
    raw = rev.value(kind=Video, game=game)  # traced: q: and bytes
    c = Cut(cut_video(raw, home, away))
    c.preds.update(game=game, version=version,
                   video=raw,               # a Video-typed pred
                   team=[home, away])       # a many pred: a list
    return c


@ledger_fn
def thumb(rev, *, clip: Ref) -> dict:
    """Downstream of one cut, keyed by the cut itself.

    `-> dict` names no `Value` subclass, so the result is wrapped in
    `Pickled` and the annotation recorded as `db/returns`.
    """
    c = clip.load()
    return {"bytes": len(c.clip), "head": c.clip[:4].hex()}


@ledger_fn
def poster(rev, *, game: str) -> dict:
    """Downstream of the game's current cut, reached by its alias."""
    c = rev.load(f"game/{game}")    # traced: game/G1 db/alias
    return {"game": game, "bytes": len(c.clip)}


@ledger_fn
def noisy(rev, *, game: str) -> dict:
    """A nondeterministic stand-in (T527's case): runs disagree."""
    time.sleep(1)                   # long enough for two to race
    return {"game": game, "draw": random.random()}


@ledger_class(preds=("game",))
class Still(Value):
    """One frame of a game's video; was `demo_game.legacy.Frame`."""

    def __init__(self, image: bytes):
        self.image = image

    def encode(self) -> bytes:
        return self.image

    @classmethod
    def decode(cls, data: bytes, store) -> "Still":
        return cls(data)
