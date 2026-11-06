"""A value's encoding is deterministic and lossless (SVP 1542): equal values encode to the same bytes in any
process on any machine, and ``decode`` gives back an equal value whose encoding is those bytes.

Each shipped class is measured against both clauses. A case the class breaks today is ``xfail(strict=True)``:
changing a class's encoding moves the hash of everything stored under it, a migration the owner decides, so the
failure stays visible here and turns the suite red the day the class is fixed. ``test_the_harness_...`` prove
the assertions can fail, and a new class with its own ``encode`` fails ``test_every_encoding_is_measured_here``
until it is added.
"""

import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

import dvc_dat
from dvc_dat import Dat, DatManager, core
from dvc_dat.ledger import Code, Value
from dvc_dat.ledger.codec import sha256

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
    raise TypeError(type(a))


def assert_same_bytes(a, b):
    assert encoded(a) == encoded(b)


def assert_round_trips(value):
    """Encode, decode, encode gives the same bytes."""
    assert encoded(decoded(value)) == encoded(value)


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
                              env={**os.environ, "PYTHONHASHSEED": str(seed)})
        assert done.returncode == 0, done.stderr
        out[seed] = json.loads(done.stdout)
    return out


def breaks(reason, raises=AssertionError):
    return pytest.mark.xfail(strict=True, raises=raises, reason=reason)


PICKLE_ORDER = "Blob: pickle writes a dict in insertion order and a set in iteration order"
PICKLE_MEMO = "Blob: pickle's memo records object identity, so a repeated object and an equal copy differ"
SET_REBUILT = "Blob: a decoded set is rebuilt by inserts, so its iteration order, and its pickle, can move"
PARQUET_CHUNKS = "Table: parquet's pages follow the table's chunks, and a long table decodes in 131072-row chunks"
PARQUET_META = "Table: the schema metadata (pandas adds its own) is in the bytes and outside Table.equals"
PARQUET_VERSION = "Table: the footer names the pyarrow version, so a pyarrow upgrade moves every hash"
SPEC_ORDER = "Dat: core writes _spec_.yaml in the spec's key order; sv-pipe's LedgerDat sorts what it stores"
CODE_NO_DECODE = "Code: decode is not implemented, and encode omits the description decode would have to restore"


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
    assert own == {Blob, Table, Dat, Code}


# --- lossless -------------------------------------------------------------------------------------------------

ROUND_TRIPS = [
    pytest.param(lambda: Blob([1, "a", 2.5, None, True]), id="blob-scalars"),
    pytest.param(lambda: Blob({"a": [1, {"b": (2, 3)}], "c": b"x"}), id="blob-nested"),
    pytest.param(lambda: Blob(shuffled(PLAYERS)), id="blob-dict"),
    pytest.param(lambda: Blob([TEXT, TEXT]), id="blob-shared"),
    pytest.param(lambda: Blob([TEXT, split(TEXT)]), id="blob-copies"),
    pytest.param(lambda: Blob(churned()), id="blob-set", marks=breaks(SET_REBUILT)),
    pytest.param(lambda: Table(pa.table(rows())), id="table-arrow"),
    pytest.param(lambda: Table(frame()), id="table-pandas"),
    pytest.param(lambda: Table(pa.table(rows()).slice(0, 0)), id="table-empty"),
    pytest.param(lambda: Table(pa.table({"s": pa.array(["a", "b", "a"]).dictionary_encode()})), id="table-dictionary"),
    pytest.param(lambda: Table(pa.table(rows()).replace_schema_metadata({"k": "v"})), id="table-metadata"),
    pytest.param(lambda: Table(pa.table({"x": np.arange(READ_BATCH)})), id="table-one-batch"),
    pytest.param(lambda: Table(long_table()), id="table-long", marks=breaks(PARQUET_CHUNKS)),
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


def stored_and_back(L, dat, name):
    """``dat`` saved on ``L`` and loaded back, from the store."""
    dat.seal(L, name=name)
    L._values.clear()
    return L.at().load(name)


def test_a_dat_comes_back_equal_with_the_same_bytes(L, tmp_path):
    dat = plain_folder(tmp_path / "f")
    bytes_before = encoded(dat)
    back = stored_and_back(L, dat, "f/1")
    assert encoded(back) == bytes_before and back.path != tmp_path / "f"
    assert same(plain_folder(tmp_path / "again"), back)


def test_a_dat_with_a_spec_comes_back_equal_with_the_same_bytes(L, tmp_path):
    dat = created(tmp_path / "f")
    bytes_before, content = encoded(dat), files(dat)
    back = stored_and_back(L, dat, "f/1")
    assert encoded(back) == bytes_before and files(back) == content


def test_a_dat_with_a_run_comes_back_with_the_same_bytes(L, tmp_path):
    before = core._default_manager
    Dat.manager = DatManager(dat_folders=[str(tmp_path / "data")])
    try:
        spec = {"dat": {"do": "ledger_kinds.build_table", "name": "t/{unique}", "kwargs": {"n": 3}}}
        dat = Dat.manager.run(spec)
        assert (dat.path / "run").is_dir() and "run/_spec_.yaml" not in json.loads(encoded(dat))["files"]
        bytes_before = encoded(dat)
        back = stored_and_back(L, dat, "t/1")
        assert encoded(back) == bytes_before
    finally:
        core._default_manager = before
        if before is not None:
            Dat.manager = before


@pytest.mark.xfail(strict=True, raises=NotImplementedError, reason=CODE_NO_DECODE)
def test_a_code_decodes():
    assert_round_trips(code())


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
    pytest.param(lambda f: Blob(dict(PLAYERS)), lambda f: Blob(shuffled(PLAYERS)), id="blob-dict-other-order",
                 marks=breaks(PICKLE_ORDER)),
    pytest.param(lambda f: Blob({"outer": dict(PLAYERS)}), lambda f: Blob({"outer": shuffled(PLAYERS)}),
                 id="blob-nested-dict-other-order", marks=breaks(PICKLE_ORDER)),
    pytest.param(lambda f: Blob([TEXT, TEXT]), lambda f: Blob([TEXT, split(TEXT)]), id="blob-identity-versus-copy",
                 marks=breaks(PICKLE_MEMO)),
    pytest.param(lambda f: Table(pa.table(rows())), lambda f: Table(pa.table(rows())), id="table-arrow"),
    pytest.param(lambda f: Table(frame()), lambda f: Table(frame().copy()), id="table-pandas"),
    pytest.param(lambda f: Table(long_table()), lambda f: Table(chunked(1000)), id="table-short-chunk"),
    pytest.param(lambda f: Table(long_table()), lambda f: Table(chunked(READ_BATCH)), id="table-other-chunks",
                 marks=breaks(PARQUET_CHUNKS)),
    pytest.param(lambda f: Table(frame()), lambda f: Table(pa.table({"x": [1, 2, 3], "s": ["a", "b", "c"]})),
                 id="table-pandas-versus-arrow", marks=breaks(PARQUET_META)),
    pytest.param(lambda f: Table(pa.table(rows())), lambda f: Table(pa.table(rows()).replace_schema_metadata({"k": "v"})),
                 id="table-other-metadata", marks=breaks(PARQUET_META)),
    pytest.param(lambda f: plain_folder(f / "a"), lambda f: plain_folder(f / "b", ("é.txt", "sub/b.txt", "a.txt")),
                 id="dat-files-other-order"),
    pytest.param(lambda f: created(f / "a"), lambda f: created(f / "b"), id="dat-spec-other-path"),
    pytest.param(lambda f: created(f / "a", {"n": 1, "m": 2}), lambda f: created(f / "b", {"m": 2, "n": 1}),
                 id="dat-spec-other-key-order", marks=breaks(SPEC_ORDER)),
    pytest.param(lambda f: code(), lambda f: code(modules=shuffled(code()._manifest["modules"])),
                 id="code-modules-other-order"),
    pytest.param(lambda f: code(), lambda f: code(version="2.0.0", commit="abc1234", sandboxed=True),
                 id="code-other-description"),
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


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=PARQUET_VERSION)
def test_table_bytes_do_not_name_the_pyarrow_version():
    assert pa.__version__.encode() not in encoded(Table(pa.table(rows())))


# --- deterministic: the same value in processes of their own, under other hash seeds -----------------------------

@pytest.mark.parametrize("name", [
    "blob-scalars", "blob-nested", "blob-dict", "blob-array", "blob-shared", "blob-copies",
    pytest.param("blob-set", marks=breaks(PICKLE_ORDER)),
    "table-arrow", "table-pandas", "table-long", "dat-plain", "dat-created", "code",
])
def test_every_process_gives_the_same_bytes(name, elsewhere, tmp_path):
    assert_one_hash([sha256(encoded(BUILT[name](tmp_path))), *(elsewhere[seed][name] for seed in SEEDS)])
