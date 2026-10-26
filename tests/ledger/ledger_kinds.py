"""Value kinds and value functions the ledger tests seal and evaluate (module level: ``Ref.type``
resolves a class by its dotted name, ``load_fn`` a function by its)."""

from pathlib import Path

import ledger_helper
from dvc_dat.ledger import Dat, Ref, Value, ledger_class, ledger_fn

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
    return {"thumb": rev.run("ledger_kinds.cut", game=game).hash[:8]}


@ledger_fn
def folder(rev, *, game: str, path: Path) -> Dat:
    _count("folder")
    (path / "a.txt").write_text(game)
    return Dat(path)


@ledger_fn
def placed(rev, *, game: str, path: Path = "games/{game}") -> Dat:
    _count("placed")
    (path / "g.txt").write_text(game)
    return Dat(path)


@ledger_fn
def controls(rev, *, seal: int, clean: str, kwargs: dict, n: int = 0) -> dict:
    return {"seal": seal, "clean": clean, "kwargs": kwargs, "n": n}


@ledger_fn
def wrong(rev, *, game: str) -> Cut:
    return {"not": "a cut"}


@ledger_fn
def via_ref(rev, *, name: str) -> dict:
    return {"n": ledger_helper.twice(len(Ref(rev, name).load().data))}


@ledger_fn
def via_ref_preds(rev, *, name: str) -> dict:
    return {"game": Ref(rev, name).preds.get("game")}


@ledger_fn
def via_refs_rev(rev, *, game: str) -> dict:
    r = rev.refs(game=game)[0]
    return {"note": r.rev.get(r.subject, "note")}


@ledger_fn
def maybe(rev, *, game: str) -> dict:
    hit = rev.run("ledger_kinds.cut", game=game, seal="get")
    return {"had": hit is not None}


@ledger_fn
def scratchy(rev, *, game: str, path: Path) -> dict:
    CALLS["work"] = path
    (path / "tmp.txt").write_text(game)
    return {"game": game}


@ledger_fn
def sealed_early(rev, *, game: str) -> Cut:
    c = Cut(game.encode())
    c.seal()
    return c


class Dat2(Dat):
    """A ``Dat`` that also loads folders whose ``_spec_`` names one of ``kinds`` (the ``kind_ok`` hook)."""

    kinds: tuple = ()

    @classmethod
    def kind_ok(cls, kind: str) -> bool:
        return kind in cls.kinds or super().kind_ok(kind)


class Blobby(Value):
    """A value whose one part comes from an opener: the encoding names the part's hash."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def encode(self) -> bytes:
        from dvc_dat.ledger.codec import sha256

        return sha256(self.data).encode()

    def _parts(self):
        import io

        from dvc_dat.ledger.codec import sha256

        return [(sha256(self.data), lambda: io.BytesIO(self.data))]

    @classmethod
    def decode(cls, data: bytes, store) -> "Blobby":
        return cls(store.get(data.decode()))


@ledger_class(preds=("game", "take"))
class GameDat(Dat):
    """A folder value with preds: the seal-record tests reopen it in another process."""


def build_table(dat, n=10, start=1):
    """A dat's run function (``Dat.do`` / ``rev.do``): ``table.csv``, ``cells`` in the results, saved."""
    _count("build_table")
    Path(dat.get_path(), "table.csv").write_text(f"{n} from {start}\n")
    dat.get_results()["cells"] = n * n
    dat.save()
    return dat


def never_saves(dat, n=1):
    """A run function that leaves its dat open."""
    Path(dat.get_path(), "x.txt").write_text(str(n))


@ledger_class(preds=("note",))
class NotedDat(Dat):
    """A dat kind declaring one pred of its own beside its folder's."""
