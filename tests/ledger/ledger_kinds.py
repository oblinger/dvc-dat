"""Value kinds and value functions the ledger tests seal and evaluate (module level: ``Ref.type``
resolves a class by its dotted name, ``rev.ns.load`` a function by its)."""

from pathlib import Path

import ledger_helper
from dvc_dat.ledger import Dat, Ledger, Ref, Value, ledger_class
from dvc_dat import dat

CALLS = {}


def _count(name):
    CALLS[name] = CALLS.get(name, 0) + 1


@ledger_class(preds=("game", "camera", "span"))
class Video(Value):
    def __init__(self, frames: bytes):
        self.frames = frames

    def encode(self, out) -> None:

        out.write(self.frames)

    @classmethod
    def decode(cls, src, store):
        return cls(src.read())


@ledger_class(preds=("game", "version", "video", "team"))
class Cut(Value):
    def __init__(self, clip: bytes):
        self.clip = clip

    def encode(self, out) -> None:

        out.write(self.clip)

    @classmethod
    def decode(cls, src, store):
        return cls(src.read())


class Plain(Value):
    def __init__(self, data: bytes):
        self.data = data

    def encode(self, out) -> None:

        out.write(self.data)

    @classmethod
    def decode(cls, src, store):
        return cls(src.read())


@dat.fn
def cut(rev, *, game: str, version: str = "1.0.0") -> Cut:
    _count("cut")
    home = rev[f"game/{game}", "home"]
    raw = rev.value(kind=Video, game=game)
    c = Cut(raw.frames[:4] + home.encode())
    c.preds.update(game=game, version=version, video=raw)
    return c


@dat.fn(reproducible="exact")
def cut_det(rev, *, game: str, version: str = "1.0.0") -> Cut:
    """``cut`` claiming ``exact`` (SVP 251 Q2): its lookups ask for the same card and driver."""
    _count("cut_det")
    home = rev[f"game/{game}", "home"]
    raw = rev.value(kind=Video, game=game)
    c = Cut(raw.frames[:4] + home.encode())
    c.preds.update(game=game, version=version, video=raw)
    return c


@dat.fn
def thumb(rev, *, clip) -> dict:
    _count("thumb")
    return {"n": len(clip.load().clip)}


@dat.fn
def poster(rev, *, game: str) -> dict:
    _count("poster")
    return {"n": len(rev.load(f"game/{game}").clip)}


@dat.fn
def chain(rev, *, game: str) -> dict:
    _count("chain")
    return {"thumb": rev.run("ledger_kinds.cut", game=game).hash[:8]}


@dat.fn
def folder(rev, *, game: str, path: Path) -> Dat:
    _count("folder")
    (path / "a.txt").write_text(game)
    return Dat(path)


@dat.fn
def placed(rev, *, game: str, path: Path = "games/{game}") -> Dat:
    _count("placed")
    (path / "g.txt").write_text(game)
    return Dat(path)


@dat.fn
def controls(rev, *, seal: int, clean: str, kwargs: dict, n: int = 0) -> dict:
    return {"seal": seal, "clean": clean, "kwargs": kwargs, "n": n}


@dat.fn
def wrong(rev, *, game: str) -> Cut:
    return {"not": "a cut"}


@dat.fn
def via_ref(rev, *, name: str) -> dict:
    return {"n": ledger_helper.twice(len(Ref(rev, name).load().data))}


@dat.fn
def via_ref_preds(rev, *, name: str) -> dict:
    return {"game": Ref(rev, name).preds.get("game")}


@dat.fn
def via_refs_rev(rev, *, game: str) -> dict:
    r = rev.refs(game=game)[0]
    return {"note": r.rev.get(r.subject, "note")}


@dat.fn
def maybe(rev, *, game: str) -> dict:
    hit = rev.run("ledger_kinds.cut", game=game, seal="get")
    return {"had": hit is not None}


@dat.fn
def scratchy(rev, *, game: str, path: Path) -> dict:
    CALLS["work"] = path
    (path / "tmp.txt").write_text(game)
    return {"game": game}


@dat.fn
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

    def encode(self, out) -> None:
        from dvc_dat.ledger.codec import sha256

        out.write(sha256(self.data).encode())

    def _parts(self):
        import io

        from dvc_dat.ledger.codec import sha256

        return [(sha256(self.data), lambda: io.BytesIO(self.data))]

    @classmethod
    def decode(cls, src, store) -> "Blobby":
        with store.open(src.read().decode()) as part:
            return cls(part.read())


@ledger_class(preds=("game", "take"))
class GameDat(Dat):
    """A folder value with preds: the seal-record tests reopen it in another process."""


def build_table(dat, n=10, start=1):
    """A dat's run function (``Dat.ns`` / ``rev.run``): ``table.csv``, ``cells`` in the results, saved."""
    _count("build_table")
    Path(dat.get_path(), "table.csv").write_text(f"{n} from {start}\n")
    dat.get_results()["cells"] = n * n
    dat.save()
    return dat


#: A spec by its dotted name, imported (``rev.run("ledger_kinds.TABLE_SPEC")``).
TABLE_SPEC = {"dat": {"do": "ledger_kinds.build_table", "kwargs": {"n": 12, "start": 1}}}


def never_saves(dat, n=1):
    """A run function that leaves its dat open."""
    Path(dat.get_path(), "x.txt").write_text(str(n))


@ledger_class(preds=("note",))
class NotedDat(Dat):
    """A dat kind declaring one pred of its own beside its folder's."""


#: One MiB block a ``Streamed`` value writes again and again.
MIB = bytes(range(256)) * 4096
#: Encode calls per class name (the one-encode-per-seal tests read it).
ENCODES = {}


class Streamed(Value):
    """A value of ``blocks`` MiB generated block by block: its bytes are never whole in memory (DAT 240)."""

    def __init__(self, blocks: int):
        self.blocks = blocks

    def encode(self, out) -> None:
        ENCODES["Streamed"] = ENCODES.get("Streamed", 0) + 1
        for _ in range(self.blocks):
            out.write(MIB)

    @classmethod
    def decode(cls, src, store):
        n = 0
        for block in iter(lambda: src.read(1 << 20), b""):
            n += len(block)
        return cls(n >> 20)


# -- SVP 1521: what a run reads through any Rev but its recording one, and dat.at ------------------------------

@dat.fn
def reads_foreign(rev, *, where: str, name: str) -> dict:
    """Reads ``name`` off the ledger at ``where``, through a ``Rev`` that records nothing."""
    _count("reads_foreign")
    return {"seen": Ledger(where).at().load(name).obj, "home": rev["game/G1", "home"]}


@dat.fn
def reads_foreign_nested(rev, *, where: str, name: str) -> dict:
    """Reads one foreign value itself and calls ``reads_foreign``, which reads another."""
    return {"mine": Ledger(where).at().load("mine").obj,
            "inner": rev.run("ledger_kinds.reads_foreign", where=where, name=name).obj}


@dat.fn
def reads_foreign_in_threads(rev, *, where: str, name: str) -> dict:
    """The read in a thread the body started, which inherits no context."""
    import threading

    out = {}
    t = threading.Thread(target=lambda: out.update(seen=Ledger(where).at().load(name).obj))
    t.start()
    t.join()
    return out


@dat.fn
def runs_foreign(rev, *, where: str, n: int) -> dict:
    """A run on another ledger, called from a body."""
    return {"n": Ledger(where).at().run("ledger_kinds.doubled", n=n).obj}


@dat.fn
def doubled(rev, *, n: int) -> dict:
    return {"n": 2 * n}


@dat.fn
def reads_row_only(rev, *, where: str) -> dict:
    """A raw triple on another ledger: not tracked."""
    return {"home": Ledger(where).at()["game/G1", "home"]}


@dat.fn
def reads_key(rev, *, clip) -> dict:
    """A value key, loaded through its own ``Ref``: it is in the keys already."""
    return {"seen": clip.load().obj}


def reads_at(dat, name):
    """A dat's run function reading through ``dat.at``."""
    dat.get_results()["out"] = dat.at.load(name).obj
    dat.get_results()["recording"] = dat.at._rec is not None
    dat.get_results()["rev"] = dat.at.id
    dat.get_results()["seen"] = dat.run.get_results()["dat"]["run_rev"]
    dat.save()


def reads_mounted(dat):
    """A dat's run function reading a name through the manager's namespace."""
    from dvc_dat.core import Dat

    dat.get_results()["rev"] = Dat.manager.ns.rev().id
    dat.save()


@dat.fn
def calls_doubled(rev, *, n: int) -> dict:
    return {"n": rev.run("ledger_kinds.doubled", n=n).obj["n"]}


def runs_plain_inside(dat):
    """A dat's run function running a plain dat inside."""
    from dvc_dat.core import Dat

    inner = Dat.manager.run({"dat": {"do": "ledger_kinds.build_table", "kwargs": {"n": 2}}})
    dat.get_results()["inner"] = Dat.get(inner.run.get_results(), "dat.run_rev")
    dat.save()


def makes_a_subdat(dat):
    """A dat's run function that makes a subdat by a nested run inside its own folder (SVP 241)."""
    Dat.manager.run({"dat": {"do": "ledger_kinds.build_table", "name": str(dat.path / "viz"),
                             "kwargs": {"n": 2, "start": 1}}})
    dat.get_results()["cells"] = 4
    dat.save()
    return dat


@ledger_class(preds=("i",))
class NumberedDat(Dat):
    """A dat carrying one declared pred."""
