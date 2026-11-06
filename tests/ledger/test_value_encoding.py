"""A value's encoding is deterministic and lossless (SVP 1542): equal values encode to the same bytes in any
process on any machine, and ``decode`` gives back an equal value whose encoding is those bytes.

Each shipped class is measured against both clauses. A case the class breaks today is ``xfail(strict=True)``:
changing a class's encoding moves the hash of everything stored under it, a migration the owner decides, so the
failure stays visible here and turns the suite red the day the class is fixed. ``test_the_harness_...`` prove
the assertions can fail, and a new class with its own ``encode`` fails ``test_every_encoding_is_measured_here``
until it is added. ``Video`` (SVP 249) is measured on its stored form, and its sources' conversion is the limit
its class states: ``canonical=False`` keeps a source's codec, so equal frames in two encodings are two values.
"""

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

import dvc_dat
from dvc_dat import Dat, DatManager, core
from dvc_dat.ledger import Code, Value, Video
from dvc_dat.ledger.codec import sha256
from dvc_dat.ledger.video import DEFAULT_STANDARD

Blob, Table = Value.Blob, Value.Table
HERE = Path(__file__).parent

#: The rows ``pq.read_table`` hands back per chunk: a longer table decodes in several chunks.
READ_BATCH = 131072
LONG = 300_000
SEEDS = (1, 2, 3)


def encoded(value):
    out = io.BytesIO()
    value.encode(out)
    return out.getvalue()


def decoded(value):
    return type(value).decode(io.BytesIO(encoded(value)), None)


def arrow(value):
    t = value.table
    return t if isinstance(t, pa.Table) else pa.Table.from_pandas(t)


def files(dat):
    """A dat's content: its spec as data, and every other file's bytes."""
    found = {rel: p.read_bytes() for rel, p in dat._walk() if rel != "_spec_.yaml"}
    return dat.get_spec(), found


def same(a, b):
    """Are ``a`` and ``b`` equal values? By content, whatever their bytes: no ``Value`` defines ``__eq__``."""
    assert type(a) is type(b)
    if isinstance(a, Blob):
        return a.obj == b.obj
    if isinstance(a, Table):
        return arrow(a).equals(arrow(b))
    if isinstance(a, Dat):
        return files(a) == files(b)
    if isinstance(a, Code):
        return (a.modules, encoded(a)) == (b.modules, encoded(b))
    if isinstance(a, Video):
        return all((x == y).all() for x, y in zip(a.iter(), b.iter())) and \
            a._info()["frames"] == b._info()["frames"]
    raise TypeError(type(a))


def assert_same_bytes(a, b):
    """Compared by sha256: pytest's diff of two megabytes of bytes runs for many minutes."""
    assert sha256(encoded(a)) == sha256(encoded(b))


def assert_round_trips(value):
    """Encode, decode, encode gives the same bytes (by sha256, as above)."""
    assert sha256(encoded(decoded(value))) == sha256(encoded(value))


def assert_one_hash(hashes):
    assert len(set(hashes)) == 1, hashes


# --- what is measured, by name, so a child process can build the same values ---------------------------------

TEXT = "a string long enough not to be interned"


def split(text):
    """An equal string that is a different object."""
    copy = "".join(list(text))
    assert copy is not text
    return copy


def shuffled(items):
    """A dict of ``items``, inserted in reverse."""
    return dict(reversed(list(items.items())))


PLAYERS = {f"player-{i}": i for i in range(20)}


class Box:
    """An object other than plain data, equal by its contents."""

    def __init__(self, held):
        self.held = held

    def __eq__(self, other):
        return type(other) is Box and self.held == other.held


BOX = Box(dict(PLAYERS))


def churned():
    """A set that grew and shrank: ``1`` and ``8`` iterate in that order in its large table, and a rebuilt set's
    small table holds them the other way round. Ints, so no hash seed changes it."""
    numbers = set(range(1000))
    for n in range(1000):
        if n not in (1, 8):
            numbers.discard(n)
    return numbers


def long_table():
    return pa.table({"x": np.arange(LONG)})


def rows():
    return {"x": [1, 2, None], "s": ["a", "b", "c"]}


def frame():
    return pd.DataFrame({"x": [1, 2, 3], "s": ["a", "b", "c"]})


def plain_folder(folder, names=("a.txt", "sub/b.txt", "é.txt")):
    """A folder of files with no spec, written in the order given."""
    for rel in names:
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rel)
    return Dat(folder)


def created(folder, kwargs=None):
    """A dat ``create`` wrote at ``folder``, from a spec."""
    manager = DatManager(dat_folders=[str(folder.parent / "data")])
    dat = manager.create({"dat": {"kwargs": kwargs or {"n": 1, "m": 2}}}, path=str(folder))
    dat.save()
    return dat


def code(modules=None, **description):
    fields = {"modules": modules or {"pkg/a.py": "1" * 64, "pkg/b.py": "2" * 64}, "mounts_hash": "3" * 16,
              "mounts": {}, "commit": None, "lock": None, "sandboxed": False, "version": "1.0.0"}
    return Code({**fields, **description}, unit="pkg")


FFMPEG = shutil.which("ffmpeg") is not None or bool(os.environ.get("CI"))
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not on PATH (CI installs it)")


def video_frames():
    """20 frames, 32x24, each a grey level with a white square that moves."""
    out = []
    for i in range(20):
        f = np.full((24, 32, 3), i * 9, np.uint8)
        f[i % 16:i % 16 + 8, i:i + 8] = 255
        out.append(f)
    return out


def standard(video):
    """``video`` converted to the default standard, as a seal onto a ledger that declares it converts it."""
    video.__dict__["_mode"] = DEFAULT_STANDARD
    return video


def video_file(folder, name, *args):
    """``video_frames`` written by ffmpeg to ``folder/name`` with the codec arguments ``args``."""
    folder.mkdir(parents=True, exist_ok=True)
    raw = b"".join(f.tobytes() for f in video_frames())
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "32x24", "-r", "10",
                    "-i", "pipe:0", *args, str(folder / name)], input=raw, check=True)
    return folder / name


def lossless(folder, preset):
    """The frames in H.264 with no loss, by an encoder preset: other bytes, the same frames."""
    return video_file(folder, f"{preset}.mp4", "-c:v", "libx264", "-qp", "0", "-preset", preset,
                      "-pix_fmt", "yuv444p")


class Scrambled(Value):
    """The control: what breaks the rule. Its bytes follow a set's order, and ``decode`` keeps none of them."""

    def __init__(self, words):
        self.words = words

    def encode(self, out):
        out.write(",".join(self.words).encode())

    @classmethod
    def decode(cls, src, store):
        return cls({"gone"})


#: Name -> a value built from nothing but its folder, the same in every process.
BUILT = {
    "blob-scalars": lambda f: Blob([1, "a", 2.5, None, True]),
    "blob-nested": lambda f: Blob({"a": [1, {"b": (2, 3)}], "c": b"x"}),
    "blob-dict": lambda f: Blob(dict(PLAYERS)),
    "blob-array": lambda f: Blob(np.arange(5.0)),
    "blob-shared": lambda f: Blob([TEXT, TEXT]),
    "blob-copies": lambda f: Blob([TEXT, split(TEXT)]),
    "blob-set": lambda f: Blob(set(PLAYERS)),
    "table-arrow": lambda f: Table(pa.table(rows())),
    "table-pandas": lambda f: Table(frame()),
    "table-long": lambda f: Table(long_table()),
    "dat-plain": lambda f: plain_folder(f / "plain"),
    "dat-created": lambda f: created(f / "created"),
    "code": lambda f: code(),
    "control": lambda f: Scrambled(set(PLAYERS)),
}
if FFMPEG:
    BUILT["video"] = lambda f: standard(Video.from_frames(iter(video_frames()), 10))


def child_hashes():
    """Run as a child process: each ``BUILT`` value's sha256, as JSON, under its folder ``argv[1]``."""
    folder = Path(sys.argv[1])
    print(json.dumps({k: sha256(encoded(build(folder))) for k, build in BUILT.items()}))


@pytest.fixture(scope="module")
def elsewhere(tmp_path_factory):
    """``{seed: {name: sha256}}``: every value built in a process of its own under each ``PYTHONHASHSEED``."""
    out = {}
    code_text = f"import sys; sys.path.insert(0, {str(HERE)!r}); import test_value_encoding as m; m.child_hashes()"
    for seed in SEEDS:
        folder = tmp_path_factory.mktemp(f"seed{seed}")
        done = subprocess.run([sys.executable, "-c", code_text, str(folder)], capture_output=True, text=True,
                              env={**os.environ, "PYTHONHASHSEED": str(seed)}, timeout=120)
        assert done.returncode == 0, done.stderr
        out[seed] = json.loads(done.stdout)
    return out


def breaks(reason, raises=AssertionError):
    return pytest.mark.xfail(strict=True, raises=raises, reason=reason)


OBJECT_ORDER = "Blob: an object other than plain data is pickled as pickle writes it, its state in insertion order"
OBJECT_MEMO = "Blob: an object other than plain data repeated is written as a back-reference, an equal copy in full"
VIDEO_SOURCE = "Video: canonical=False keeps the source's codec, so equal frames in two encodings are two values"


# --- the harness can fail -------------------------------------------------------------------------------------

def test_the_harness_catches_bytes_that_differ():
    with pytest.raises(AssertionError):
        assert_same_bytes(Scrambled(["a", "b"]), Scrambled(["b", "a"]))


def test_the_harness_catches_a_lossy_decode():
    with pytest.raises(AssertionError):
        assert_round_trips(Scrambled(["a", "b"]))


def test_the_harness_catches_bytes_that_move_with_the_hash_seed(elsewhere):
    with pytest.raises(AssertionError):
        assert_one_hash(elsewhere[seed]["control"] for seed in SEEDS)


def test_every_encoding_is_measured_here():
    """A ``dvc_dat`` class with its own ``encode`` is a new encoding: it gets its cases in this file."""
    def under(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from under(sub)

    own = {c for c in under(Value) if c.__module__.startswith(dvc_dat.__name__) and "encode" in c.__dict__}
    assert own == {Blob, Table, Dat, Code, Video}


# --- lossless -------------------------------------------------------------------------------------------------

ROUND_TRIPS = [
    pytest.param(lambda: Blob([1, "a", 2.5, None, True]), id="blob-scalars"),
    pytest.param(lambda: Blob({"a": [1, {"b": (2, 3)}], "c": b"x"}), id="blob-nested"),
    pytest.param(lambda: Blob(shuffled(PLAYERS)), id="blob-dict"),
    pytest.param(lambda: Blob([TEXT, TEXT]), id="blob-shared"),
    pytest.param(lambda: Blob([TEXT, split(TEXT)]), id="blob-copies"),
    pytest.param(lambda: Blob(churned()), id="blob-set"),
    pytest.param(lambda: Blob({frozenset({1, 2}): {3.5, float("nan")}, (1, "a"): {b"x": [TEXT, TEXT]}}), id="blob-mixed"),
    pytest.param(lambda: Table(pa.table(rows())), id="table-arrow"),
    pytest.param(lambda: Table(frame()), id="table-pandas"),
    pytest.param(lambda: Table(pa.table(rows()).slice(0, 0)), id="table-empty"),
    pytest.param(lambda: Table(pa.table({"s": pa.array(["a", "b", "a"]).dictionary_encode()})), id="table-dictionary"),
    pytest.param(lambda: Table(pa.table(rows()).replace_schema_metadata({"k": "v"})), id="table-metadata"),
    pytest.param(lambda: Table(pa.table({"x": np.arange(READ_BATCH)})), id="table-one-batch"),
    pytest.param(lambda: Table(long_table()), id="table-long"),
]


@pytest.mark.parametrize("make", ROUND_TRIPS)
def test_encode_decode_encode_gives_the_same_bytes(make):
    assert_round_trips(make())


@pytest.mark.parametrize("make", [
    lambda: Blob(churned()),
    lambda: Blob(np.arange(5.0).tolist()),
    lambda: Table(frame()),
    lambda: Table(long_table()),
], ids=["blob-set", "blob-list", "table-pandas", "table-long"])
def test_decode_gives_back_an_equal_value(make):
    value = make()
    assert same(value, decoded(value))


def test_a_blob_of_plain_data_that_contains_itself_is_pickled_as_given():
    loop = {"a": [1, 2]}
    loop["self"] = loop
    back = decoded(Blob(loop)).obj
    assert back["self"] is back and back["a"] == [1, 2]


def stored_and_back(L, dat, name):
    """``dat`` saved on ``L`` and loaded back, from the store."""
    dat.seal(L, name=name)
    L._values.clear()
    return L.at().load(name)


def test_a_dat_comes_back_equal_with_the_same_bytes(L, tmp_path):
    dat = plain_folder(tmp_path / "f")
    bytes_before = encoded(dat)
    back = stored_and_back(L, dat, "f/1")
    assert sha256(encoded(back)) == sha256(bytes_before) and back.path != tmp_path / "f"
    assert same(plain_folder(tmp_path / "again"), back)


def test_a_dat_with_a_spec_comes_back_equal_with_the_same_bytes(L, tmp_path):
    dat = created(tmp_path / "f")
    bytes_before, content = encoded(dat), files(dat)
    back = stored_and_back(L, dat, "f/1")
    assert sha256(encoded(back)) == sha256(bytes_before) and files(back) == content


def test_a_dat_with_a_run_comes_back_with_the_same_bytes(L, tmp_path):
    before = core._default_manager
    Dat.manager = DatManager(dat_folders=[str(tmp_path / "data")])
    try:
        spec = {"dat": {"do": "ledger_kinds.build_table", "name": "t/{unique}", "kwargs": {"n": 3}}}
        dat = Dat.manager.run(spec)
        assert (dat.path / "run").is_dir() and "run/_spec_.yaml" not in json.loads(encoded(dat))["files"]
        bytes_before = encoded(dat)
        back = stored_and_back(L, dat, "t/1")
        assert sha256(encoded(back)) == sha256(bytes_before)
    finally:
        core._default_manager = before
        if before is not None:
            Dat.manager = before


def test_a_code_decodes():
    assert_round_trips(code())
    assert same(code(), decoded(code()))


def test_a_code_decoded_by_its_name_keeps_its_unit_and_version():
    """The description is not the identity, so it is not in the bytes: the name restores the unit and version,
    and nothing restores the commit, lock or mounts (SVP 1543)."""
    mounted = code(mounts_hash="4" * 16, sandboxed=True, commit="abc1234", mounts={"pkg": {"repo": "r", "root": "."}})
    back = Code.decode(io.BytesIO(encoded(mounted)), None, name="pkg@1.0.0")
    assert (back.name, back.hash, back.sandboxed) == ("pkg@1.0.0", mounted.hash, True)
    assert (back.commit, back.lock, back.mounts) == (None, None, {})
    installed = code(mounts_hash=None)
    bare = Code.decode(io.BytesIO(encoded(installed)), None)
    assert (bare.name, bare.hash, bare.sandboxed) == ("code@#" + installed.hash[:8], installed.hash, False)


@needs_ffmpeg
def test_a_video_comes_back_with_the_same_bytes(L, tmp_path, monkeypatch):
    """A ``Video``'s value is its stored segments and manifest: loaded back, it encodes to the bytes it was
    saved with, and decodes to the same frames. (``L`` declares no standard, so the seal converts as the hash
    before it did.)"""
    from dvc_dat.ledger import video as video_mod

    monkeypatch.setattr(video_mod, "_WARNED", set())
    v = Video.from_frames(iter(video_frames()), 10)
    bytes_before = encoded(v)
    with pytest.warns(UserWarning, match="canonical=False"):
        v.seal(L, name="video/a")
    L._values.clear()
    back = L.at().load("video/a")
    assert sha256(encoded(back)) == sha256(bytes_before) and same(v, back)


# --- deterministic: equal values built separately, here --------------------------------------------------------

def chunked(*cuts):
    table = long_table()
    edges = [0, *cuts, LONG]
    return pa.concat_tables([table.slice(a, b - a) for a, b in zip(edges, edges[1:])])


PAIRS = [
    pytest.param(lambda f: Blob([1, "a", 2.5]), lambda f: Blob([1, "a", 2.5]), id="blob-scalars"),
    pytest.param(lambda f: Blob(dict(PLAYERS)), lambda f: Blob(dict(PLAYERS)), id="blob-dict-same-order"),
    pytest.param(lambda f: Blob([split(TEXT), split(TEXT)]), lambda f: Blob([split(TEXT), split(TEXT)]),
                 id="blob-copies-both"),
    pytest.param(lambda f: Blob(dict(PLAYERS)), lambda f: Blob(shuffled(PLAYERS)), id="blob-dict-other-order"),
    pytest.param(lambda f: Blob({"outer": dict(PLAYERS)}), lambda f: Blob({"outer": shuffled(PLAYERS)}),
                 id="blob-nested-dict-other-order"),
    pytest.param(lambda f: Blob([TEXT, TEXT]), lambda f: Blob([TEXT, split(TEXT)]), id="blob-identity-versus-copy"),
    pytest.param(lambda f: Blob({"s": set(PLAYERS)}), lambda f: Blob({"s": set(reversed(list(PLAYERS)))}),
                 id="blob-set-other-order"),
    pytest.param(lambda f: Blob({(1, "a"): 1, ("b",): 2, 3: 3}), lambda f: Blob({3: 3, ("b",): 2, (1, "a"): 1}),
                 id="blob-mixed-keys-other-order"),
    pytest.param(lambda f: Blob(Box(dict(PLAYERS))), lambda f: Blob(Box(shuffled(PLAYERS))),
                 id="blob-object-other-order", marks=breaks(OBJECT_ORDER)),
    pytest.param(lambda f: Blob(defaultdict(int, PLAYERS)), lambda f: Blob(defaultdict(int, shuffled(PLAYERS))),
                 id="blob-dict-subclass-other-order", marks=breaks(OBJECT_ORDER)),
    pytest.param(lambda f: Blob([BOX, BOX]), lambda f: Blob([BOX, Box(dict(PLAYERS))]),
                 id="blob-object-identity-versus-copy", marks=breaks(OBJECT_MEMO)),
    pytest.param(lambda f: Table(pa.table(rows())), lambda f: Table(pa.table(rows())), id="table-arrow"),
    pytest.param(lambda f: Table(frame()), lambda f: Table(frame().copy()), id="table-pandas"),
    pytest.param(lambda f: Table(long_table()), lambda f: Table(chunked(1000)), id="table-short-chunk"),
    pytest.param(lambda f: Table(long_table()), lambda f: Table(chunked(READ_BATCH)), id="table-other-chunks"),
    pytest.param(lambda f: Table(frame()), lambda f: Table(pa.table({"x": [1, 2, 3], "s": ["a", "b", "c"]})),
                 id="table-pandas-versus-arrow"),
    pytest.param(lambda f: Table(pa.table(rows())),
                 lambda f: Table(pa.table(rows()).replace_schema_metadata({"k": "v"})),
                 id="table-other-metadata"),
    pytest.param(lambda f: plain_folder(f / "a"), lambda f: plain_folder(f / "b", ("é.txt", "sub/b.txt", "a.txt")),
                 id="dat-files-other-order"),
    pytest.param(lambda f: created(f / "a"), lambda f: created(f / "b"), id="dat-spec-other-path"),
    pytest.param(lambda f: created(f / "a", {"n": 1, "m": 2}), lambda f: created(f / "b", {"m": 2, "n": 1}),
                 id="dat-spec-other-key-order"),
    pytest.param(lambda f: code(), lambda f: code(modules=shuffled(code()._manifest["modules"])),
                 id="code-modules-other-order"),
    pytest.param(lambda f: code(), lambda f: code(version="2.0.0", commit="abc1234", sandboxed=True),
                 id="code-other-description"),
    pytest.param(lambda f: standard(Video.from_frames(iter(video_frames()), 10)),
                 lambda f: standard(Video.from_frames(iter(video_frames()), "10/1")), id="video-frames",
                 marks=needs_ffmpeg),
    pytest.param(lambda f: Video.from_path(lossless(f / "a", "ultrafast")),
                 lambda f: Video.from_url(lossless(f / "b", "ultrafast").as_uri()), id="video-path-versus-url",
                 marks=needs_ffmpeg),
    pytest.param(lambda f: standard(Video.from_frames(iter(video_frames()), 10)),
                 lambda f: standard(Video.from_path(video_file(f, "v.mkv", "-c:v", "ffv1", "-pix_fmt", "yuv420p"))),
                 id="video-standard-frames-versus-file", marks=needs_ffmpeg),
    pytest.param(lambda f: standard(Video.from_path(lossless(f / "a", "ultrafast"))),
                 lambda f: standard(Video.from_path(lossless(f / "b", "veryslow"))),
                 id="video-standard-two-encodings", marks=needs_ffmpeg),
    pytest.param(lambda f: Video.from_path(lossless(f / "a", "ultrafast")),
                 lambda f: Video.from_path(lossless(f / "b", "veryslow")),
                 id="video-source-codec-two-encodings", marks=[needs_ffmpeg, breaks(VIDEO_SOURCE)]),
]


@pytest.mark.parametrize("left, right", [p.values for p in PAIRS], ids=[p.id for p in PAIRS])
def test_each_pair_measured_below_is_equal(left, right, tmp_path):
    """An xfail below says equal values differ, so each pair must be equal, whatever its marks."""
    assert same(left(tmp_path), right(tmp_path))


@pytest.mark.parametrize("left, right", PAIRS)
def test_equal_values_give_the_same_bytes(left, right, tmp_path):
    assert_same_bytes(left(tmp_path), right(tmp_path))


def test_a_code_hash_is_the_hash_of_its_encoding():
    assert code().hash == hashlib.sha256(encoded(code())).hexdigest()


def test_table_bytes_do_not_name_the_pyarrow_version():
    assert pa.__version__.encode() not in encoded(Table(pa.table(rows())))


def test_table_bytes_are_parquet_that_names_dvc_dat_as_its_writer():
    import pyarrow.parquet as pq

    data = encoded(Table(frame()))
    assert pq.ParquetFile(io.BytesIO(data)).metadata.created_by == "dvc-dat Value.Table"
    assert pd.read_parquet(io.BytesIO(data)).equals(frame())


def test_table_field_metadata_is_not_in_the_bytes():
    plain = pa.table(rows())
    tagged = plain.cast(pa.schema([f.with_metadata({"unit": "m"}) for f in plain.schema]))
    assert_same_bytes(Table(plain), Table(tagged))


# --- deterministic: the same value in processes of their own, under other hash seeds -----------------------------

@pytest.mark.parametrize("name", [
    "blob-scalars", "blob-nested", "blob-dict", "blob-array", "blob-shared", "blob-copies",
    "blob-set",
    "table-arrow", "table-pandas", "table-long", "dat-plain", "dat-created", "code",
    pytest.param("video", marks=needs_ffmpeg),
])
def test_every_process_gives_the_same_bytes(name, elsewhere, tmp_path):
    assert_one_hash([sha256(encoded(BUILT[name](tmp_path))), *(elsewhere[seed][name] for seed in SEEDS)])
